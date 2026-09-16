"""A single connection session: one tab with its own panels, queue and service."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
import traceback
import uuid
from pathlib import Path
from typing import Any

import asyncssh
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QLineEdit,
    QMenu,
    QMessageBox,
    QSplitter,
    QWidget,
)

from cashcontrol.builtin.file_manager.backends import (
    SFTP_SUBSYSTEM_TIMEOUT,
    ScpShellBackend,
    SftpBackend,
    SSHScpProvider,
    SSHShellRunner,
    connect_with_tofu,
    default_known_hosts_path,
)
from cashcontrol.builtin.file_manager.gui.dialogs import (
    EDITOR_MAX_BYTES,
    ConnectErrorDialog,
    DeleteConfirmDialog,
    FileEditorDialog,
    PathInputDialog,
    PropertiesDialog,
)
from cashcontrol.builtin.file_manager.gui.runtime import (
    AsyncExecutor,
    ConflictPrompter,
    JobSignalRelay,
    enqueue_delete,
    enqueue_download,
    enqueue_local_copy,
    enqueue_local_delete,
    enqueue_remote_copy,
    enqueue_upload,
    local_chmod,
    local_info,
    local_mkdir,
    local_rename,
)
from cashcontrol.builtin.file_manager.gui.widgets import FilePanel, TransferWidget
from cashcontrol.builtin.file_manager.models import (
    FileKind,
    RemoteFilesError,
    RemoteNotFoundError,
    TransferStatus,
    basename_remote,
    join_remote,
    parent_remote,
)
from cashcontrol.builtin.file_manager.service import RemoteFileService, TransferQueue

logger = logging.getLogger("cashcontrol.builtin.file_manager.gui")

SFTP_READY_TIMEOUT = 20.0


class RemoteSession(QWidget):
    """One tab in the host window: local + remote panels and its own transfers."""

    status_requested = Signal(str)
    label_changed = Signal(str)

    def __init__(self, host_window: Any, parent: Any = None) -> None:
        super().__init__(parent)
        self._host = host_window
        self._service: RemoteFileService | None = None
        self._conn: asyncssh.SSHClientConnection | None = None
        self._connected_host = ""
        self._connected_backend = ""
        self._display = ""
        self._active_panel: FilePanel | None = None

        self._executor = AsyncExecutor(self)
        self._queue = TransferQueue(concurrency=1)
        self._relay = JobSignalRelay(self)
        self._queue.subscribe(self._relay)
        self._executor.submit(self._start_queue(), report=False)
        self._prompter = ConflictPrompter(self._host)
        self._executor.finished.connect(self._route_finished)
        self._executor.error.connect(self._route_error)

        self._local = FilePanel("local", "Локально", self)
        self._remote = FilePanel(
            "remote",
            "Удалённо",
            self,
            list_dir=self._remote_list_dir,
            executor=self._executor,
        )

        self._editor_dialogs: dict[str, FileEditorDialog] = {}

        panels = QSplitter(Qt.Orientation.Horizontal, self)
        panels.addWidget(self._local)
        panels.addWidget(self._remote)
        panels.setStretchFactor(0, 1)
        panels.setStretchFactor(1, 1)

        self._transfers = TransferWidget(self._queue, self._relay, self)
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(panels)
        splitter.addWidget(self._transfers)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        self._relay.changed.connect(self._on_job_changed)

        self._transfers.hide()
        self._transfers_hide_timer = QTimer(self)
        self._transfers_hide_timer.setSingleShot(True)
        self._transfers_hide_timer.setInterval(10_000)
        self._transfers_hide_timer.timeout.connect(self._transfers.hide)

        layout = _session_layout(self)
        layout.addWidget(splitter)

        for panel in (self._local, self._remote):
            panel.focus_gained.connect(functools.partial(self._set_active, panel))
            panel.context_menu.connect(functools.partial(self._show_panel_menu, panel))
            panel.open_file_requested.connect(functools.partial(self._open_entry, panel))
            panel.error_raised.connect(self.status_requested)
            panel.files_dropped_into.connect(self._on_files_dropped_into)
            panel.remote_paths_dropped_into.connect(self._on_remote_paths_dropped_into)
        self._local.cd(str(Path.home()))
        self._set_active(self._local)

    # ── async plumbing ──────────────────────────────────────
    async def _start_queue(self) -> None:
        self._queue.start()

    async def _remote_list_dir(self, path: str):
        if self._service is None:
            raise RemoteFilesError("Нет подключения")
        return await self._service.list_dir(path)

    def host_display(self) -> str:
        return self._display

    def is_connected(self) -> bool:
        return self._service is not None

    # ── connect ─────────────────────────────────────────────
    def open_connection(
        self,
        host: str,
        port: int = 22,
        username: str = "",
        password: str = "",
        start_dir: str = "/",
        protocol: str = "auto",
    ) -> None:
        if protocol not in ("auto", "sftp", "scp"):
            protocol = "auto"
        old_service, old_conn = self._service, self._conn
        self._service, self._conn = None, None
        if old_service is not None or old_conn is not None:
            self._executor.submit(self._close_old(old_service, old_conn), report=False)
        self._connected_host = host
        self._display = f"{host}:{port}"
        self.label_changed.emit(self._display)
        self.status_requested.emit(f"Подключение к {host}…")
        logger.info(
            "Запрашиваем подключение: host=%s port=%d user=%s протокол=%s каталог=%s",
            host,
            port,
            username or "root",
            protocol,
            start_dir,
        )
        self._executor.submit(
            self._connect_coro(host, port, username or "root", password, start_dir, protocol)
        )

    async def _close_old(
        self,
        service: RemoteFileService | None,
        conn: asyncssh.SSHClientConnection | None,
    ) -> None:
        if service is not None:
            try:
                await service.close()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Не удалось закрыть прежнее подключение: %s", exc, exc_info=True)
        if conn is not None and not conn.is_closed():
            try:
                conn.close()
                await conn.wait_closed()
            except (OSError, asyncssh.Error) as exc:  # pragma: no cover - defensive
                logger.warning("Не удалось закрыть прежний SSH-канал: %s", exc)

    async def _connect_coro(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        start_dir: str,
        protocol: str,
    ):
        try:
            conn = await connect_with_tofu(
                host=host,
                port=port,
                username=username,
                password=password or None,
                known_hosts=default_known_hosts_path(),
                timeout=15.0,
            )
        except Exception as exc:
            return ("connect_error", self._diag(host, port, protocol, "SSH-соединение", exc))

        if protocol in ("auto", "sftp"):
            try:
                probe = await asyncio.wait_for(conn.start_sftp_client(), SFTP_SUBSYSTEM_TIMEOUT)
                probe.exit()
            except (TimeoutError, OSError, asyncssh.Error) as exc:
                if protocol == "sftp":
                    await self._quiet_close(conn)
                    return ("connect_error", self._diag(host, port, protocol, "SFTP-подсистема", exc))
                logger.info("SFTP не стартует (%s), переходим на SCP/shell", exc)
            else:
                service: RemoteFileService | None = RemoteFileService(
                    SftpBackend(connection=conn, own_connection=True, host=host, port=port, username=username),
                    close_backend=True,
                )
                ok, error = await self._probe_service(service, start_dir)
                if ok:
                    self._service = service
                    self._conn = None
                    self._connected_backend = "sftp"
                    logger.info("Подключение по SFTP установлено (каталог %s)", start_dir or "/")
                    return ("connected", start_dir, "sftp")
                if protocol == "sftp":
                    await self._quiet_close(conn)
                    return ("connect_error", self._diag(host, port, protocol, f"Проверка SFTP {start_dir or '/'}", error))
                logger.info("SFTP-проверка не прошла (%s), переходим на SCP/shell", error)

        runner = SSHShellRunner(conn, timeout=15.0)
        scp_connect_kwargs: dict[str, object] = {
            "host": host,
            "port": port,
            "username": username,
            "password": password or None,
            "known_hosts": default_known_hosts_path(),
            "timeout": 15.0,
        }
        scp_service = RemoteFileService(
            ScpShellBackend(
                runner,
                SSHScpProvider(conn, connect_kwargs=scp_connect_kwargs),
                timeout=15.0,
            ),
            close_backend=False,
        )
        ok, error = await self._probe_service(scp_service, start_dir)
        if not ok:
            await self._quiet_close(conn)
            return ("connect_error", self._diag(host, port, "scp", f"Проверка SCP/shell {start_dir or '/'}", error))
        self._service = scp_service
        self._conn = conn
        self._connected_backend = "scp"
        logger.info("Подключение по SCP/shell установлено (каталог %s)", start_dir or "/")
        return ("connected", start_dir, "scp")

    @staticmethod
    async def _probe_service(service: RemoteFileService, start_dir: str) -> tuple[bool, BaseException | None]:
        try:
            await asyncio.wait_for(service.stat(start_dir or "/"), SFTP_READY_TIMEOUT)
            return True, None
        except Exception as exc:
            return False, exc

    @staticmethod
    async def _quiet_close(conn: asyncssh.SSHClientConnection | None) -> None:
        if conn is not None and not conn.is_closed():
            try:
                conn.close()
                await conn.wait_closed()
            except (OSError, asyncssh.Error):
                pass

    def _diag(self, host: str, port: int, protocol: str, stage: str, exc: BaseException) -> dict[str, object]:
        logger.warning(
            "Ошибка на этапе «%s»: %s: %s",
            stage,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return {
            "host": host,
            "port": port,
            "protocol": protocol,
            "stage": stage,
            "error_line": f"{type(exc).__name__}: {exc}",
            "details": details,
            "log_tail": self._host.log_tail(120),
        }

    def _route_finished(self, payload: object) -> None:
        if not isinstance(payload, tuple):
            return
        verb = payload[0]
        if verb == "connected":
            _, start_dir, backend_name = payload
            self._remote.cd(start_dir)
            self._display = f"{self._connected_host} ({backend_name})"
            self.label_changed.emit(self._display)
            self.status_requested.emit(f"Подключено ({backend_name}): {self._connected_host}")
        elif verb == "connect_error":
            data = payload[1]
            self.status_requested.emit(f"Не удалось подключиться: {data['error_line']}")
            ConnectErrorDialog(
                host=str(data["host"]),
                port=int(data["port"]),
                protocol=str(data["protocol"]),
                stage=str(data["stage"]),
                error_line=str(data["error_line"]),
                details=str(data["details"]),
                log_tail=list(data["log_tail"]),
                on_open_log=self._host.request_log,
                parent=self._host,
            ).exec()
        elif verb == "mkdir":
            self._refresh_panel(payload[1])
            self.status_requested.emit("Папка создана")
        elif verb == "rename":
            self._refresh_panel(payload[1])
            self.status_requested.emit("Переименовано")
        elif verb == "stat":
            info = payload[1]
            try:
                dialog = PropertiesDialog(
                    info,
                    parent=self._host,
                    can_own=True,
                    apply_callback=functools.partial(self._apply_properties, "remote", info.path),
                )
                dialog.exec()
            except Exception as exc:
                logger.warning("Не удалось открыть свойства (%s): %s", info.path, exc, exc_info=True)
                QMessageBox.warning(
                    self._host,
                    "Свойства",
                    f"Не удалось открыть свойства «{info.path}»:\n{type(exc).__name__}: {exc}",
                )
        elif verb == "stat_local":
            info = payload[1]
            try:
                dialog = PropertiesDialog(
                    info,
                    parent=self._host,
                    can_own=False,
                    apply_callback=functools.partial(self._apply_properties, "local", info.path),
                )
                dialog.exec()
            except Exception as exc:
                logger.warning("Не удалось открыть свойства (%s): %s", info.path, exc, exc_info=True)
                QMessageBox.warning(
                    self._host,
                    "Свойства",
                    f"Не удалось открыть свойства «{info.path}»:\n{type(exc).__name__}: {exc}",
                )
        elif verb == "props_changed":
            self._refresh_panel(payload[1])
            self.status_requested.emit("Свойства обновлены")
        elif verb == "editor_remote":
            self.open_editor("remote", payload[1])
        elif verb == "editor_load":
            _, token, raw, error = payload
            dialog = self._editor_dialogs.get(token)
            if dialog is not None:
                dialog.apply_load(raw, error)
            if error is not None:
                self.status_requested.emit(f"Не удалось прочитать файл: {error}")
        elif verb == "editor_save":
            _, token, error = payload
            dialog = self._editor_dialogs.get(token)
            if dialog is not None:
                dialog.show_save_result(error)
                if error is None:
                    self._refresh_panel("local")
                    if self._service is not None:
                        self._refresh_panel("remote")
                    self.status_requested.emit("Файл сохранён")
        elif verb == "cd_local":
            self._local.cd(str(payload[1]))
        elif verb == "cd_remote":
            self._remote.cd(str(payload[1]))

    def _route_error(self, message: str) -> None:
        self.status_requested.emit(message)
        QMessageBox.warning(self._host, "CashSCP", message)

    # ── panels ──────────────────────────────────────────────
    def _set_active(self, panel: FilePanel) -> None:
        self._active_panel = panel

    def _refresh_panel(self, kind: str) -> None:
        panel = self._local if kind == "local" else self._remote
        if kind == "remote":
            panel._model.invalidate()
        panel.refresh()

    def _on_job_changed(self, job: object) -> None:
        self._recount_jobs()
        progress = getattr(job, "progress", None)
        if progress is None or progress.status not in (
            TransferStatus.COMPLETED,
            TransferStatus.FAILED,
            TransferStatus.CANCELLED,
        ):
            return
        if self._service is not None:
            self._refresh_panel("remote")
        self._refresh_panel("local")

    def _recount_jobs(self) -> None:
        active = any(
            job.progress.status in (TransferStatus.WAITING, TransferStatus.RUNNING)
            for job in self._queue.jobs()
        )
        if active:
            self._transfers.show()
            self._transfers_hide_timer.stop()
        else:
            self._transfers_hide_timer.start()

    # ── command handlers ────────────────────────────────────
    def copy(self, move: bool) -> None:
        panel = self._active_panel
        if panel is None:
            return
        sources = panel.selected_paths()
        if not sources:
            QMessageBox.information(self._host, "Копирование", "Ничего не выбрано")
            return
        if panel.kind == "local":
            if self._service is None:
                QMessageBox.warning(self._host, "Копирование", "Нет подключения")
                return
            target_dir = self._remote.current_dir()
            if not target_dir:
                return
            enqueue_upload(self._queue, self._service, self._prompter, sources, target_dir, move=move)
        else:
            target_dir = self._local.current_dir()
            if not target_dir:
                return
            enqueue_download(self._queue, self._service, self._prompter, sources, target_dir, move=move)

    def delete(self) -> None:
        panel = self._active_panel
        if panel is None:
            return
        sources = panel.selected_paths()
        if not sources:
            return
        has_dirs = False
        if panel.kind == "local":
            has_dirs = any(Path(path).is_dir() for path in sources)
        else:
            has_dirs = any(_is_remote_dir_cached(panel, path) for path in sources)
        dialog = DeleteConfirmDialog(len(sources), has_dirs, self._host)
        if not dialog.exec():
            return
        recursive = dialog.recursive()
        if panel.kind == "local":
            enqueue_local_delete(self._queue, sources, recursive)
        else:
            if self._service is None:
                return
            enqueue_delete(self._queue, self._service, sources, recursive)

    def new_folder(self) -> None:
        panel = self._active_panel
        if panel is None:
            return
        dialog = PathInputDialog("Новая папка", "Имя папки:", parent=self._host)
        if not dialog.exec():
            return
        name = dialog.value()
        if not name:
            return
        if panel.kind == "local":
            target = str(Path(panel.current_dir() or "") / name)
            self._executor.submit(self._local_mkdir_coro(target, "local"))
        else:
            if self._service is None:
                return
            base = panel.current_dir() or "/"
            target = join_remote(base, name)
            self._executor.submit(self._remote_mkdir_coro(target, "remote"))

    async def _local_mkdir_coro(self, path: str, kind: str) -> tuple[str, str]:
        await local_mkdir(path)
        return ("mkdir", kind)

    async def _remote_mkdir_coro(self, path: str, kind: str) -> tuple[str, str]:
        await self._service.mkdir(path, create_parents=True)
        return ("mkdir", kind)

    def rename(self) -> None:
        panel = self._active_panel
        if panel is None:
            return
        sources = panel.selected_paths()
        if len(sources) != 1:
            QMessageBox.information(self._host, "Переименование", "Выберите один элемент")
            return
        current = sources[0]
        dialog = PathInputDialog("Переименование", "Новое имя:", initial=basename_remote(current.replace(os.sep, "/")), parent=self._host)
        if not dialog.exec():
            return
        new_name = dialog.value()
        if not new_name:
            return
        if panel.kind == "local":
            target = str(Path(current).parent / new_name)
            self._executor.submit(self._local_rename_coro(current, target, "local"))
        else:
            parent = parent_remote(current)
            target = join_remote(parent, new_name)
            self._executor.submit(self._remote_rename_coro(current, target, "remote"))

    async def _local_rename_coro(self, source: str, target: str, kind: str) -> tuple[str, str]:
        await local_rename(source, target)
        return ("rename", kind)

    async def _remote_rename_coro(self, source: str, target: str, kind: str) -> tuple[str, str]:
        await self._service.rename(source, target)
        return ("rename", kind)

    def properties(self) -> None:
        panel = self._active_panel
        if panel is None:
            return
        sources = panel.selected_paths()
        if not sources:
            return
        path = sources[0]
        if panel.kind == "local":
            self._executor.submit(self._local_stat_coro(path))
        else:
            if self._service is None:
                return
            self._executor.submit(self._remote_stat_coro(path))

    async def _local_stat_coro(self, path: str) -> tuple[str, object]:
        return ("stat_local", await local_info(path))

    async def _remote_stat_coro(self, path: str) -> tuple[str, object]:
        return ("stat", await self._service.stat(path))

    def edit_file(self) -> None:
        panel = self._active_panel
        if panel is None:
            return
        sources = panel.selected_paths()
        if len(sources) != 1:
            QMessageBox.information(self._host, "Редактор", "Выберите один файл")
            return
        self._open_entry(panel, sources[0])

    def _open_entry(self, panel: FilePanel, path: str) -> None:
        if panel.kind == "local":
            info = _safe_info(path)
            if info is not None and info.is_dir:
                self._local.cd(path)
                return
            self.open_editor("local", path)
            return
        if self._service is not None:
            self._executor.submit(self._remote_probe_coro(path))

    async def _remote_probe_coro(self, path: str) -> tuple[str, str]:
        try:
            info = await self._service.stat(path)
        except RemoteNotFoundError:
            return ("editor_remote", path)
        if info.is_dir or info.kind is FileKind.SYMLINK:
            return ("cd_remote", path)
        return ("editor_remote", path)

    # ── editor ─────────────────────────────────────────────
    def open_editor(self, kind: str, path: str) -> None:
        if kind == "remote" and self._service is None:
            QMessageBox.warning(self._host, "Редактор", "Нет подключения")
            return
        dialog = FileEditorDialog(self._host, path=path, remote=kind == "remote")
        token = uuid.uuid4().hex
        self._editor_dialogs[token] = dialog
        dialog.load_requested.connect(
            lambda t=token, k=kind, p=path: self._request_editor_load(t, k, p)
        )
        dialog.save_requested.connect(
            lambda data, t=token, k=kind, p=path: self._request_editor_save(t, k, p, data)
        )
        dialog.finished.connect(lambda _result, t=token: self._editor_dialogs.pop(t, None))
        dialog.show()
        dialog.request_load()

    def _request_editor_load(self, token: str, kind: str, path: str) -> None:
        self._executor.submit(self._editor_load_coro(token, kind, path))

    async def _editor_load_coro(self, token: str, kind: str, path: str) -> tuple[str, str, bytes | None, str | None]:
        try:
            if kind == "local":
                raw = await asyncio.to_thread(_read_local_file, path, EDITOR_MAX_BYTES)
            else:
                assert self._service is not None
                raw = await self._service.read_file(path, max_bytes=EDITOR_MAX_BYTES)
        except Exception as exc:
            return ("editor_load", token, None, f"{type(exc).__name__}: {exc}")
        return ("editor_load", token, raw, None)

    def _request_editor_save(self, token: str, kind: str, path: str, data: bytes) -> None:
        self._executor.submit(self._editor_save_coro(token, kind, path, data))

    async def _editor_save_coro(self, token: str, kind: str, path: str, data: bytes) -> tuple[str, str, str | None]:
        try:
            if kind == "local":
                await asyncio.to_thread(_write_local_file, path, data)
            else:
                assert self._service is not None
                mode: int | None = None
                with contextlib.suppress(RemoteFilesError):
                    mode = (await self._service.stat(path)).mode
                await self._service.write_file_atomic(path, data, mode=mode)
        except Exception as exc:
            return ("editor_save", token, f"{type(exc).__name__}: {exc}")
        return ("editor_save", token, None)

    # ── properties ▸ apply ─────────────────────────────────
    def _apply_properties(self, kind: str, path: str, mode: int | None, owner: str | None,
                          group: str | None) -> None:
        if mode is None and owner is None and group is None:
            return
        self._executor.submit(self._apply_props_coro(kind, path, mode, owner, group))

    async def _apply_props_coro(self, kind: str, path: str, mode: int | None, owner: str | None,
                                group: str | None) -> tuple[str, str]:
        if kind == "local":
            if mode is not None:
                await local_chmod(path, mode)
        else:
            assert self._service is not None
            if mode is not None:
                await self._service.chmod(path, mode)
            if owner is not None or group is not None:
                await self._service.chown(path, owner, group)
        return ("props_changed", kind)

    def focus_address(self) -> None:
        panel = self._active_panel
        if panel is None:
            return
        edit = panel.findChild(QLineEdit)
        if edit is not None:
            edit.setFocus()
            edit.selectAll()

    def backspace_up(self) -> None:
        if self._active_panel is not None:
            self._active_panel.go_up()

    def select_all(self) -> None:
        if self._active_panel is not None:
            self._active_panel._view.selectAll()

    # ── context menu ────────────────────────────────────────
    def _show_panel_menu(self, panel: FilePanel, global_pos: Any) -> None:
        menu = QMenu(self._host)
        menu.addAction(
            "Копировать на другую панель (F5)",
            functools.partial(lambda p: self._set_active(p) or self.copy(False), panel),
        )
        menu.addAction(
            "Переместить на другую панель (F6)",
            functools.partial(lambda p: self._set_active(p) or self.copy(True), panel),
        )
        menu.addSeparator()
        menu.addAction(
            "Новая папка…",
            functools.partial(lambda p: self._set_active(p) or self.new_folder(), panel),
        )
        menu.addAction(
            "Переименовать…",
            functools.partial(lambda p: self._set_active(p) or self.rename(), panel),
        )
        menu.addAction(
            "Удалить…",
            functools.partial(lambda p: self._set_active(p) or self.delete(), panel),
        )
        menu.addAction(
            "Свойства",
            functools.partial(lambda p: self._set_active(p) or self.properties(), panel),
        )
        menu.addSeparator()
        menu.addAction("Обновить", lambda: self._refresh_panel(panel.kind))
        menu.exec(global_pos)

    # ── drag & drop ─────────────────────────────────────────
    def _on_files_dropped_into(self, kind: str, target_dir: str | None, local_files: list[str]) -> None:
        if not target_dir or not local_files:
            return
        if kind == "remote":
            if self._service is not None:
                enqueue_upload(self._queue, self._service, self._prompter, local_files, target_dir)
        else:
            enqueue_local_copy(self._queue, local_files, target_dir)

    def _on_remote_paths_dropped_into(self, kind: str, target_dir: str | None, remote_paths: list[str]) -> None:
        if not target_dir or not remote_paths:
            return
        if kind == "local":
            if self._service is not None:
                enqueue_download(self._queue, self._service, self._prompter, remote_paths, target_dir)
        elif self._service is not None:
            enqueue_remote_copy(self._queue, self._service, self._prompter, remote_paths, target_dir)

    # ── shutdown ────────────────────────────────────────────
    def shutdown(self) -> None:
        self._executor.shutdown(self._finalize())

    async def _finalize(self) -> None:
        await self._queue.stop()
        if self._service is not None:
            try:
                await self._service.close()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Ошибка закрытия сервиса: %s", exc)
            self._service = None
        if self._conn is not None and not self._conn.is_closed():
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None


def _session_layout(widget: QWidget) -> Any:
    from PySide6.QtWidgets import QVBoxLayout

    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    return layout


def _is_remote_dir_cached(panel: FilePanel, path: str) -> bool:
    for entry in panel._model.entries():
        if entry.path == path:
            return entry.kind is FileKind.DIRECTORY
    return False


def _safe_info(path: str):
    try:
        return local_info(path)
    except Exception:
        return None


def _read_local_file(path: str, limit: int) -> bytes:
    data = Path(path).read_bytes()
    if len(data) > limit:
        raise RemoteFilesError(f"{path} превышает лимит {limit} байт")
    return data


def _write_local_file(path: str, data: bytes) -> None:
    Path(path).write_bytes(data)


__all__ = ["RemoteSession"]
