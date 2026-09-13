"""PTY-канал: create_process, потоки, resize, кодировка utf-8/cp1251."""

from __future__ import annotations

import asyncio
import gc
import logging
from typing import Callable, Optional

import asyncssh

_LOG = logging.getLogger("ssh_term.core.pty")

_READ_CHUNK = 8192
_FEED_SLICE = 4096

# полный sweep GC по живому scrollback (1.6M+ Char-объектов под большим
# окном) даёт периодические паузы по 50-100 мс на верхушке чанк-фида.
# Эмитатор не создаёт reference-циклов на горячем пути (refcount всё
# освобождает), поэтому мусорный коллектор можно выключать на время флуда
# и разрешать один полный проход после — пауза мажет на конец потока,
# а не в середину прокрутки.
_gc_guard = 0


def _gc_acquire() -> None:
    global _gc_guard
    if _gc_guard == 0:
        gc.disable()
    _gc_guard += 1


def _gc_release() -> None:
    global _gc_guard
    _gc_guard -= 1
    if _gc_guard == 0:
        gc.enable()


class PtyStream:
    """Интерактивная PTY-сессия поверх готового asyncssh-соединения."""

    def __init__(
        self,
        conn: asyncssh.SSHClientConnection,
        rows: int = 24,
        cols: int = 80,
        term_type: str = "xterm-256color",
        on_output: Optional[Callable[[str], None]] = None,
        on_closed: Optional[Callable[[Optional[int]], None]] = None,
    ) -> None:
        self._conn = conn
        self._rows = rows
        self._cols = cols
        self._term_type = term_type
        self._on_output = on_output
        self._on_closed = on_closed

        self._process: Optional[asyncssh.SSHClientProcess[str]] = None
        self._reader_task: Optional[asyncio.Task[None]] = None

        self._partial_utf8 = b""  # недокодированный хвост из прошлого чанка

    # ---- properties ----

    @property
    def is_running(self) -> bool:
        return self._process is not None and not self._process.is_closing()

    # ---- public API ----

    async def start(self) -> None:
        """Открыть PTY и запустить читатель stdout/stderr."""
        if self.is_running:
            return
        self._process = await self._conn.create_process(
            term_type=self._term_type,
            term_size=(self._cols, self._rows),  # asyncssh ждёт (width, height)!
            encoding=None,  # байты: декодируем сами, с fallback cp1251
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        """Закрыть PTY-канал и читателя."""
        proc, self._process = self._process, None
        task, self._reader_task = self._reader_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if proc is not None:
            proc.close()
            try:
                await asyncio.wait_for(proc.wait_closed(), timeout=3.0)
            except (asyncio.TimeoutError, OSError):
                pass

    async def resize(self, rows: int, cols: int) -> None:
        """Изменить размер PTY."""
        proc = self._process
        if proc is None:
            self._rows, self._cols = rows, cols
            return
        self._rows, self._cols = rows, cols
        if proc.is_closing():
            return
        proc.change_terminal_size(cols, rows)

    def write_sync(self, data: str) -> None:
        """Быстрая запись без drain (для интерактивного ввода из Qt-слоя)."""
        proc = self._process
        if proc is not None and not proc.is_closing():
            proc.stdin.write(data.encode("utf-8"))

    # ---- internals ----

    async def _read_loop(self) -> None:
        proc = self._process
        assert proc is not None
        loop = asyncio.get_running_loop()
        try:
            while not proc.at_eof(None) and not proc.is_closing():  # datatype=None -> stdout
                data = await proc.stdout.read(_READ_CHUNK)
                if not data:
                    if proc.at_eof(None):
                        break
                    continue
                text = self._decode(data)
                if text and self._on_output:
                    await self._emit_output(text)
                # stderr перенаправлен в stdout PTY самой PTY-сессией
        except (asyncio.CancelledError, ConnectionError, OSError):
            pass
        except asyncssh.Error:
            pass
        finally:
            exit_status: Optional[int] = None
            try:
                exit_status = proc.returncode
            except Exception:  # noqa: BLE001 - статус может быть недоступен
                pass
            if self._on_closed is not None:
                loop.call_soon_threadsafe(self._on_closed, exit_status)

    async def _emit_output(self, text: str) -> None:
        """Порционная подача в эмулятор.

        Большой чанк скармливается emulator.feed синхронно и за один раз
        морозит основной цикл на десятки мс (pyte медленный). Режем на
        _FEED_SLICE и отдаём управление loop'у между порциями, чтобы Qt
        успевал прожимать repaint/ввод — терминал не «виснет», а плавно
        догоняет поток."""
        if len(text) <= _FEED_SLICE:
            self._on_output(text)
            return
        _gc_acquire()
        try:
            for i in range(0, len(text), _FEED_SLICE):
                self._on_output(text[i : i + _FEED_SLICE])
                await asyncio.sleep(0)
        finally:
            _gc_release()

    def _decode(self, data: bytes) -> str:
        """utf-8 с fallback на cp1251, с учётом межчанкового разрыва символа."""
        if self._partial_utf8:
            data = self._partial_utf8 + data
            self._partial_utf8 = b""
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.reason == "unexpected end of data" or self._is_truncated_tail(data, exc):
                # хвост — незавершённый multibyte (разрыв на границе чанка):
                # ждём продолжение в следующем чанке, остальное декодируем как есть
                self._partial_utf8 = data[exc.start :]
                return data[: exc.start].decode("utf-8", errors="replace")
            return data.decode("cp1251", errors="replace")

    @staticmethod
    def _is_truncated_tail(data: bytes, exc: UnicodeDecodeError) -> bool:
        """True, если с exc.start начинается похожее на многобайтовый UTF-8
        начало последовательности (ведущий байт + только continuation-байты)
        на самом конце чанка. Покрывает и 2-байтовую кириллицу (\\xd0/\\xd1)."""
        if exc.end != len(data):
            return False
        tail = data[exc.start :]
        if not tail:
            return False
        lead, rest = tail[0], tail[1:]
        if not (0xC2 <= lead <= 0xF4):
            return False
        return all(0x80 <= b <= 0xBF for b in rest)
