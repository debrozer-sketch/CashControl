"""TerminalSession: связка SSHConnection + PtyStream + TerminalEmulator.

Живёт в qasync-цикле. Qt-виджет общается с сессией через сигналы/колбэки,
вся async-работа — здесь.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

import qasync

from core.connection import SSHConnection
from core.pty import PtyStream
from data.profiles import HostProfile, ProfileStore
from terminal.emulator import TerminalEmulator

_LOG = logging.getLogger("ssh_term.core.session")


class TerminalSession(QObject):
    """Одна вкладка = одна сессия = одно SSH-соединение + PTY."""

    statusChanged = Signal(str)  # текст статуса
    connected = Signal()
    disconnected = Signal(str)  # причина
    connectionFailed = Signal(str)
    outputReceived = Signal()  # новые байты от хоста записаны в эмулятор

    def __init__(
        self,
        profile: HostProfile,
        store: ProfileStore,
        emulator: Optional[TerminalEmulator] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self._store = store

        # эмулятор принадлежит сессии; виджет использует его же (или передаёт свой)
        self.emulator = emulator or TerminalEmulator(
            cols=80,
            rows=24,
            on_title=self._handle_title,
        )

        self._conn: Optional[SSHConnection] = None
        self._pty: Optional[PtyStream] = None
        self._connect_task: Optional[asyncio.Task] = None

        self._output_buffer: list[str] = []
        self.stream_dump = None  # file handle сырого дампа (диагностика)

    # ---- свойства ----

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and self._conn.is_connected

    # ---- подключение ----

    def start(self) -> None:
        """Запустить подключение в фоне (не блокирует GUI)."""
        self.statusChanged.emit(f"Подключение к {self.profile.host}…")
        self._connect_task = asyncio.ensure_future(self._connect_and_open_pty())

    async def _connect_and_open_pty(self) -> None:
        t0 = asyncio.get_running_loop().time()
        try:
            self._conn = SSHConnection(
                host=self.profile.host,
                username=self.profile.username,
                port=self.profile.port,
                password=self.profile.password,
                known_hosts_path=self._store.known_hosts_path,
                connect_timeout=self._store.settings.connect_timeout,
                keepalive_interval=self._store.settings.keepalive_interval,
            )
            _LOG.info("connecting to %s:%s as %s …", self.profile.host, self.profile.port, self.profile.username)
            await self._conn.connect()
            _LOG.info("connected in %.2fs", asyncio.get_running_loop().time() - t0)
        except Exception as exc:  # noqa: BLE001 - в UI показываем любую ошибку
            _LOG.error("connect failed after %.2fs: %s", asyncio.get_running_loop().time() - t0, exc)
            self.connectionFailed.emit(str(exc))
            return

        self.connected.emit()
        self.statusChanged.emit(
            f"Подключено: {self.profile.username}@{self.profile.host}:{self.profile.port}"
        )
        self._store.push_recent(self.profile)

        # PTY
        self._pty = PtyStream(
            await self._conn.acquire(),
            rows=self.emulator.rows,
            cols=self.emulator.cols,
            term_type=self._store.settings.term_type,
            on_output=self._on_output,
            on_closed=self._on_pty_closed,
        )
        try:
            await self._pty.start()
        except Exception as exc:  # noqa: BLE001
            _LOG.error("pty start failed: %s", exc)
            self.connectionFailed.emit(f"PTY: {exc}")

    # ---- вывод хоста ----

    def _on_output(self, text: str) -> None:
        """Данные из PTY -> эмулятор. Ошибка эмуляции не должна рвать сессию."""
        if self.stream_dump is not None:
            try:
                self.stream_dump.write(text)
            except Exception:  # noqa: BLE001 - дамп не должен ломать сессию
                self.stream_dump = None
        try:
            self.emulator.feed(text)
        except Exception:  # noqa: BLE001 - рендер/эмуляция не должны убивать PTY
            _LOG.exception("emulator feed failed (chunk skipped)")
        self.outputReceived.emit()

    # ---- дамп потока (диагностика) ----

    def start_stream_dump(self, path: Path) -> None:
        """Писать сырой вывод хоста в файл (диагностика mc и др. TUI)."""
        self.stop_stream_dump()
        try:
            self.stream_dump = open(path, "a", encoding="utf-8", errors="replace")
            self._stream_dump_path = path
        except OSError as exc:
            _LOG.warning("cannot open stream dump %s: %s", path, exc)
            self.stream_dump = None

    def stop_stream_dump(self) -> Optional[Path]:
        f, self.stream_dump = self.stream_dump, None
        path = getattr(self, "_stream_dump_path", None)
        if f is not None:
            try:
                f.close()
            except OSError:
                pass
        return path

    # ---- ввод ----

    def write(self, data: str) -> None:
        """Ввод из Qt-виджета: отправить в PTY."""
        if self._pty is not None:
            self._pty.write_sync(data)

    # ---- сервис ----

    async def resize_pty(self, rows: int, cols: int) -> None:
        if self._pty is not None:
            await self._pty.resize(rows, cols)

    def _handle_title(self, title: str) -> None:
        self.statusChanged.emit(title)

    def _on_pty_closed(self, exit_status: Optional[int]) -> None:
        try:
            self.disconnected.emit(f"Сессия завершена (код {exit_status})")
        except RuntimeError:
            # окно/сессия уже удалены (QObject deleted) — событие никому не нужно
            pass

    async def close(self) -> None:
        """Аккуратно закрыть всё."""
        if self._pty is not None:
            await self._pty.stop()
            self._pty = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def abort(self) -> None:
        """Быстрое закрытие без ожидания (закрытие окна)."""
        if self._connect_task is not None:
            self._connect_task.cancel()
        pty, self._pty = self._pty, None
        if pty is not None:
            asyncio.ensure_future(self._abort_pty(pty))
        conn = self._conn
        if conn is not None:
            asyncio.ensure_future(self._close_quietly(conn))

    @staticmethod
    async def _abort_pty(pty: PtyStream) -> None:
        """Остановить PTY-читателя: иначе его finally динет _on_pty_closed
        уже после удаления окна (QObject deleted) и уронит цикл."""
        try:
            await asyncio.wait_for(pty.stop(), timeout=3.0)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    async def _close_quietly(conn: SSHConnection) -> None:
        try:
            await asyncio.wait_for(conn.close(), timeout=3.0)
        except Exception:  # noqa: BLE001
            pass
