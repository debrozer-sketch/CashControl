"""
VNC Preview — pure-Python RFB client with colour-depth buttons.

Quality buttons (horizontal, below VNC area, inside VncPreviewWidget):
  [ 8 бит ]  [ 16 бит ]  [ 32 бит ]

All RFB socket I/O is confined to ``_VNCWorker``.  The worker never touches a
QWidget or QImage: it posts small events through a Qt signal bridge and the GUI
thread owns the framebuffer and paints it.
"""


from __future__ import annotations

import asyncio
import contextlib
import queue
import socket
import struct
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, override

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cashcontrol.infrastructure.audit_logger import audit_log, get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from cashcontrol.core.session import CashSession

logger = get_logger()


# ── Colour-depth presets ───────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class _DepthPreset:
    """Wire pixel format requested from the RFB server."""

    label: str
    tooltip: str
    bpp: int
    depth: int
    true_colour: int
    r_max: int
    g_max: int
    b_max: int
    r_shift: int
    g_shift: int
    b_shift: int


_DEPTH_PRESETS: tuple[_DepthPreset, ...] = (
    _DepthPreset(
        "8 бит",
        "8 бит — минимальный трафик\nИндексированный цвет (256 цветов)",
        8, 8, 0, 0, 0, 0, 0, 0, 0,
    ),
    _DepthPreset(
        "16 бит",
        "16 бит — сниженный трафик\nRGB565 (65536 цветов)",
        16, 16, 1, 31, 63, 31, 11, 5, 0,
    ),
    _DepthPreset(
        "32 бит",
        "32 бит — полное качество\nRGB True Color (по умолчанию)",
        32, 24, 1, 255, 255, 255, 16, 8, 0,
    ),
)
_DEFAULT_DEPTH_IDX = 2  # 32 бит


# ── Pointer wheel button masks (RFB buttons 4/5) ───────────────────────────

_WHEEL_UP_MASK = 8
_WHEEL_DOWN_MASK = 16


_X11VNC_CMD = (
    "X11VNC=$(which x11vnc 2>/dev/null "
    "|| ls /usr/local/bin/x11vnc /usr/bin/x11vnc 2>/dev/null | head -1); "
    "[ -z \"$X11VNC\" ] && exit 1; "
    "DISP=$(w -h 2>/dev/null | awk '{print $3}' | grep -m1 ^: || echo :0); "
    "sudo killall x11vnc 2>/dev/null; sleep 0.3; "
    "nohup \"$X11VNC\" -display \"$DISP\" -forever -shared -bg "
    "-listen 0.0.0.0 -rfbport 5900 -nopw "
    "</dev/null >/dev/null 2>&1 &"
)
_VNC_START_DELAY = 5.0


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL STATES / COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

class _ConnState:
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    ERROR = 3


class _Cmd:
    DISCONNECT = 0
    KEY_EVENT = 1
    POINTER_EVENT = 2
    FULL_UPDATE = 3
    SET_DEPTH = 4


class _VNCError(RuntimeError):
    """A user-presentable RFB protocol or connection error."""


class _WorkerStoppedError(Exception):
    """Internal non-error path used when the GUI asks a worker to stop."""


_QT_KEYSYM: dict[int, int] = {
    Qt.Key.Key_Escape: 0xFF1B,
    Qt.Key.Key_Tab: 0xFF09,
    Qt.Key.Key_Backspace: 0xFF08,
    Qt.Key.Key_Return: 0xFF0D,
    Qt.Key.Key_Enter: 0xFF8D,
    Qt.Key.Key_Delete: 0xFFFF,
    Qt.Key.Key_Home: 0xFF50,
    Qt.Key.Key_End: 0xFF57,
    Qt.Key.Key_Left: 0xFF51,
    Qt.Key.Key_Up: 0xFF52,
    Qt.Key.Key_Right: 0xFF53,
    Qt.Key.Key_Down: 0xFF54,
    Qt.Key.Key_PageUp: 0xFF55,
    Qt.Key.Key_PageDown: 0xFF56,
    Qt.Key.Key_Shift: 0xFFE1,
    Qt.Key.Key_Control: 0xFFE3,
    Qt.Key.Key_Alt: 0xFFE9,
    Qt.Key.Key_F1: 0xFFBE,
    Qt.Key.Key_F2: 0xFFBF,
    Qt.Key.Key_F3: 0xFFC0,
    Qt.Key.Key_F4: 0xFFC1,
    Qt.Key.Key_F5: 0xFFC2,
    Qt.Key.Key_F6: 0xFFC3,
    Qt.Key.Key_F7: 0xFFC4,
    Qt.Key.Key_F8: 0xFFC5,
    Qt.Key.Key_F9: 0xFFC6,
    Qt.Key.Key_F10: 0xFFC7,
    Qt.Key.Key_F11: 0xFFC8,
    Qt.Key.Key_F12: 0xFFC9,
}


def _depth_preset(idx: int) -> _DepthPreset:
    """Return a preset and fail early instead of indexing a magic tuple."""
    if not 0 <= idx < len(_DEPTH_PRESETS):
        raise ValueError(f"Неизвестный индекс глубины VNC: {idx}")
    return _DEPTH_PRESETS[idx]


def _qt_to_keysym(key: int, text: str, mods: Qt.KeyboardModifier) -> int:
    if key in _QT_KEYSYM:
        return _QT_KEYSYM[key]
    if text and len(text) == 1:
        code = ord(text[0])
        if 0x20 <= code <= 0xFF:
            return code
        if code > 0xFF:
            return 0x01000000 | code
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return key if (mods & Qt.KeyboardModifier.ShiftModifier) else key + 32
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return key
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# VNC WORKER — all socket I/O in a background thread
# ══════════════════════════════════════════════════════════════════════════════

class _VNCWorker(threading.Thread):
    """Minimal RFB client worker.

    ``SetPixelFormat`` is serialized with framebuffer requests.  There is at
    most one outstanding FramebufferUpdateRequest; this is important when a
    colour mode changes because an already requested response must be decoded
    with the *old* format before the new format is sent to the server.
    """

    CONNECT_TIMEOUT = 10.0
    SOCK_TIMEOUT = 0.1
    KEEP_ALIVE = 0.2
    PARTIAL_READ_TIMEOUT = 30.0
    MAX_FRAMEBUFFER_PIXELS = 64_000_000  # 64M RGBA pixels ≈ 244 MiB
    MAX_SERVER_TEXT = 1_048_576

    def __init__(
        self,
        host: str,
        port: int,
        cmd_queue: queue.Queue[tuple],
        cbs: dict[str, Callable],
        depth_idx: int = _DEFAULT_DEPTH_IDX,
    ) -> None:
        super().__init__(daemon=True, name="VNCWorker")
        self.host = host
        self.port = port
        self._q = cmd_queue
        self._cbs = cbs
        _depth_preset(depth_idx)  # validate before the worker thread starts
        self._depth_idx = depth_idx
        self._pending_depth_idx: int | None = None
        self._pending_full_update = False
        self._update_outstanding = False
        self._last_request_at = 0.0

        self._sock: socket.socket | None = None
        self._socket_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._buf = bytearray()

        self.fb_w = 0
        self.fb_h = 0

        # Palette for 8-bit mode (RGB tuples).  numpy cache is created only
        # if an 8-bit frame really needs it.
        self._palette: list[tuple[int, int, int]] = [(0, 0, 0)] * 256
        self._palette_np = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Ask the thread to stop and actively unblock recv()/sendall()."""
        self._stop_event.set()
        self._close_socket()

    def run(self) -> None:
        try:
            self._connect()
            self._handshake()
            self._raise_if_stopped()

            # The GUI allocates its QImage only after this event.  Queue order
            # guarantees that it happens before any following frame event.
            self._cb("on_connected", self.fb_w, self.fb_h)
            self._send_pixel_format()
            self._send_encodings()
            self._request_update(incremental=False)

            sock = self._socket_or_raise()
            sock.settimeout(self.SOCK_TIMEOUT)
            self._main_loop()
        except _WorkerStoppedError:
            pass
        except Exception as exc:
            if not self._stop_event.is_set():
                message = str(exc) or "Неизвестная ошибка VNC"
                logger.error(
                    "[VNC worker] exception on %s: %s",
                    self.host,
                    message,
                    exc_info=True,
                )
                self._cb("on_error", message)
        finally:
            self._cleanup()
            self._cb("on_disconnected")

    def _connect(self) -> None:
        self._raise_if_stopped()
        try:
            sock = socket.create_connection(
                (self.host, self.port), timeout=self.CONNECT_TIMEOUT
            )
            sock.settimeout(self.CONNECT_TIMEOUT)
        except OSError as exc:
            if self._stop_event.is_set():
                raise _WorkerStoppedError from exc
            raise _VNCError(f"Нет соединения: {exc}") from exc

        # ``stop()`` may have run while create_connection() was blocking.
        with self._socket_lock:
            stopped = self._stop_event.is_set()
            if not stopped:
                self._sock = sock
        if stopped:
            with contextlib.suppress(OSError):
                sock.close()
            raise _WorkerStoppedError

    def _handshake(self) -> None:
        version = self._recv_required(12, "версии RFB")
        if not version.startswith(b"RFB ") or not version.endswith(b"\n"):
            raise _VNCError("Сервер прислал некорректную версию RFB")
        try:
            major = int(version[4:7])
            minor = int(version[8:11])
        except ValueError as exc:
            raise _VNCError("Сервер прислал некорректную версию RFB") from exc
        if major != 3:
            raise _VNCError(f"Неподдерживаемая версия RFB: {version!r}")

        # RFB 3.3 has a different security handshake.  x11vnc normally uses
        # 3.8, but accepting 3.3/3.7 makes the client less fragile.
        negotiated_minor = 8 if minor >= 8 else 7 if minor >= 7 else 3
        self._sendall(f"RFB 003.{negotiated_minor:03d}\n".encode("ascii"))

        if negotiated_minor == 3:
            security_type = struct.unpack(
                "!I", self._recv_required(4, "типа аутентификации")
            )[0]
            if security_type == 0:
                raise _VNCError(f"Сервер отказал: {self._read_failure_reason()}")
            if security_type != 1:
                raise _VNCError(self._unsupported_security_message(security_type))
            # RFB 3.3 with security type None has no SecurityResult message.
        else:
            security_count = self._recv_required(1, "списка аутентификации")[0]
            if security_count == 0:
                raise _VNCError(f"Сервер отказал: {self._read_failure_reason()}")
            security_types = self._recv_required(
                security_count, "списка аутентификации"
            )
            if 1 not in security_types:
                if 2 in security_types:
                    raise _VNCError(
                        "Сервер требует пароль VNC; запустите x11vnc с -nopw"
                    )
                listed = ", ".join(str(item) for item in security_types)
                raise _VNCError(
                    f"Неподдерживаемый тип аутентификации VNC: {listed}"
                )

            self._sendall(b"\x01")  # SecurityType: None
            result = struct.unpack(
                "!I", self._recv_required(4, "результата аутентификации")
            )[0]
            if result != 0:
                reason = self._read_failure_reason() if negotiated_minor >= 8 else ""
                suffix = f": {reason}" if reason else ""
                raise _VNCError(f"Ошибка аутентификации VNC{suffix}")

        self._sendall(b"\x01")  # ClientInit: shared=1
        header = self._recv_required(24, "заголовка рабочего стола")
        self.fb_w, self.fb_h = struct.unpack("!HH", header[:4])
        self._validate_framebuffer_size(self.fb_w, self.fb_h)

        name_len = struct.unpack("!I", header[20:24])[0]
        if name_len > self.MAX_SERVER_TEXT:
            raise _VNCError("Сервер прислал слишком длинное имя рабочего стола")
        if name_len:
            self._recv_required(name_len, "имени рабочего стола")

    @staticmethod
    def _unsupported_security_message(security_type: int) -> str:
        if security_type == 2:
            return "Сервер требует пароль VNC; запустите x11vnc с -nopw"
        return f"Неподдерживаемый тип аутентификации VNC: {security_type}"

    def _read_failure_reason(self) -> str:
        length = struct.unpack("!I", self._recv_required(4, "причины отказа"))[0]
        if length > self.MAX_SERVER_TEXT:
            return "слишком длинное сообщение сервера"
        return self._recv_required(length, "причины отказа").decode(
            errors="replace"
        ) if length else "без пояснения"

    # ── main loop / commands ──────────────────────────────────────────────

    def _main_loop(self) -> None:
        while not self._stop_event.is_set():
            self._drain_queue()
            self._raise_if_stopped()
            self._maybe_apply_pending_control()

            if (
                not self._update_outstanding
                and time.monotonic() - self._last_request_at >= self.KEEP_ALIVE
            ):
                self._request_update(incremental=True)

            try:
                # Only waiting for a *new message type* is allowed to time
                # out.  Once a type byte is received, nested reads wait for
                # the rest of that message, so a split TCP packet cannot
                # desynchronise the RFB stream.
                self._recv_message()
            except TimeoutError:
                continue

    def _drain_queue(self) -> None:
        """Send queued input, coalescing only mouse-move commands.

        Press/release/wheel events retain their order.  Coalescing movement
        prevents a long drag on a slow connection from building an unbounded
        latency queue.
        """
        latest_motion: tuple | None = None

        def flush_motion() -> None:
            nonlocal latest_motion
            if latest_motion is not None:
                self._send_pointer(
                    int(latest_motion[1]),
                    int(latest_motion[2]),
                    int(latest_motion[3]),
                )
                latest_motion = None

        while True:
            try:
                cmd = self._q.get_nowait()
            except queue.Empty:
                break
            if not cmd:
                continue

            command_type = cmd[0]
            if command_type == _Cmd.DISCONNECT:
                self.stop()
                return

            if command_type == _Cmd.POINTER_EVENT:
                # Fifth item is private metadata: True means a pure move.
                is_motion = len(cmd) > 4 and bool(cmd[4])
                if is_motion:
                    latest_motion = cmd
                    continue
                flush_motion()
                self._send_pointer(int(cmd[1]), int(cmd[2]), int(cmd[3]))
                continue

            flush_motion()
            if command_type == _Cmd.KEY_EVENT:
                self._send_key(bool(cmd[1]), int(cmd[2]))
            elif command_type == _Cmd.FULL_UPDATE:
                self._pending_full_update = True
            elif command_type == _Cmd.SET_DEPTH:
                self._request_depth(int(cmd[1]))

        flush_motion()

    def _request_depth(self, idx: int) -> None:
        _depth_preset(idx)  # validate command data before mutating state
        if idx == self._depth_idx:
            # A second click may cancel a not-yet-applied depth request.
            self._pending_depth_idx = None
            return
        self._pending_depth_idx = idx

    def _maybe_apply_pending_control(self) -> None:
        """Apply deferred SetPixelFormat/full-update at a message boundary."""
        if self._update_outstanding:
            return

        if self._pending_depth_idx is not None:
            self._depth_idx = self._pending_depth_idx
            self._pending_depth_idx = None
            self._pending_full_update = False
            self._send_pixel_format()
            self._request_update(incremental=False)
            return

        if self._pending_full_update:
            self._pending_full_update = False
            self._request_update(incremental=False)

    # ── client-to-server RFB messages ─────────────────────────────────────

    def _send_pixel_format(self) -> None:
        preset = _depth_preset(self._depth_idx)
        pixel_format = struct.pack(
            "!BBBBHHHBBB3x",
            preset.bpp,
            preset.depth,
            0,  # little-endian pixels on the wire
            preset.true_colour,
            preset.r_max,
            preset.g_max,
            preset.b_max,
            preset.r_shift,
            preset.g_shift,
            preset.b_shift,
        )
        self._sendall(b"\x00\x00\x00\x00" + pixel_format)

    def _send_encodings(self) -> None:
        message = struct.pack("!BxH", 2, 3)
        message += struct.pack("!i", 1)  # CopyRect
        message += struct.pack("!i", 0)  # Raw
        message += struct.pack("!i", -223)  # DesktopSize
        self._sendall(message)

    def _request_update(self, incremental: bool) -> None:
        if self._update_outstanding:
            if not incremental:
                self._pending_full_update = True
            return
        if self.fb_w <= 0 or self.fb_h <= 0:
            raise _VNCError("Сервер сообщил недопустимый размер рабочего стола")
        self._sendall(
            struct.pack(
                "!BBHHHH",
                3,
                1 if incremental else 0,
                0,
                0,
                self.fb_w,
                self.fb_h,
            )
        )
        self._update_outstanding = True
        self._last_request_at = time.monotonic()

    def _send_key(self, down: bool, keysym: int) -> None:
        self._sendall(struct.pack("!BBxxI", 4, 1 if down else 0, keysym & 0xFFFFFFFF))

    def _send_pointer(self, x: int, y: int, mask: int) -> None:
        if self.fb_w <= 0 or self.fb_h <= 0:
            return
        x = max(0, min(x, self.fb_w - 1))
        y = max(0, min(y, self.fb_h - 1))
        self._sendall(struct.pack("!BBHH", 5, mask & 0xFF, x, y))

    # ── server-to-client RFB messages ─────────────────────────────────────

    def _recv_message(self) -> None:
        message_type = self._recv(1, allow_idle_timeout=True)
        if message_type is None:
            raise OSError("VNC-сервер закрыл соединение")

        message_id = message_type[0]
        if message_id == 0:
            self._handle_update()
        elif message_id == 1:
            self._handle_colormap()
        elif message_id == 2:
            self._cb("on_bell")
        elif message_id == 3:
            self._handle_server_cut_text()
        else:
            raise _VNCError(f"Неподдерживаемое сообщение RFB: {message_id}")

    def _handle_server_cut_text(self) -> None:
        header = self._recv_or_closed(7)
        length = struct.unpack("!xxxI", header)[0]
        # Clipboard contents are not exposed by this widget, but every byte
        # must be consumed.  The old min(n, 65536) read left long texts in the
        # stream and made the next byte look like a message type.
        if length > self.MAX_SERVER_TEXT:
            raise _VNCError("Сервер прислал слишком длинный текст буфера обмена")
        self._discard(length)

    def _handle_colormap(self) -> None:
        """Handle SetColourMapEntries for 8-bit indexed mode."""
        header = self._recv_or_closed(5)
        first, count = struct.unpack("!xHH", header)
        for offset in range(count):
            entry = self._recv_or_closed(6)
            red, green, blue = struct.unpack("!HHH", entry)
            palette_idx = first + offset
            if palette_idx < len(self._palette):
                self._palette[palette_idx] = (red >> 8, green >> 8, blue >> 8)
        # Rebuild lazily: colour-map messages can arrive in 16/32-bit mode,
        # where allocating numpy data would be wasteful.
        self._palette_np = None

    def _handle_update(self) -> None:
        header = self._recv_or_closed(3)
        rectangle_count = struct.unpack("!xH", header)[0]
        bpp = _depth_preset(self._depth_idx).bpp

        for _ in range(rectangle_count):
            rect_header = self._recv_or_closed(12)
            x, y, width, height, encoding = struct.unpack("!HHHHi", rect_header)

            if encoding == 0:  # Raw
                if width == 0 or height == 0:
                    continue
                pixels = width * height
                if pixels > self.MAX_FRAMEBUFFER_PIXELS:
                    raise _VNCError("Сервер прислал слишком большой VNC-кадр")
                raw = self._recv_or_closed(pixels * (bpp // 8))
                rgba = self._to_rgba32(raw, width, height, bpp)
                self._cb("on_frame_update", x, y, width, height, rgba)
            elif encoding == 1:  # CopyRect
                source = self._recv_or_closed(4)
                source_x, source_y = struct.unpack("!HH", source)
                self._cb(
                    "on_copy_rect", x, y, width, height, source_x, source_y
                )
            elif encoding == -223:  # DesktopSize
                self._validate_framebuffer_size(width, height)
                self.fb_w, self.fb_h = width, height
                self._cb("on_desktop_resize", width, height)
            else:
                # We only advertised Raw, CopyRect and DesktopSize.  Continuing
                # without consuming an unknown encoding would corrupt framing.
                raise _VNCError(f"Сервер прислал незапрошенное RFB-кодирование: {encoding}")

        self._update_outstanding = False
        self._maybe_apply_pending_control()

    def _validate_framebuffer_size(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0 or width * height > self.MAX_FRAMEBUFFER_PIXELS:
            raise _VNCError(f"Недопустимый размер рабочего стола VNC: {width}×{height}")

    # ── pixel conversion ──────────────────────────────────────────────────

    def _to_rgba32(self, raw: bytes, width: int, height: int, bpp: int) -> bytes:
        """Convert a Raw RFB rectangle to host-order BGRX/RGB32 bytes.

        All reduced-colour paths are vectorised with numpy.  The 32-bit preset
        deliberately has B/G/R shifts 0/8/16 and little-endian wire order, so
        it is already exactly QImage.Format_RGB32 byte layout and needs no copy.
        """
        import numpy as np

        pixel_count = width * height
        if bpp == 32:
            return raw

        if bpp == 16:
            values = np.frombuffer(raw, dtype="<u2", count=pixel_count).astype(
                np.uint32, copy=False
            )
            red5 = (values >> 11) & 0x1F
            green6 = (values >> 5) & 0x3F
            blue5 = values & 0x1F
            # Bit replication gives the full 0..255 range rather than dark
            # colours with the low bits permanently zeroed.
            red = (red5 << 3) | (red5 >> 2)
            green = (green6 << 2) | (green6 >> 4)
            blue = (blue5 << 3) | (blue5 >> 2)
            packed = blue | (green << 8) | (red << 16) | np.uint32(0xFF000000)
            return packed.astype("<u4", copy=False).tobytes()

        if bpp == 8:
            if self._palette_np is None:
                self._palette_np = np.asarray(self._palette, dtype=np.uint8)
            indexes = np.frombuffer(raw, dtype=np.uint8, count=pixel_count)
            rgb = self._palette_np[indexes]  # (pixels, 3), RGB order
            result = np.empty((pixel_count, 4), dtype=np.uint8)
            result[:, 0] = rgb[:, 2]  # B
            result[:, 1] = rgb[:, 1]  # G
            result[:, 2] = rgb[:, 0]  # R
            result[:, 3] = 0xFF
            return result.tobytes()

        raise _VNCError(f"Неподдерживаемая глубина пикселя VNC: {bpp}")

    # ── socket helpers ────────────────────────────────────────────────────

    def _socket_or_raise(self) -> socket.socket:
        with self._socket_lock:
            sock = self._sock
        if sock is None:
            if self._stop_event.is_set():
                raise _WorkerStoppedError
            raise OSError("Сокет VNC закрыт")
        return sock

    def _sendall(self, data: bytes) -> None:
        self._raise_if_stopped()
        try:
            self._socket_or_raise().sendall(data)
        except OSError as exc:
            if self._stop_event.is_set():
                raise _WorkerStoppedError from exc
            raise _VNCError(f"Ошибка отправки данных VNC: {exc}") from exc

    def _recv(
        self,
        count: int,
        *,
        allow_idle_timeout: bool = False,
    ) -> bytes | None:
        """Read exactly ``count`` bytes without losing RFB message framing.

        ``allow_idle_timeout`` is used only for a fresh server-message byte.
        A timeout inside a known message is retried, otherwise a packet split
        between TCP reads would make the next header byte look like a new RFB
        message.  ``stop()`` closes the socket, so these retries remain
        interruptible.
        """
        if count < 0:
            raise ValueError("Нельзя получить отрицательное число байтов")
        if count == 0:
            return b""

        initial_buffered = len(self._buf)
        last_progress = time.monotonic()
        while len(self._buf) < count:
            self._raise_if_stopped()
            try:
                # Deliberately read a substantial chunk even for a small
                # header.  Subsequent headers/raw data are served from _buf.
                chunk = self._socket_or_raise().recv(65_536)
            except TimeoutError:
                if allow_idle_timeout and len(self._buf) == initial_buffered:
                    raise
                if time.monotonic() - last_progress >= self.PARTIAL_READ_TIMEOUT:
                    raise _VNCError("Таймаут при получении неполного сообщения VNC") from None
                continue
            except OSError as exc:
                if self._stop_event.is_set():
                    raise _WorkerStoppedError from exc
                raise _VNCError(f"Ошибка чтения данных VNC: {exc}") from exc

            if not chunk:
                return None
            self._buf.extend(chunk)
            last_progress = time.monotonic()

        data = bytes(self._buf[:count])
        del self._buf[:count]
        return data

    def _recv_required(self, count: int, what: str) -> bytes:
        try:
            data = self._recv(count)
        except TimeoutError as exc:
            raise _VNCError(f"Таймаут при получении {what}") from exc
        if data is None:
            if self._stop_event.is_set():
                raise _WorkerStoppedError
            raise _VNCError(f"Сервер закрыл соединение при получении {what}")
        return data

    def _recv_or_closed(self, count: int) -> bytes:
        data = self._recv(count)
        if data is None:
            if self._stop_event.is_set():
                raise _WorkerStoppedError
            raise OSError("VNC-сервер закрыл соединение")
        return data

    def _discard(self, count: int) -> None:
        while count:
            chunk_size = min(count, 65_536)
            self._recv_or_closed(chunk_size)
            count -= chunk_size

    def _raise_if_stopped(self) -> None:
        if self._stop_event.is_set():
            raise _WorkerStoppedError

    def _close_socket(self) -> None:
        with self._socket_lock:
            sock, self._sock = self._sock, None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                sock.close()

    def _cleanup(self) -> None:
        self._close_socket()
        self._buf.clear()

    def _cb(self, name: str, *args: object) -> None:
        callback = self._cbs.get(name)
        if callback is not None:
            with contextlib.suppress(Exception):
                callback(*args)


# ══════════════════════════════════════════════════════════════════════════════
# EMBEDDED VNC WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class _WorkerEventBridge(QObject):
    """Qt-owned wake-up signal for a Python worker-thread event deque."""

    events_ready = Signal()


class EmbeddedVNCWidget(QWidget):
    """Framebuffer widget; all QImage/QPainter work happens in the GUI thread."""

    state_changed = Signal(str, str)
    _MAX_EVENTS_PER_TICK = 256

    def __init__(
        self,
        ip: str,
        port: int = 5900,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ip = ip
        self._port = port
        self._depth_idx = _DEFAULT_DEPTH_IDX
        self._worker: _VNCWorker | None = None
        self._retiring_workers: set[_VNCWorker] = set()
        self._q: queue.Queue[tuple] = queue.Queue()
        self._generation = 0
        self._pending_connect = False
        self._closing = False

        # Worker callbacks append only Python data while holding this short
        # mutex.  They never create QImage, mutate widget state, or start a
        # QTimer from a foreign thread.
        self._worker_events: deque[tuple[int, str, tuple[object, ...]]] = deque()
        self._event_lock = threading.Lock()
        self._event_scheduled = False
        self._event_bridge = _WorkerEventBridge(self)
        self._event_bridge.events_ready.connect(
            self._drain_worker_events,
            Qt.ConnectionType.QueuedConnection,
        )

        self._state = _ConnState.DISCONNECTED
        self._fb: QImage | None = None
        self._fb_w = 0
        self._fb_h = 0
        self._pending_updates: list[tuple] = []
        self._btn_mask = 0
        self._last_fb_pos = QPoint(0, 0)
        self._pressed_keysyms: dict[int, int] = {}

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(160, 120)
        self.setStyleSheet("background:#1a1a2e;")

        self._paint_timer = QTimer(self)
        self._paint_timer.setSingleShot(True)
        self._paint_timer.setInterval(16)  # batch to at most ~60 framebuffer paints/s
        self._paint_timer.timeout.connect(self._apply_updates)

        self._retire_timer = QTimer(self)
        self._retire_timer.setSingleShot(True)
        self._retire_timer.setInterval(50)
        self._retire_timer.timeout.connect(self._reap_workers)

    # ── lifecycle ─────────────────────────────────────────────────────────

    def set_depth(self, idx: int) -> None:
        """Select a preset and apply it live when a worker is connected."""
        _depth_preset(idx)
        if idx == self._depth_idx:
            return
        self._depth_idx = idx
        worker = self._worker
        if worker is not None and worker.is_alive():
            self._q.put((_Cmd.SET_DEPTH, idx))

    def connect_vnc(self) -> None:
        """Start one worker, retiring an older worker without GUI-thread join()."""
        if self._closing:
            return

        self._generation += 1
        self._pending_connect = True
        self._clear_framebuffer()
        self._state = _ConnState.CONNECTING
        self.state_changed.emit("connecting", f"⏳ Подключение к {self._ip}…")
        self.update()

        if self._worker is not None:
            self._retire_active_worker()
        self._start_pending_connection()

    def disconnect_vnc(self) -> None:
        """Stop the active worker and invalidate all of its queued callbacks."""
        if self._closing:
            return

        self._generation += 1
        self._pending_connect = False
        self._release_remote_input()
        self._retire_active_worker()
        self._clear_framebuffer()
        self._state = _ConnState.DISCONNECTED
        self.state_changed.emit("idle", f"🖥  Нажмите «Подключить»\n{self._ip}")
        self.update()

    def _start_pending_connection(self) -> None:
        if not self._pending_connect or self._closing or self._worker is not None:
            return
        if any(worker.is_alive() for worker in self._retiring_workers):
            self._schedule_reap()
            return

        # Join only known-dead threads.  This never blocks the GUI while a
        # socket is alive and avoids launching two workers for one preview.
        self._reap_workers(start_pending=False)
        if any(worker.is_alive() for worker in self._retiring_workers):
            self._schedule_reap()
            return

        self._pending_connect = False
        self._q = queue.Queue()
        generation = self._generation
        worker = _VNCWorker(
            self._ip,
            self._port,
            self._q,
            self._worker_callbacks(generation),
            depth_idx=self._depth_idx,
        )
        self._worker = worker
        try:
            worker.start()
        except Exception as exc:
            self._worker = None
            self._state = _ConnState.ERROR
            self.state_changed.emit("error", f"⚠  Не удалось запустить VNC: {exc}")
            self.update()

    def _retire_active_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is None:
            return
        self._retiring_workers.add(worker)
        worker.stop()  # closes the socket and unblocks recv immediately
        self._schedule_reap()

    def _schedule_reap(self) -> None:
        if not self._closing and not self._retire_timer.isActive():
            self._retire_timer.start()

    def _reap_workers(self, *, start_pending: bool = True) -> None:
        alive = False
        for worker in tuple(self._retiring_workers):
            if worker.is_alive():
                alive = True
                continue
            # A zero-time join only releases Thread resources after is_alive
            # has become false; it cannot freeze the Qt event loop.
            with contextlib.suppress(RuntimeError):
                worker.join(timeout=0)
            self._retiring_workers.discard(worker)

        if self._closing:
            return
        if alive:
            self._schedule_reap()
        elif start_pending and self._pending_connect:
            self._start_pending_connection()

    @property
    def is_connected(self) -> bool:
        return (
            self._worker is not None
            and self._worker.is_alive()
            and self._state == _ConnState.CONNECTED
        )

    @property
    def conn_state(self) -> int:
        """Public read-only access to the internal connection state."""
        return self._state

    # ── worker → GUI bridge ───────────────────────────────────────────────

    def _worker_callbacks(self, generation: int) -> dict[str, Callable]:
        return {
            "on_connected": lambda width, height: self._enqueue_worker_event(
                generation, "connected", width, height
            ),
            "on_disconnected": lambda: self._enqueue_worker_event(
                generation, "disconnected"
            ),
            "on_error": lambda message: self._enqueue_worker_event(
                generation, "error", message
            ),
            "on_frame_update": lambda x, y, width, height, data: self._enqueue_worker_event(
                generation, "frame", x, y, width, height, data
            ),
            "on_copy_rect": lambda x, y, width, height, sx, sy: self._enqueue_worker_event(
                generation, "copy", x, y, width, height, sx, sy
            ),
            "on_desktop_resize": lambda width, height: self._enqueue_worker_event(
                generation, "resize", width, height
            ),
            "on_bell": lambda: self._enqueue_worker_event(generation, "bell"),
        }

    def _enqueue_worker_event(
        self,
        generation: int,
        kind: str,
        *payload: object,
    ) -> None:
        if self._closing:
            return
        should_emit = False
        with self._event_lock:
            if self._closing:
                return
            self._worker_events.append((generation, kind, payload))
            if not self._event_scheduled:
                self._event_scheduled = True
                should_emit = True
        if should_emit:
            # Signal emission is thread-safe and, with QueuedConnection,
            # invokes _drain_worker_events in this widget's GUI thread.
            with contextlib.suppress(RuntimeError):
                self._event_bridge.events_ready.emit()

    @Slot()
    def _drain_worker_events(self) -> None:
        if self._closing:
            return

        processed = 0
        while processed < self._MAX_EVENTS_PER_TICK:
            with self._event_lock:
                if not self._worker_events:
                    self._event_scheduled = False
                    return
                generation, kind, payload = self._worker_events.popleft()
            self._handle_worker_event(generation, kind, payload)
            processed += 1

        # Keep the notification flag set while this continuation is queued.
        # A worker that appends in the meantime need not enqueue another Qt
        # event, and no wake-up can be lost.
        QTimer.singleShot(0, self._drain_worker_events)

    def _handle_worker_event(
        self,
        generation: int,
        kind: str,
        payload: tuple[object, ...],
    ) -> None:
        # A stopped/replaced worker is permitted to finish later.  Its events
        # must never overwrite the state or image of a newer connection.
        if self._closing or generation != self._generation:
            return

        if kind == "connected":
            width, height = int(payload[0]), int(payload[1])
            self._fb_w, self._fb_h = width, height
            self._fb = QImage(width, height, QImage.Format.Format_RGB32)
            if self._fb.isNull():
                self._state = _ConnState.ERROR
                self.state_changed.emit("error", "⚠  Не удалось выделить буфер VNC")
                self._retire_active_worker()
            else:
                self._fb.fill(Qt.GlobalColor.black)
                self._state = _ConnState.CONNECTED
                self.state_changed.emit("connected", "● подключено")
            self._pending_updates.clear()
            self.update()
            return

        if kind == "error":
            self._state = _ConnState.ERROR
            self.state_changed.emit("error", f"⚠  {payload[0]}")
            self.update()
            return

        if kind == "disconnected":
            worker, self._worker = self._worker, None
            if worker is not None:
                self._retiring_workers.add(worker)
                self._schedule_reap()
            # The server has dropped the client state, so local bookkeeping
            # must not leak a pressed modifier/button into a later reconnect.
            self._btn_mask = 0
            self._pressed_keysyms.clear()
            if self._state != _ConnState.ERROR:
                self._state = _ConnState.DISCONNECTED
                self.state_changed.emit(
                    "idle", f"🖥  Нажмите «Подключить»\n{self._ip}"
                )
            self.update()
            return

        if kind == "resize":
            width, height = int(payload[0]), int(payload[1])
            self._fb_w, self._fb_h = width, height
            self._fb = QImage(width, height, QImage.Format.Format_RGB32)
            if self._fb.isNull():
                self._state = _ConnState.ERROR
                self.state_changed.emit("error", "⚠  Не удалось изменить размер буфера VNC")
                self._retire_active_worker()
            else:
                self._fb.fill(Qt.GlobalColor.black)
            self._pending_updates.clear()
            self.update()
            return

        if kind == "frame":
            if self._state != _ConnState.CONNECTED or self._fb is None:
                return
            x, y, width, height, data = payload
            width, height = int(width), int(height)
            if (
                width <= 0
                or height <= 0
                or not isinstance(data, bytes)
                or len(data) != width * height * 4
            ):
                return
            self._pending_updates.append(("raw", int(x), int(y), width, height, data))
            self._schedule_paint()
            return

        if kind == "copy":
            if self._state != _ConnState.CONNECTED or self._fb is None:
                return
            x, y, width, height, sx, sy = (int(value) for value in payload)
            if width > 0 and height > 0:
                self._pending_updates.append(("copy", x, y, width, height, sx, sy))
                self._schedule_paint()
            return

        # "bell" is deliberately consumed without a GUI side effect.

    # ── framebuffer updates / painting (GUI thread only) ──────────────────

    @Slot()
    def _schedule_paint(self) -> None:
        if not self._paint_timer.isActive():
            self._paint_timer.start()

    @Slot()
    def _apply_updates(self) -> None:
        if self._fb is None or not self._pending_updates:
            return

        # Detach the batch before QPainter starts.  Worker callbacks only add
        # to _worker_events, then this GUI-thread bridge adds to
        # _pending_updates, so no framebuffer lock is needed and the worker is
        # never blocked by painting.
        updates, self._pending_updates = self._pending_updates, []
        framebuffer = self._fb
        dirty: QRect | None = None
        painter = QPainter(framebuffer)
        try:
            for item in updates:
                if item[0] == "raw":
                    _, x, y, width, height, data = item
                    source = QImage(
                        data,
                        width,
                        height,
                        width * 4,
                        QImage.Format.Format_RGB32,
                    )
                    if not source.isNull():
                        painter.drawImage(x, y, source)
                        rect = QRect(x, y, width, height).intersected(framebuffer.rect())
                        dirty = rect if dirty is None else dirty.united(rect)
                else:  # CopyRect
                    _, x, y, width, height, source_x, source_y = item
                    source_rect = QRect(source_x, source_y, width, height).intersected(
                        framebuffer.rect()
                    )
                    if source_rect.isEmpty():
                        continue
                    # Copy first: CopyRect regions may overlap, and painting a
                    # framebuffer onto itself is not guaranteed to have memmove
                    # semantics across all Qt paint engines.
                    source = framebuffer.copy(source_rect)
                    destination_x = x + source_rect.x() - source_x
                    destination_y = y + source_rect.y() - source_y
                    painter.drawImage(destination_x, destination_y, source)
                    rect = QRect(
                        destination_x,
                        destination_y,
                        source.width(),
                        source.height(),
                    ).intersected(framebuffer.rect())
                    dirty = rect if dirty is None else dirty.united(rect)
        finally:
            painter.end()

        if dirty is not None and not dirty.isEmpty():
            self.update(self._fb_rect_to_widget(dirty))

    def _clear_framebuffer(self) -> None:
        self._fb = None
        self._fb_w = 0
        self._fb_h = 0
        self._pending_updates.clear()

    def _target_rect(self) -> QRect:
        if self._fb is None or self._fb.isNull() or self.width() <= 0 or self.height() <= 0:
            return QRect()
        framebuffer_width, framebuffer_height = self._fb.width(), self._fb.height()
        if framebuffer_width <= 0 or framebuffer_height <= 0:
            return QRect()
        scale = min(self.width() / framebuffer_width, self.height() / framebuffer_height)
        display_width = max(1, round(framebuffer_width * scale))
        display_height = max(1, round(framebuffer_height * scale))
        return QRect(
            (self.width() - display_width) // 2,
            (self.height() - display_height) // 2,
            display_width,
            display_height,
        )

    def _fb_rect_to_widget(self, source: QRect) -> QRect:
        """Map one framebuffer dirty rect to a slightly expanded widget rect."""
        target = self._target_rect()
        if target.isEmpty() or self._fb is None:
            return self.rect()
        clipped = source.intersected(self._fb.rect())
        if clipped.isEmpty():
            return QRect()

        framebuffer_width, framebuffer_height = self._fb.width(), self._fb.height()
        left = target.x() + clipped.x() * target.width() // framebuffer_width
        top = target.y() + clipped.y() * target.height() // framebuffer_height
        right = target.x() + (
            (clipped.x() + clipped.width()) * target.width() + framebuffer_width - 1
        ) // framebuffer_width
        bottom = target.y() + (
            (clipped.y() + clipped.height()) * target.height() + framebuffer_height - 1
        ) // framebuffer_height

        # Smooth scaling samples neighbouring source pixels, hence one pixel
        # of padding around the mapped destination dirty area.
        return QRect(left - 1, top - 1, right - left + 2, bottom - top + 2).intersected(
            self.rect()
        )

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            # WA_OpaquePaintEvent means we must fill every exposed portion.
            painter.fillRect(event.rect(), QColor("#1a1a2e"))
            framebuffer = self._fb
            if framebuffer is not None and not framebuffer.isNull():
                target = self._target_rect()
                if not target.isEmpty():
                    painter.setClipRegion(event.region())
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                    # This avoids allocating framebuffer.scaled(...) on every
                    # paint; Qt rasterizes directly into the clipped dirty area.
                    painter.drawImage(target, framebuffer, framebuffer.rect())
            elif self._state == _ConnState.CONNECTING:
                painter.setPen(QColor("#888"))
                painter.drawText(
                    self.rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    f"⏳  Подключение…\n{self._ip}",
                )
            elif self._state == _ConnState.ERROR:
                painter.setPen(QColor("#f44336"))
                painter.drawText(
                    self.rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    "⚠  Ошибка подключения VNC",
                )
        finally:
            painter.end()

    # ── mouse / keyboard ──────────────────────────────────────────────────

    def _to_fb(self, pos: QPoint) -> tuple[int, int]:
        if self._fb_w <= 0 or self._fb_h <= 0 or self.width() <= 0 or self.height() <= 0:
            return 0, 0
        scale = min(self.width() / self._fb_w, self.height() / self._fb_h)
        if scale <= 0:
            return 0, 0
        origin_x = (self.width() - int(self._fb_w * scale)) // 2
        origin_y = (self.height() - int(self._fb_h * scale)) // 2
        x = int((pos.x() - origin_x) / scale)
        y = int((pos.y() - origin_y) / scale)
        return (
            max(0, min(x, self._fb_w - 1)),
            max(0, min(y, self._fb_h - 1)),
        )

    def _queue_pointer(self, x: int, y: int, mask: int, *, motion: bool = False) -> None:
        self._last_fb_pos = QPoint(x, y)
        self._q.put((_Cmd.POINTER_EVENT, x, y, mask, motion))

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.is_connected:
            event.ignore()
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        button = event.button()
        if button == Qt.MouseButton.LeftButton:
            self._btn_mask |= 1
        elif button == Qt.MouseButton.MiddleButton:
            self._btn_mask |= 2
        elif button == Qt.MouseButton.RightButton:
            self._btn_mask |= 4
        x, y = self._to_fb(event.position().toPoint())
        self._queue_pointer(x, y, self._btn_mask)
        event.accept()

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self.is_connected:
            event.ignore()
            return
        button = event.button()
        if button == Qt.MouseButton.LeftButton:
            self._btn_mask &= ~1
        elif button == Qt.MouseButton.MiddleButton:
            self._btn_mask &= ~2
        elif button == Qt.MouseButton.RightButton:
            self._btn_mask &= ~4
        x, y = self._to_fb(event.position().toPoint())
        self._queue_pointer(x, y, self._btn_mask)
        event.accept()

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.is_connected:
            event.ignore()
            return
        x, y = self._to_fb(event.position().toPoint())
        self._queue_pointer(x, y, self._btn_mask, motion=True)
        event.accept()

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.is_connected:
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        x, y = self._to_fb(event.position().toPoint())
        wheel_mask = _WHEEL_UP_MASK if delta > 0 else _WHEEL_DOWN_MASK
        self._queue_pointer(x, y, self._btn_mask | wheel_mask)
        self._queue_pointer(x, y, self._btn_mask)
        event.accept()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self.is_connected or event.isAutoRepeat():
            event.ignore()
            return
        keysym = _qt_to_keysym(event.key(), event.text(), event.modifiers())
        if keysym:
            count = self._pressed_keysyms.get(keysym, 0)
            self._pressed_keysyms[keysym] = count + 1
            if count == 0:
                self._q.put((_Cmd.KEY_EVENT, True, keysym))
            event.accept()
        else:
            event.ignore()

    @override
    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not self.is_connected or event.isAutoRepeat():
            event.ignore()
            return
        keysym = _qt_to_keysym(event.key(), event.text(), event.modifiers())
        if keysym:
            count = self._pressed_keysyms.get(keysym, 0)
            if count <= 1:
                self._pressed_keysyms.pop(keysym, None)
                self._q.put((_Cmd.KEY_EVENT, False, keysym))
            else:
                self._pressed_keysyms[keysym] = count - 1
            event.accept()
        else:
            event.ignore()

    @override
    def focusOutEvent(self, event) -> None:
        # Do not leave a remote mouse button/modifier pressed if the operator
        # clicks another tab or a dialog steals focus.
        self._release_remote_input()
        super().focusOutEvent(event)

    def _release_remote_input(self) -> None:
        if self.is_connected:
            if self._btn_mask:
                self._queue_pointer(
                    self._last_fb_pos.x(), self._last_fb_pos.y(), 0
                )
            for keysym in self._pressed_keysyms:
                self._q.put((_Cmd.KEY_EVENT, False, keysym))
        self._btn_mask = 0
        self._pressed_keysyms.clear()

    def cleanup(self) -> None:
        """Stop networking without allowing late worker callbacks into Qt."""
        if self._closing:
            return
        self._closing = True
        self._generation += 1
        self._pending_connect = False
        self._paint_timer.stop()
        self._retire_timer.stop()
        self._release_remote_input()
        self._retire_active_worker()
        for worker in tuple(self._retiring_workers):
            worker.stop()
        self._clear_framebuffer()
        with self._event_lock:
            self._worker_events.clear()
            self._event_scheduled = False

        # Socket close normally makes this immediate.  Keep cleanup bounded in
        # case create_connection() is still inside the OS connect timeout.
        deadline = time.monotonic() + 0.2
        for worker in tuple(self._retiring_workers):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            with contextlib.suppress(RuntimeError):
                worker.join(timeout=remaining)


# ══════════════════════════════════════════════════════════════════════════════
# VncPreviewWidget — container with depth buttons below VNC area
# ══════════════════════════════════════════════════════════════════════════════

_SS_BTN_NORMAL = (
    "QPushButton {"
    "  background: rgba(40,40,60,0.75);"
    "  color: #b0b8d0;"
    "  border: 1px solid rgba(160,170,200,0.25);"
    "  border-radius: 4px;"
    "  font-size: 11px;"
    "  font-weight: normal;"
    "  padding: 0 6px;"
    "}"
    "QPushButton:hover {"
    "  background: rgba(76,100,180,0.55);"
    "  color: #ffffff;"
    "  border-color: rgba(120,150,240,0.6);"
    "}"
)

_SS_BTN_ACTIVE = (
    "QPushButton {"
    "  background: rgba(76,163,245,0.85);"
    "  color: #ffffff;"
    "  border: 1px solid rgba(76,163,245,1.0);"
    "  border-radius: 4px;"
    "  font-size: 11px;"
    "  font-weight: bold;"
    "  padding: 0 6px;"
    "}"
)

_SS_DEPTH_BAR = (
    "background: rgba(20,20,35,0.6);"
    "border-top: 1px solid rgba(255,255,255,0.08);"
)


class VncPreviewWidget(QWidget):
    """VNC preview container with 8/16/32-bit colour-mode buttons."""

    state_changed = Signal(str, str)

    def __init__(self, ip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("vncPanel")
        self._ip = ip
        self._config = ConfigManager()
        self._session: CashSession | None = None
        self._task: asyncio.Task | None = None
        self._depth_idx = _DEFAULT_DEPTH_IDX

        self._vnc = EmbeddedVNCWidget(ip, parent=self)
        self._vnc.state_changed.connect(self._on_vnc_state)
        self._vnc.set_depth(self._depth_idx)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._vnc, stretch=1)

        depth_bar = QWidget(self)
        depth_bar.setFixedHeight(28)
        depth_bar.setStyleSheet(_SS_DEPTH_BAR)
        bar_layout = QHBoxLayout(depth_bar)
        bar_layout.setContentsMargins(6, 3, 6, 3)
        bar_layout.setSpacing(4)

        self._depth_btns: list[QPushButton] = []
        for idx, preset in enumerate(_DEPTH_PRESETS):
            button = QPushButton(preset.label, depth_bar)
            button.setFixedHeight(20)
            button.setMinimumWidth(52)
            button.setToolTip(preset.tooltip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, selected_idx=idx: self._on_depth_clicked(
                    selected_idx
                )
            )
            bar_layout.addWidget(button)
            self._depth_btns.append(button)

        bar_layout.addStretch()
        layout.addWidget(depth_bar)
        self._update_depth_buttons()

    # ── asyncio task management ────────────────────────────────────────────

    def _spawn_task(self, coro) -> None:
        """Replace an in-flight task, avoiding overlapping SSH/start flows."""
        self._cancel_task()
        task = asyncio.ensure_future(coro)
        self._task = task

        def on_done(done_task: asyncio.Task) -> None:
            if done_task is self._task:
                self._task = None
            # Retrieve exceptions so cancellation/races do not produce an
            # "exception was never retrieved" warning in the qasync loop.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                done_task.result()

        task.add_done_callback(on_done)

    def _cancel_task(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    # ── Depth selection ───────────────────────────────────────────────────

    def _on_depth_clicked(self, idx: int) -> None:
        _depth_preset(idx)
        if idx == self._depth_idx:
            return

        self._depth_idx = idx
        self._vnc.set_depth(idx)
        self._update_depth_buttons()
        preset = _depth_preset(idx)
        logger.info("[VNC] depth changed to %s for %s", preset.label, self._ip)
        self._audit("vnc_depth_change")

    def _update_depth_buttons(self) -> None:
        for idx, button in enumerate(self._depth_btns):
            button.setStyleSheet(
                _SS_BTN_ACTIVE if idx == self._depth_idx else _SS_BTN_NORMAL
            )

    # ── Public API ────────────────────────────────────────────────────────

    def set_session(self, session: CashSession | None) -> None:
        self._session = session

    @property
    def state(self) -> str:
        if self._vnc.is_connected:
            return "connected"
        if self._vnc.conn_state == _ConnState.CONNECTING:
            return "connecting"
        if self._vnc.conn_state == _ConnState.ERROR:
            return "error"
        return "idle"

    def connect_vnc(self) -> None:
        self._spawn_task(self._connect_flow())

    def disconnect_vnc(self) -> None:
        # A pending _connect_flow sleep must not reconnect after an explicit
        # disconnect button click.
        self._cancel_task()
        self._sync_embedded_ip()
        self._vnc.disconnect_vnc()
        self._audit("vnc_disconnect")

    def open_fullscreen(self) -> None:
        exe_str = str(self._config.settings.programs.get_vnc_client() or "").strip()
        # Path("") is Path(".") and therefore exists.  Check before creating
        # Path and require a file, not merely an existing directory.
        if not exe_str:
            self.state_changed.emit("error", "⚠  Путь к VNC клиенту не настроен")
            return

        exe = Path(exe_str).expanduser()
        if not exe.is_file():
            self.state_changed.emit("error", f"⚠  VNC клиент не найден:\n{exe_str}")
            return
        self._spawn_task(self._open_fullscreen_async(exe))

    async def _ensure_x11vnc(self) -> bool:
        if not self._session or not self._session.is_connected:
            return False
        try:
            await self._session.ssh.execute(_X11VNC_CMD, timeout=10)
            return True
        except Exception as exc:
            logger.error("[VNC] x11vnc failed: %s", exc)
            return False

    async def _open_fullscreen_async(self, exe: Path) -> None:
        if not self._vnc.is_connected:
            started = await self._ensure_x11vnc()
            await asyncio.sleep(_VNC_START_DELAY if started else 1.0)

        port = self._config.settings.connection.vnc_port
        vnc_config = self._config.settings.vnc_preview
        args = [
            str(exe),
            f"{self._ip}:{port}",
            f"-Quality={vnc_config.quality}",
            f"-ColorLevel={vnc_config.color_level}",
        ]
        try:
            subprocess.Popen(args)
            self._audit("vnc_fullscreen")
        except Exception as exc:
            logger.error("[VNC] fullscreen error: %s", exc)
            self.state_changed.emit("error", f"⚠  Не удалось открыть VNC клиент: {exc}")

    async def _connect_flow(self) -> None:
        if self._session and self._session.is_connected:
            self.state_changed.emit(
                "connecting", f"⏳  Запуск x11vnc на {self._ip}…"
            )
            try:
                await self._session.ssh.execute(_X11VNC_CMD, timeout=10)
            except Exception as exc:
                logger.error("[VNC] x11vnc failed: %s", exc)
                self.state_changed.emit("error", "⚠  Ошибка запуска x11vnc через SSH")
                return

        await asyncio.sleep(_VNC_START_DELAY)
        # ``_ip`` is intentionally writable from the tab owner.  Synchronize
        # it immediately before opening a new socket so an IP switch does not
        # connect the embedded widget to a stale address.
        self._sync_embedded_ip()
        self._vnc.connect_vnc()

    def _sync_embedded_ip(self) -> None:
        self._vnc._ip = self._ip

    def _on_vnc_state(self, state: str, message: str) -> None:
        if state == "connected":
            logger.info("✅ Открыт VNC-просмотр для кассы %s", self._ip)
            self._audit("vnc_connect")
        elif state == "error":
            logger.error("[VNC] error on %s: %s", self._ip, message)
        self.state_changed.emit(state, message)

    def _audit(self, action_name: str) -> None:
        # A logging backend outage must not break a terminal-control action.
        try:
            audit_log(
                action_type="tool",
                action_name=action_name,
                target=self._ip,
                result="success",
            )
        except Exception as exc:
            logger.warning("[VNC] audit log failed for %s: %s", action_name, exc)

    def cleanup(self) -> None:
        self._cancel_task()
        self._vnc.cleanup()
