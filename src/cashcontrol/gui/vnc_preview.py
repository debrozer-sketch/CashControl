"""
VNC Preview — pure-Python RFB client with colour-depth buttons.

Quality buttons (horizontal, below VNC area, inside VncPreviewWidget):
  [ 8 бит ]  [ 16 бит ]  [ 32 бит ]   ← always visible when session exists

Colour modes
  8 бит  — 8 bpp paletted (server sends palette, we map → RGB32)
  16 бит — 16 bpp RGB565 (2 bytes/pixel → RGB32)
  32 бит — 32 bpp BGRX   (4 bytes/pixel, default)
"""

# ruff: noqa: E402 — imports after constants; numpy lazy-imported in methods
from __future__ import annotations

# ── Colour-depth presets ───────────────────────────────────────────────────
# (label, tooltip, bpp, depth, true_colour, r_max, g_max, b_max, r_shift, g_shift, b_shift)
_DEPTH_PRESETS = [
    ("8 бит",
     "8 бит — минимальный трафик\nИндексированный цвет (256 цветов)",
     8, 8, 0, 0, 0, 0, 0, 0, 0),
    ("16 бит",
     "16 бит — сниженный трафик\nRGB565 (65536 цветов)",
     16, 16, 1, 31, 63, 31, 11, 5, 0),
    ("32 бит",
     "32 бит — полное качество\nRGB True Color (по умолчанию)",
     32, 24, 1, 255, 255, 255, 16, 8, 0),
]
_DEFAULT_DEPTH_IDX = 2  # 32 бит

# ── Pointer wheel button masks (RFB buttons 4/5) ────────────────────────────
_WHEEL_UP_MASK   = 8
_WHEEL_DOWN_MASK = 16

import asyncio
import contextlib
import queue
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, override

from PySide6.QtCore import QMetaObject, QPoint, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor, QImage, QKeyEvent, QMouseEvent,
    QPainter, QPaintEvent, QWheelEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from cashcontrol.infrastructure.audit_logger import audit_log, get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager

if TYPE_CHECKING:
    from collections.abc import Callable
    from cashcontrol.core.session import CashSession

logger = get_logger()

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
    CONNECTING   = 1
    CONNECTED    = 2
    ERROR        = 3


class _Cmd:
    DISCONNECT    = 0
    KEY_EVENT     = 1
    POINTER_EVENT = 2
    FULL_UPDATE   = 3


_QT_KEYSYM: dict[int, int] = {
    Qt.Key.Key_Escape:    0xFF1B, Qt.Key.Key_Tab:       0xFF09,
    Qt.Key.Key_Backspace: 0xFF08, Qt.Key.Key_Return:    0xFF0D,
    Qt.Key.Key_Enter:     0xFF8D, Qt.Key.Key_Delete:    0xFFFF,
    Qt.Key.Key_Home:      0xFF50, Qt.Key.Key_End:       0xFF57,
    Qt.Key.Key_Left:      0xFF51, Qt.Key.Key_Up:        0xFF52,
    Qt.Key.Key_Right:     0xFF53, Qt.Key.Key_Down:      0xFF54,
    Qt.Key.Key_PageUp:    0xFF55, Qt.Key.Key_PageDown:  0xFF56,
    Qt.Key.Key_Shift:     0xFFE1, Qt.Key.Key_Control:   0xFFE3,
    Qt.Key.Key_Alt:       0xFFE9,
    Qt.Key.Key_F1: 0xFFBE, Qt.Key.Key_F2: 0xFFBF, Qt.Key.Key_F3: 0xFFC0,
    Qt.Key.Key_F4: 0xFFC1, Qt.Key.Key_F5: 0xFFC2, Qt.Key.Key_F6: 0xFFC3,
    Qt.Key.Key_F7: 0xFFC4, Qt.Key.Key_F8: 0xFFC5, Qt.Key.Key_F9: 0xFFC6,
    Qt.Key.Key_F10:0xFFC7, Qt.Key.Key_F11:0xFFC8, Qt.Key.Key_F12:0xFFC9,
}


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
# VNC WORKER — all socket I/O in background thread
# ══════════════════════════════════════════════════════════════════════════════

class _VNCWorker(threading.Thread):
    KEEP_ALIVE   = 0.2
    SOCK_TIMEOUT = 0.1

    def __init__(
        self,
        host: str,
        port: int,
        cmd_queue: queue.Queue,
        cbs: dict[str, Callable],
        depth_idx: int = _DEFAULT_DEPTH_IDX,
    ) -> None:
        super().__init__(daemon=True, name="VNCWorker")
        self.host      = host
        self.port      = port
        self._q        = cmd_queue
        self._cbs      = cbs
        self._depth_idx = depth_idx
        self._sock: socket.socket | None = None
        self._running  = False
        self._buf      = bytearray()
        self.fb_w      = 0
        self.fb_h      = 0
        # Palette for 8-bit mode (RGB tuples)
        self._palette: list[tuple[int, int, int]] = [(0, 0, 0)] * 256
        # numpy palette cache (256, 3) uint8 — rebuilt on colormap change
        self._palette_np = None

    def stop(self) -> None:
        self._running = False

    # ── lifecycle ─────────────────────────────────────────────────────────

    def run(self) -> None:
        self._running = True
        try:
            if not self._connect():
                return
            if not self._handshake():
                return
            self._cb("on_connected")
            self._send_pixel_format()
            self._send_encodings()
            self._request_update(incremental=False)
            if self._sock:
                self._sock.settimeout(self.SOCK_TIMEOUT)
            self._main_loop()
        except Exception as e:
            import logging as _log
            _log.getLogger("cashcontrol").error(
                f"[VNC worker] exception on {self.host}: {e}", exc_info=True
            )
            self._cb("on_error", str(e))
        finally:
            self._cleanup()
            self._cb("on_disconnected")

    def _connect(self) -> bool:
        try:
            s = socket.create_connection((self.host, self.port), timeout=10)
            s.settimeout(10.0)
            self._sock = s
            return True
        except Exception as e:
            self._cb("on_error", f"Нет соединения: {e}")
            return False

    def _handshake(self) -> bool:
        ver = self._recv(12)
        if not ver:
            return False
        self._sock.sendall(b"RFB 003.008\n")
        n = self._recv(1)
        if not n:
            return False
        n = n[0]
        if n == 0:
            rlen_raw = self._recv(4)
            if not rlen_raw:
                return False
            rlen = struct.unpack("!I", rlen_raw)[0]
            reason = self._recv(rlen) or b""
            self._cb("on_error", f"Сервер отказал: {reason.decode(errors='replace')}")
            return False
        types = self._recv(n)
        if not types:
            return False
        types = list(types)
        # NOTE: VNC password auth (type 2) is NOT implemented here — only
        # type 1 (None) is fully supported. Server must run with -nopw.
        chosen = 1 if 1 in types else (2 if 2 in types else types[0])
        self._sock.sendall(struct.pack("!B", chosen))
        if chosen == 2:
            challenge = self._recv(16)
            if not challenge:
                return False
            self._sock.sendall(b"\x00" * 16)  # placeholder — no real DES auth
        result = self._recv(4)
        if not result:
            return False
        if struct.unpack("!I", result)[0] != 0:
            self._cb("on_error", "Ошибка аутентификации VNC")
            return False
        self._sock.sendall(b"\x01")   # ClientInit shared=1
        header = self._recv(24)
        if not header:
            return False
        self.fb_w, self.fb_h = struct.unpack("!HH", header[:4])
        name_len = struct.unpack("!I", header[20:24])[0]
        if name_len:
            self._recv(name_len)
        return True

    # ── main loop ─────────────────────────────────────────────────────────

    def _main_loop(self) -> None:
        last_ka = time.monotonic()
        while self._running:
            self._drain_queue()
            now = time.monotonic()
            if now - last_ka >= self.KEEP_ALIVE:
                self._request_update(incremental=True)
                last_ka = now
            try:
                self._recv_message()
            except TimeoutError:
                continue
            except OSError:
                break

    def _drain_queue(self) -> None:
        while True:
            try:
                cmd = self._q.get_nowait()
            except queue.Empty:
                break
            t = cmd[0]
            if   t == _Cmd.DISCONNECT:    self._running = False
            elif t == _Cmd.KEY_EVENT:     self._send_key(cmd[1], cmd[2])
            elif t == _Cmd.POINTER_EVENT: self._send_pointer(cmd[1], cmd[2], cmd[3])
            elif t == _Cmd.FULL_UPDATE:   self._request_update(incremental=False)

    # ── pixel format — varies by depth preset ────────────────────────────

    def _send_pixel_format(self) -> None:
        _, _, bpp, depth, tc, rm, gm, bm, rs, gs, bs = _DEPTH_PRESETS[self._depth_idx]
        pf = struct.pack(
            "!BBBBHHHBBB3x",
            bpp, depth, 0, tc,
            rm, gm, bm,
            rs, gs, bs,
        )
        self._sock.sendall(b"\x00\x00\x00\x00" + pf)

    def _send_encodings(self) -> None:
        msg = struct.pack("!BxH", 2, 3)
        msg += struct.pack("!i", 1)    # CopyRect
        msg += struct.pack("!i", 0)    # Raw
        msg += struct.pack("!i", -223) # DesktopSize
        self._sock.sendall(msg)

    def _request_update(self, incremental: bool) -> None:
        self._sock.sendall(struct.pack(
            "!BBHHHH", 3, 1 if incremental else 0,
            0, 0, self.fb_w, self.fb_h,
        ))

    def _send_key(self, down: bool, keysym: int) -> None:
        self._sock.sendall(struct.pack("!BBxxI", 4, 1 if down else 0, keysym))

    def _send_pointer(self, x: int, y: int, mask: int) -> None:
        x = max(0, min(x, self.fb_w - 1))
        y = max(0, min(y, self.fb_h - 1))
        self._sock.sendall(struct.pack("!BBHH", 5, mask, x, y))

    # ── receive ───────────────────────────────────────────────────────────

    def _recv_message(self) -> None:
        t = self._recv(1)
        if not t:
            raise OSError("Server closed connection")
        t = t[0]
        if   t == 0: self._handle_update()
        elif t == 1: self._handle_colormap()
        elif t == 2: self._cb("on_bell")
        elif t == 3:
            hdr = self._recv(7)
            if not hdr:
                raise OSError("Server closed connection")
            n = struct.unpack("!xxxI", hdr)[0]
            if n:
                self._recv(min(n, 65536))

    def _handle_colormap(self) -> None:
        """SetColourMapEntries — only relevant in 8-bit paletted mode."""
        hdr = self._recv(5)
        if not hdr:
            raise OSError("Server closed connection")
        first, nc = struct.unpack("!xHH", hdr)
        for i in range(nc):
            entry = self._recv(6)
            if not entry:
                raise OSError("Server closed connection")
            r, g, b = struct.unpack("!HHH", entry)
            self._palette[first + i] = (r >> 8, g >> 8, b >> 8)
        # Refresh numpy palette cache for fast 8-bit conversion
        import numpy as np
        self._palette_np = np.array(self._palette, dtype=np.uint8)

    def _handle_update(self) -> None:
        hdr = self._recv(3)
        if not hdr:
            raise OSError("Server closed connection")
        n = struct.unpack("!xH", hdr)[0]
        bpp = _DEPTH_PRESETS[self._depth_idx][2]
        for _ in range(n):
            rh = self._recv(12)
            if not rh:
                raise OSError("Server closed connection")
            x, y, w, h, enc = struct.unpack("!HHHHi", rh)
            if enc == 0:   # Raw
                if w > 0 and h > 0:
                    bytes_per_pixel = bpp // 8
                    raw = self._recv(w * h * bytes_per_pixel)
                    if raw:
                        rgba = self._to_rgba32(raw, w, h, bpp)
                        self._cb("on_frame_update", x, y, w, h, rgba)
            elif enc == 1: # CopyRect
                sp = self._recv(4)
                if not sp:
                    raise OSError("Server closed connection")
                sx, sy = struct.unpack("!HH", sp)
                self._cb("on_copy_rect", x, y, w, h, sx, sy)
            elif enc == -223: # DesktopSize
                self.fb_w, self.fb_h = w, h
                self._cb("on_desktop_resize", w, h)

    def _to_rgba32(self, raw: bytes, w: int, h: int, bpp: int) -> bytes:
        """Convert raw pixel data to 32-bit BGRX (QImage.Format_RGB32).

        Vectorised via numpy — orders of magnitude faster than per-pixel loops,
        which is essential since reduced-depth modes exist precisely to be fast.
        """
        import numpy as np
        n = w * h
        if bpp == 32:
            # Already BGRX — pass through
            return raw

        if bpp == 16:
            # RGB565 (little-endian) → BGRX
            v = np.frombuffer(raw, dtype="<u2", count=n).astype(np.uint32)
            r = ((v >> 11) & 0x1F) << 3
            g = ((v >> 5)  & 0x3F) << 2
            b = (v          & 0x1F) << 3
            # Pack into BGRX little-endian: B in byte0, G byte1, R byte2, X byte3
            packed = (b | (g << 8) | (r << 16) | (np.uint32(0xFF) << 24))
            return packed.astype("<u4").tobytes()

        if bpp == 8:
            # Paletted → BGRX
            idx = np.frombuffer(raw, dtype=np.uint8, count=n)
            rgb = self._palette_np[idx]            # (n, 3) in RGB order
            out = np.empty((n, 4), dtype=np.uint8)
            out[:, 0] = rgb[:, 2]                  # B
            out[:, 1] = rgb[:, 1]                  # G
            out[:, 2] = rgb[:, 0]                  # R
            out[:, 3] = 0xFF                       # X
            return out.tobytes()

        return raw  # fallback

    # ── socket helpers ────────────────────────────────────────────────────

    def _recv(self, n: int) -> bytes | None:
        """Accumulate exactly `n` bytes.

        Honours SOCK_TIMEOUT cooperatively: while waiting for more data we keep
        checking `self._running`, so a long/partial transfer over a slow link
        cannot wedge the worker (and thus the input queue) indefinitely.
        """
        while len(self._buf) < n:
            if not self._running:
                return None
            try:
                chunk = self._sock.recv(min(n - len(self._buf), 65536))
                if not chunk:
                    return None
                self._buf.extend(chunk)
            except TimeoutError:
                # If we have NO partial data at all → we are between messages,
                # waiting for the next message type byte.  Propagate so that
                # _main_loop can service the keep-alive timer and command
                # queue instead of being stuck forever.
                if not self._buf:
                    raise
                # Otherwise we are in the middle of receiving a message;
                # keep waiting for the remaining bytes.
                continue
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    def _cleanup(self) -> None:
        if self._sock:
            with contextlib.suppress(Exception):
                self._sock.close()
            self._sock = None

    def _cb(self, name: str, *args) -> None:
        fn = self._cbs.get(name)
        if fn:
            with contextlib.suppress(Exception):
                fn(*args)


# ══════════════════════════════════════════════════════════════════════════════
# EMBEDDED VNC WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class EmbeddedVNCWidget(QWidget):
    state_changed = Signal(str, str)

    def __init__(self, ip: str, port: int = 5900, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ip        = ip
        self._port      = port
        self._depth_idx = _DEFAULT_DEPTH_IDX
        self._worker: _VNCWorker | None = None
        self._q: queue.Queue = queue.Queue()
        self._state  = _ConnState.DISCONNECTED
        self._fb: QImage | None = None
        self._fb_w   = 0
        self._fb_h   = 0
        self._fb_lock = threading.Lock()
        self._pending: list[tuple] = []
        self._btn_mask = 0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(160, 120)
        self.setStyleSheet("background:#1a1a2e;")
        self._paint_timer = QTimer(self)
        self._paint_timer.setSingleShot(True)
        self._paint_timer.setInterval(16)
        self._paint_timer.timeout.connect(self._apply_updates)

    def set_depth(self, idx: int) -> None:
        """Set colour depth preset index. Takes effect on next connect."""
        self._depth_idx = idx

    def connect_vnc(self) -> None:
        if self._worker and self._worker.is_alive():
            self.disconnect_vnc()
        self._q    = queue.Queue()
        self._state = _ConnState.CONNECTING
        self.state_changed.emit("connecting", f"⏳ Подключение к {self._ip}…")
        self.update()
        self._worker = _VNCWorker(
            self._ip, self._port, self._q,
            {
                "on_connected":      self._cb_connected,
                "on_disconnected":   self._cb_disconnected,
                "on_error":          self._cb_error,
                "on_frame_update":   self._cb_frame,
                "on_copy_rect":      self._cb_copy,
                "on_desktop_resize": self._cb_resize,
                "on_bell":           lambda: None,
            },
            depth_idx=self._depth_idx,
        )
        self._worker.start()

    def disconnect_vnc(self) -> None:
        if self._worker:
            self._q.put((_Cmd.DISCONNECT,))
            self._worker.stop()
            self._worker.join(timeout=2.0)
            self._worker = None
        self._state = _ConnState.DISCONNECTED
        self._fb    = None
        self.update()
        self.state_changed.emit("idle", f"🖥  Нажмите «Подключить»\n{self._ip}")

    @property
    def is_connected(self) -> bool:
        return (
            self._worker is not None
            and self._worker.is_alive()
            and self._state == _ConnState.CONNECTED
        )

    @property
    def conn_state(self) -> int:
        """Public read-only access to internal connection state."""
        return self._state

    # ── worker callbacks ──────────────────────────────────────────────────

    def _cb_connected(self) -> None:
        w, h = self._worker.fb_w, self._worker.fb_h
        self._fb_w, self._fb_h = w, h
        with self._fb_lock:
            self._fb = QImage(w, h, QImage.Format.Format_RGB32)
            self._fb.fill(Qt.GlobalColor.black)
        self._state = _ConnState.CONNECTED
        QMetaObject.invokeMethod(self, "_on_connected_main", Qt.ConnectionType.QueuedConnection)

    def _cb_disconnected(self) -> None:
        self._state = _ConnState.DISCONNECTED
        QMetaObject.invokeMethod(self, "_on_disconnected_main", Qt.ConnectionType.QueuedConnection)

    def _cb_error(self, msg: str) -> None:
        self._state = _ConnState.ERROR
        QMetaObject.invokeMethod(self, "_on_error_main", Qt.ConnectionType.QueuedConnection, msg)

    def _cb_frame(self, x: int, y: int, w: int, h: int, data: bytes) -> None:
        with self._fb_lock:
            if self._fb is None:
                return
            self._pending.append(("raw", x, y, w, h, data))
        QMetaObject.invokeMethod(self, "_schedule_paint", Qt.ConnectionType.QueuedConnection)

    def _cb_copy(self, x: int, y: int, w: int, h: int, sx: int, sy: int) -> None:
        with self._fb_lock:
            self._pending.append(("copy", x, y, w, h, sx, sy))
        QMetaObject.invokeMethod(self, "_schedule_paint", Qt.ConnectionType.QueuedConnection)

    def _cb_resize(self, w: int, h: int) -> None:
        with self._fb_lock:
            self._fb_w, self._fb_h = w, h
            self._fb = QImage(w, h, QImage.Format.Format_RGB32)
            self._fb.fill(Qt.GlobalColor.black)
            if self._worker:
                self._worker.fb_w, self._worker.fb_h = w, h
        QMetaObject.invokeMethod(self, "_schedule_paint", Qt.ConnectionType.QueuedConnection)

    # ── main-thread slots ─────────────────────────────────────────────────

    @Slot()
    def _on_connected_main(self) -> None:
        self.state_changed.emit("connected", "● подключено")
        self.update()

    @Slot()
    def _on_disconnected_main(self) -> None:
        if self._state != _ConnState.ERROR:
            self.state_changed.emit("idle", f"🖥  Нажмите «Подключить»\n{self._ip}")
        self.update()

    @Slot(str)
    def _on_error_main(self, msg: str) -> None:
        self.state_changed.emit("error", f"⚠  {msg}")
        self.update()

    @Slot()
    def _schedule_paint(self) -> None:
        if not self._paint_timer.isActive():
            self._paint_timer.start()

    @Slot()
    def _apply_updates(self) -> None:
        with self._fb_lock:
            if self._fb is None or not self._pending:
                return
            painter = QPainter(self._fb)
            for item in self._pending:
                if item[0] == "raw":
                    _, x, y, w, h, data = item
                    # NOTE: QImage(bytes,...) does NOT copy the buffer. We force
                    # a deep copy so the pixels stay valid independently of the
                    # transient `data` lifetime (and survive any future change
                    # to lazy/deferred painting).
                    img = QImage(
                        data, w, h, w * 4, QImage.Format.Format_RGB32
                    ).copy()
                    painter.drawImage(x, y, img)
                elif item[0] == "copy":
                    _, x, y, w, h, sx, sy = item
                    painter.drawImage(x, y, self._fb, sx, sy, w, h)
            painter.end()
            self._pending.clear()
        self.update()

    # ── paint ─────────────────────────────────────────────────────────────

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1a1a2e"))
        with self._fb_lock:
            fb = self._fb
        if fb is not None and not fb.isNull():
            fw, fh = fb.width(), fb.height()
            ww, wh = self.width(), self.height()
            scale  = min(ww / fw, wh / fh)
            dw, dh = int(fw * scale), int(fh * scale)
            dx, dy = (ww - dw) // 2, (wh - dh) // 2
            painter.drawImage(
                dx, dy,
                fb.scaled(dw, dh,
                          Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation),
            )
        elif self._state == _ConnState.CONNECTING:
            painter.setPen(QColor("#888"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             f"⏳  Подключение…\n{self._ip}")
        elif self._state == _ConnState.ERROR:
            painter.setPen(QColor("#f44336"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "⚠  Ошибка подключения VNC")
        painter.end()

    # ── mouse / keyboard ──────────────────────────────────────────────────

    def _to_fb(self, pos: QPoint) -> tuple[int, int]:
        if not self._fb_w or not self._fb_h:
            return 0, 0
        ww, wh = self.width(), self.height()
        scale  = min(ww / self._fb_w, wh / self._fb_h)
        ox = (ww - int(self._fb_w * scale)) // 2
        oy = (wh - int(self._fb_h * scale)) // 2
        x  = int((pos.x() - ox) / scale)
        y  = int((pos.y() - oy) / scale)
        return max(0, min(x, self._fb_w - 1)), max(0, min(y, self._fb_h - 1))

    @override
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if not self.is_connected:
            return
        b = e.button()
        if   b == Qt.MouseButton.LeftButton:   self._btn_mask |= 1
        elif b == Qt.MouseButton.MiddleButton: self._btn_mask |= 2
        elif b == Qt.MouseButton.RightButton:  self._btn_mask |= 4
        x, y = self._to_fb(e.position().toPoint())
        self._q.put((_Cmd.POINTER_EVENT, x, y, self._btn_mask))

    @override
    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if not self.is_connected:
            return
        b = e.button()
        if   b == Qt.MouseButton.LeftButton:   self._btn_mask &= ~1
        elif b == Qt.MouseButton.MiddleButton: self._btn_mask &= ~2
        elif b == Qt.MouseButton.RightButton:  self._btn_mask &= ~4
        x, y = self._to_fb(e.position().toPoint())
        self._q.put((_Cmd.POINTER_EVENT, x, y, self._btn_mask))

    @override
    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if not self.is_connected:
            return
        x, y = self._to_fb(e.position().toPoint())
        self._q.put((_Cmd.POINTER_EVENT, x, y, self._btn_mask))

    @override
    def wheelEvent(self, e: QWheelEvent) -> None:
        if not self.is_connected:
            return
        x, y = self._to_fb(e.position().toPoint())
        d    = e.angleDelta().y()
        wheel_mask = _WHEEL_UP_MASK if d > 0 else _WHEEL_DOWN_MASK
        mask = self._btn_mask | wheel_mask
        self._q.put((_Cmd.POINTER_EVENT, x, y, mask))
        self._q.put((_Cmd.POINTER_EVENT, x, y, self._btn_mask))

    @override
    def keyPressEvent(self, e: QKeyEvent) -> None:
        if not self.is_connected or e.isAutoRepeat():
            return
        ks = _qt_to_keysym(e.key(), e.text(), e.modifiers())
        if ks:
            self._q.put((_Cmd.KEY_EVENT, True, ks))

    @override
    def keyReleaseEvent(self, e: QKeyEvent) -> None:
        if not self.is_connected or e.isAutoRepeat():
            return
        ks = _qt_to_keysym(e.key(), e.text(), e.modifiers())
        if ks:
            self._q.put((_Cmd.KEY_EVENT, False, ks))

    def cleanup(self) -> None:
        self.disconnect_vnc()


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
    """
    VNC preview container.

    Layout (vertical):
      ┌──────────────────────────────────┐
      │        EmbeddedVNCWidget         │  stretch=1
      ├──────────────────────────────────┤
      │  [8 бит]  [16 бит]  [32 бит]    │  fixed 28px depth bar
      └──────────────────────────────────┘
    """

    state_changed = Signal(str, str)

    def __init__(self, ip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ip        = ip
        self._config    = ConfigManager()
        self._session: CashSession | None = None
        self._task: asyncio.Task | None   = None
        self._depth_idx = _DEFAULT_DEPTH_IDX

        self._vnc = EmbeddedVNCWidget(ip, parent=self)
        self._vnc.state_changed.connect(self._on_vnc_state)
        self._vnc.set_depth(self._depth_idx)

        v_layout = QVBoxLayout(self)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(0)
        v_layout.addWidget(self._vnc, stretch=1)

        # ── Depth / colour bar ────────────────────────────────────────────
        depth_bar = QWidget(self)
        depth_bar.setFixedHeight(28)
        depth_bar.setStyleSheet(_SS_DEPTH_BAR)

        bar_layout = QHBoxLayout(depth_bar)
        bar_layout.setContentsMargins(6, 3, 6, 3)
        bar_layout.setSpacing(4)

        self._depth_btns: list[QPushButton] = []
        for i, (label, tooltip, *_) in enumerate(_DEPTH_PRESETS):
            btn = QPushButton(label, depth_bar)
            btn.setFixedHeight(20)
            btn.setMinimumWidth(52)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, idx=i: self._on_depth_clicked(idx))
            bar_layout.addWidget(btn)
            self._depth_btns.append(btn)

        bar_layout.addStretch()
        v_layout.addWidget(depth_bar)

        self._update_depth_buttons()

    # ── asyncio task management ────────────────────────────────────────────

    def _spawn_task(self, coro) -> None:
        """Replace any in-flight task, cancelling the previous one.

        Prevents lost/overlapping tasks (and races) on rapid repeated clicks.
        """
        if self._task and not self._task.done():
            self._task.cancel()
        task = asyncio.ensure_future(coro)
        self._task = task

        def _on_done(t: asyncio.Task) -> None:
            if t is self._task:
                self._task = None
            with contextlib.suppress(asyncio.CancelledError, Exception):
                t.result()  # surface/swallow exceptions; avoid "never retrieved"

        task.add_done_callback(_on_done)

    # ── Depth selection ───────────────────────────────────────────────────

    def _on_depth_clicked(self, idx: int) -> None:
        if idx == self._depth_idx:
            return
        self._depth_idx = idx
        self._vnc.set_depth(idx)
        self._update_depth_buttons()

        label = _DEPTH_PRESETS[idx][0]
        logger.info(f"[VNC] depth changed to {label} for {self._ip}")

        # Reconnect if currently connected so new pixel format takes effect
        if self._vnc.is_connected:
            self._vnc.disconnect_vnc()
            QTimer.singleShot(400, self._vnc.connect_vnc)

    def _update_depth_buttons(self) -> None:
        for i, btn in enumerate(self._depth_btns):
            btn.setStyleSheet(_SS_BTN_ACTIVE if i == self._depth_idx else _SS_BTN_NORMAL)

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
        self._vnc.disconnect_vnc()
        audit_log(action_type="tool", action_name="vnc_disconnect",
                  target=self._ip, result="success")

    def open_fullscreen(self) -> None:
        exe_str = self._config.settings.programs.get_vnc_client()
        exe = Path(exe_str)
        if not exe.exists():
            self.state_changed.emit("error", f"⚠  VNC клиент не найден:\n{exe_str}")
            return
        self._spawn_task(self._open_fullscreen_async(exe))

    async def _ensure_x11vnc(self) -> bool:
        if not self._session or not self._session.is_connected:
            return False
        try:
            await self._session.ssh.execute(_X11VNC_CMD, timeout=10)
            return True
        except Exception as e:
            logger.error(f"[VNC] x11vnc failed: {e}")
            return False

    async def _open_fullscreen_async(self, exe: Path) -> None:
        if not self._vnc.is_connected:
            ok = await self._ensure_x11vnc()
            await asyncio.sleep(_VNC_START_DELAY if ok else 1.0)
        port    = self._config.settings.connection.vnc_port
        vnc_cfg = self._config.settings.vnc_preview
        args = [
            str(exe), f"{self._ip}:{port}",
            f"-Quality={vnc_cfg.quality}",
            f"-ColorLevel={vnc_cfg.color_level}",
        ]
        try:
            subprocess.Popen(args)
            audit_log(action_type="tool", action_name="vnc_fullscreen",
                      target=self._ip, result="success")
        except Exception as e:
            logger.error(f"[VNC] fullscreen error: {e}")

    async def _connect_flow(self) -> None:
        if self._session and self._session.is_connected:
            self.state_changed.emit("connecting", f"⏳  Запуск x11vnc на {self._ip}…")
            try:
                await self._session.ssh.execute(_X11VNC_CMD, timeout=10)
            except Exception as e:
                logger.error(f"[VNC] x11vnc failed: {e}")
                self.state_changed.emit("error", "⚠  Ошибка запуска x11vnc через SSH")
                return
        await asyncio.sleep(_VNC_START_DELAY)
        self._vnc.connect_vnc()
        audit_log(action_type="tool", action_name="vnc_preview",
                  target=self._ip, result="success")

    def _on_vnc_state(self, state: str, message: str) -> None:
        if state == "connected":
            logger.info(f"✅ Открыт VNC-просмотр для кассы {self._ip}")
        elif state == "error":
            logger.error(f"[VNC] error on {self._ip}: {message}")
        self.state_changed.emit(state, message)

    def cleanup(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._vnc.cleanup()