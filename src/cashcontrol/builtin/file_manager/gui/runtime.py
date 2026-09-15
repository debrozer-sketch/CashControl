"""GUI plumbing: asyncio bridge, local filesystem access and job wrappers plus
the table models for the two file panels.

Single module for everything the GUI hands off to worker threads/coroutines:
the Qt->asyncio ``AsyncExecutor``, synchronous local filesystem helpers,
transfer/delete jobs backed by ``RemoteFileService`` + ``TransferQueue`` and the
Qt table models used by both file panels.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import shutil
import stat as _stat
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    QAbstractItemModel,
    QByteArray,
    QDir,
    QMimeData,
    QModelIndex,
    QObject,
    Qt,
    Signal,
)
from PySide6.QtWidgets import QFileIconProvider, QFileSystemModel

from cashcontrol.builtin.file_manager.gui.dialogs import ConflictDialog
from cashcontrol.builtin.file_manager.models import (
    FileKind,
    OperationCancelledError,
    OverwritePolicy,
    RemoteFileInfo,
    RemoteFilesError,
    RemoteNotFoundError,
    RemotePermissionError,
    TransferOptions,
    TransferResult,
    UnsupportedByBackendError,
    basename_remote,
    join_remote,
)
from cashcontrol.builtin.file_manager.service import ConflictInfo, auto_resolve, renamed_destination

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from cashcontrol.builtin.file_manager.service import (
        RemoteFileService,
        TransferJob,
        TransferQueue,
    )

MAX_IN_MEMORY = 8 * 1024 * 1024


# ── Qt↔asyncio bridge ───────────────────────────────────────────────────────
class AsyncExecutor(QObject):
    """Submits coroutines to a background event loop and reports via Qt signals.

    ``finished``/``error`` are emitted from the loop thread and delivered with
    queued connections to the GUI thread (the default for cross-thread signals),
    so connected slots never touch Qt widgets from the wrong thread.
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._thread = threading.Thread(
                target=self._run_loop,
                name="remote-files-async",
                daemon=True,
            )
            self._thread.start()
            self._started.wait(timeout=10)
        assert self._loop is not None
        return self._loop

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._started.set()
        try:
            loop.run_forever()
        finally:
            self._loop = None

    def submit(self, coro: Awaitable, report: bool = True) -> None:
        """Run ``coro`` on the background loop; report result/error by default."""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        future.add_done_callback(_make_done_callback(self.finished, self.error, report))

    def shutdown(self, finalizer: Awaitable | None = None, timeout: float = 2.0) -> None:
        """Stop the loop; optionally run a finalization coroutine first.

        ``finalizer`` is awaited (up to ``timeout`` seconds) before the loop is
        stopped so background tasks such as the transfer queue workers can exit
        cleanly instead of being aborted mid-pending.
        """
        loop = self._loop
        if loop is not None and loop.is_running():
            if finalizer is not None:
                future = asyncio.run_coroutine_threadsafe(finalizer, loop)
                with suppress(Exception):
                    future.result(timeout=timeout)
            loop.call_soon_threadsafe(loop.stop)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._loop = None
        self._thread = None


def _make_done_callback(
    finished: Signal,
    error: Signal,
    report: bool,
) -> Callable[[asyncio.Future], None]:
    def on_done(future: asyncio.Future) -> None:
        if not report:
            return
        try:
            result = future.result()
        except asyncio.CancelledError:
            error.emit("Operation cancelled")
        except Exception as exc:
            error.emit(f"{type(exc).__name__}: {exc}")
        else:
            finished.emit(result)

    return on_done


class JobSignalRelay(QObject):
    """Marshals TransferQueue notifications from the loop thread to the GUI."""

    changed = Signal(object)

    def __call__(self, job: object) -> None:
        self.changed.emit(job)


# ── Local filesystem access (keeps the two panels symmetric) ────────────────
def local_info(path_str: str) -> RemoteFileInfo:
    """Read local metadata into RemoteFileInfo, keeping both panels symmetric."""
    path = Path(path_str)
    if not path.exists() and not path.is_symlink():
        raise RemoteNotFoundError(f"No such local path: {path_str}")
    lstat = path.lstat()
    kind = FileKind.FILE
    if path.is_symlink():
        kind = FileKind.SYMLINK
    elif path.is_dir():
        kind = FileKind.DIRECTORY
    st = path.stat()
    return RemoteFileInfo(
        path=str(path),
        name=path.name or str(path),
        kind=kind,
        size=st.st_size if not path.is_dir() else None,
        modified_at=datetime.datetime.fromtimestamp(st.st_mtime),
        mode=_stat.S_IMODE(lstat.st_mode),
        owner=None,
        group=None,
        hidden=path.name.startswith("."),
    )


async def local_stat(path: str) -> RemoteFileInfo:
    return await asyncio.to_thread(local_info, path)


async def local_mkdir(path: str, mode: int | None = None) -> None:
    def _do() -> None:
        Path(path).mkdir(mode=mode if mode is not None else 0o755)
        if mode is not None:
            os.chmod(path, mode)

    await asyncio.to_thread(_do)


async def local_rename(source: str, destination: str) -> None:
    def _do() -> None:
        os.rename(source, destination)

    await asyncio.to_thread(_do)


async def local_chmod(path: str, mode: int) -> None:
    await asyncio.to_thread(os.chmod, path, mode)


async def local_remove(paths: list[str], recursive: bool) -> int:
    """Delete local paths; directories require ``recursive``. Returns count done."""

    def _do() -> int:
        removed = 0
        for raw in paths:
            path = Path(raw)
            if path.is_dir() and not path.is_symlink():
                if not recursive:
                    raise RemotePermissionError(f"{raw} is a directory; use recursive delete")
                shutil.rmtree(path)
                removed += 1
                continue
            path.unlink()
            removed += 1
        return removed

    return await asyncio.to_thread(_do)


def local_copy_into_file_ops(paths: list[str], dest_dir: str, overwrite: bool) -> int:
    """Synchronous copy of local paths into dest_dir (used on a worker thread)."""
    target = Path(dest_dir)
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for raw in paths:
        src = Path(raw)
        dst = target / src.name
        if dst.exists() and not overwrite:
            continue
        if src.is_dir() and not src.is_symlink():
            shutil.copytree(src, dst, dirs_exist_ok=overwrite)
        else:
            shutil.copy2(src, dst)
        copied += 1
    return copied


async def local_copy_into(paths: list[str], dest_dir: str, overwrite: bool) -> int:
    return await asyncio.to_thread(local_copy_into_file_ops, paths, dest_dir, overwrite)


# ── Transfer/delete job wrappers ────────────────────────────────────────────
class ConflictPrompter(QObject):
    """Synchronous-to-GUI conflict resolver: shows dialog, blocks the loop thread."""

    _request = Signal(object)
    _reply = Signal(object)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._reply_ready = threading.Event()
        self._decision: tuple[str, bool] = ("skip", False)
        self._apply_all = False
        self._cached_action: str | None = None
        self._request.connect(self._ask)
        self._reply.connect(self._receive)

    def reset(self) -> None:
        self._apply_all = False
        self._cached_action = None

    def resolve(self, conflict: ConflictInfo) -> tuple[str, bool]:
        if self._apply_all and self._cached_action in ("overwrite", "overwrite_if_newer", "rename", "skip"):
            return (self._cached_action, True)
        self._reply_ready.clear()
        self._decision = ("skip", False)
        self._request.emit(conflict)
        while not self._reply_ready.wait(0.05):
            pass
        action, apply_all = self._decision
        if apply_all and action in ("overwrite", "overwrite_if_newer", "rename", "skip"):
            self._apply_all = True
            self._cached_action = action
        if action == "abort":
            raise OperationCancelledError("Передача прервана пользователем")
        return (action, apply_all)

    def _ask(self, conflict: ConflictInfo) -> None:
        dialog = ConflictDialog(conflict, self)
        dialog.exec()
        self._reply.emit((dialog.chosen_action(), dialog.apply_to_all()))

    def _receive(self, decision: tuple[str, bool]) -> None:
        self._decision = decision
        self._reply_ready.set()


def _progress_updater(job: TransferJob):
    def update(source: str, destination: str, done: int, total: int) -> None:
        progress = job.progress
        progress.current_path = destination
        progress.total_transferred_bytes = done
        progress.total_size = total if total > 0 else progress.total_size

    return update


def _label(paths: list[str]) -> str:
    if not paths:
        return ""
    if len(paths) == 1:
        return basename_remote(paths[0])
    return f"{len(paths)} элементов"


def enqueue_upload(
    queue: TransferQueue,
    service: RemoteFileService,
    prompter: ConflictPrompter,
    local_paths: list[str],
    remote_dir: str,
    move: bool = False,
) -> str:
    options = TransferOptions(overwrite_policy=OverwritePolicy.ASK)

    async def runner(job: TransferJob) -> TransferResult:
        prompter.reset()
        result = await service.upload(
            [Path(path) for path in local_paths],
            remote_dir,
            options,
            on_conflict=prompter.resolve,
            progress=_progress_updater(job),
        )
        if move and result.success:
            removed = await local_remove(local_paths, recursive=True)
            result.transferred_files += removed
        return result

    return queue.enqueue("upload", _label(local_paths), remote_dir, runner)


def enqueue_download(
    queue: TransferQueue,
    service: RemoteFileService,
    prompter: ConflictPrompter,
    remote_paths: list[str],
    local_dir: str,
    move: bool = False,
) -> str:
    options = TransferOptions(overwrite_policy=OverwritePolicy.ASK)

    async def runner(job: TransferJob) -> TransferResult:
        prompter.reset()
        result = await service.download(
            remote_paths,
            Path(local_dir),
            options,
            on_conflict=prompter.resolve,
            progress=_progress_updater(job),
        )
        if move and result.success:
            await service.remove(remote_paths, recursive=True)
        return result

    return queue.enqueue("download", _label(remote_paths), local_dir, runner)


def enqueue_delete(
    queue: TransferQueue,
    service: RemoteFileService,
    remote_paths: list[str],
    recursive: bool,
) -> str:
    async def runner(job: TransferJob) -> TransferResult:
        return await service.remove(remote_paths, recursive=recursive, on_confirm=None)

    return queue.enqueue("delete", _label(remote_paths), "", runner)


def enqueue_local_delete(
    queue: TransferQueue,
    local_paths: list[str],
    recursive: bool,
) -> str:
    async def runner(job: TransferJob) -> TransferResult:
        removed = await local_remove(local_paths, recursive)
        return TransferResult(operation="delete", transferred_files=removed)

    return queue.enqueue("delete", _label(local_paths), "", runner)


def enqueue_local_copy(
    queue: TransferQueue,
    local_paths: list[str],
    dest_dir: str,
    move: bool = False,
) -> str:
    async def runner(job: TransferJob) -> TransferResult:
        copied = await local_copy_into(local_paths, dest_dir, overwrite=False)
        if move and copied:
            await local_remove(local_paths, recursive=False)
        return TransferResult(operation="copy", transferred_files=copied)

    return queue.enqueue("copy", _label(local_paths), dest_dir, runner)


def enqueue_remote_copy(
    queue: TransferQueue,
    service: RemoteFileService,
    prompter: ConflictPrompter,
    remote_paths: list[str],
    dest_dir: str,
) -> str:
    options = TransferOptions(overwrite_policy=OverwritePolicy.ASK)

    async def runner(job: TransferJob) -> TransferResult:
        prompter.reset()
        copied = 0
        for source in remote_paths:
            copied += await _copy_one(service, source, dest_dir, options, prompter, job)
        return TransferResult(operation="copy", transferred_files=copied)

    return queue.enqueue("copy", _label(remote_paths), dest_dir, runner)


async def _copy_one(
    service: RemoteFileService,
    source: str,
    dest_dir: str,
    options: TransferOptions,
    prompter: ConflictPrompter,
    job: TransferJob,
) -> int:
    info = await service.stat(source)
    name = basename_remote(source)
    destination = join_remote(dest_dir, name)
    destination = await _resolve_destination(service, source, destination, info, options, prompter)
    if destination is None:
        return 0
    if info.is_dir:
        await service.mkdir(destination, create_parents=True)
        children = await service.list_dir(source)
        total = 0
        for child in children:
            if child.name in (".", ".."):
                continue
            total += await _copy_one(service, child.path, destination, options, prompter, job)
        return total
    await _copy_file(service, source, destination, info, job)
    return 1


async def _resolve_destination(
    service: RemoteFileService,
    source: str,
    destination: str,
    info: RemoteFileInfo,
    options: TransferOptions,
    prompter: ConflictPrompter | None,
) -> str | None:
    try:
        existing = await service.stat(destination)
    except RemoteNotFoundError:
        return destination
    conflict = ConflictInfo(
        source=source,
        destination=destination,
        source_size=info.size,
        destination_size=existing.size,
        source_mtime=info.modified_at,
        destination_mtime=existing.modified_at,
    )
    if options.overwrite_policy is OverwritePolicy.ASK and prompter is not None:
        decision, _ = prompter.resolve(conflict)
    else:
        decision = auto_resolve(conflict, options)
    if decision == "skip":
        return None
    if decision == "rename":
        return renamed_destination(destination)
    return destination


async def _copy_file(
    service: RemoteFileService,
    source: str,
    destination: str,
    info: RemoteFileInfo,
    job: TransferJob,
) -> None:
    if info.size is not None and info.size <= MAX_IN_MEMORY:
        try:
            data = await service.read_file(source, max_bytes=MAX_IN_MEMORY)
        except UnsupportedByBackendError:
            pass
        else:
            await service.write_file_atomic(destination, data, mode=info.mode)
            job.progress.total_transferred_bytes += len(data)
            return
    options = TransferOptions(overwrite_policy=OverwritePolicy.OVERWRITE)
    temp_dir = Path(tempfile.mkdtemp(prefix="rfiles-copy-"))
    try:
        temp_file = temp_dir / (info.name or "copy")
        await service.backend.download(source, temp_file, options)
        await service.backend.upload(temp_file, destination, options)
        job.progress.total_transferred_bytes += info.size or 0
    except RemoteFilesError:
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


__all__ = [
    "AsyncExecutor",
    "ConflictPrompter",
    "JobSignalRelay",
    "enqueue_delete",
    "enqueue_download",
    "enqueue_local_copy",
    "enqueue_local_delete",
    "enqueue_remote_copy",
    "enqueue_upload",
    "local_chmod",
    "local_copy_into",
    "local_info",
    "local_mkdir",
    "local_remove",
    "local_rename",
    "local_stat",
]


# --- merged from tablemodels.py ---

RFILES_MIME = "application/x-rfiles-paths"

_COLUMNS = ("Имя", "Размер", "Изменён", "Права")


class LocalFileModel(QFileSystemModel):
    """QFileSystemModel with a hidden-files toggle and RemoteFileInfo accessors."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._show_hidden = False
        self._apply_filter()

    def _apply_filter(self) -> None:
        flags = QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
        if self._show_hidden:
            flags |= QDir.Filter.Hidden | QDir.Filter.System
        self.setFilter(flags)

    def toggle_hidden(self, show: bool) -> None:
        self._show_hidden = show
        self._apply_filter()

    def info_for(self, path: str) -> RemoteFileInfo | None:
        try:
            return local_info(path)
        except Exception:
            return None

    def info_for_index(self, index: QModelIndex) -> RemoteFileInfo | None:
        if not index.isValid():
            return None
        return self.info_for(self.filePath(index))

    def cd(self, path: str) -> None:
        super().setRootPath(path)

    def directory(self) -> str:
        root = self.rootPath()
        return root if root else str(Path.home())


class RemoteFileModel(QAbstractItemModel):
    """Shows one directory at a time; listings are loaded asynchronously and cached."""

    listing_failed = Signal(str)
    directory_loaded = Signal(str)

    def __init__(
        self,
        list_dir: Callable[[str], Awaitable[list[RemoteFileInfo]]] | None = None,
        executor: AsyncExecutor | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._list_dir = list_dir if list_dir is not None else self._no_listing
        self._executor = executor if executor is not None else AsyncExecutor(self)
        self._executor.finished.connect(self._on_finished)
        self._executor.error.connect(self._on_error)
        self._directory: str | None = None
        self._entries: list[RemoteFileInfo] = []
        self._cache: dict[str, list[RemoteFileInfo]] = {}
        self._loading = False
        self._show_hidden = False
        self._refresh_seq = 0
        self._icons = QFileIconProvider()

    async def _no_listing(self, path: str) -> list[RemoteFileInfo]:
        raise ValueError(f"Not connected; cannot list {path}")

    # ── Qt model interface ──────────────────────────────────
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if parent.isValid() or not 0 <= row < len(self._entries):
            return QModelIndex()
        return self.createIndex(row, column, self._entries[row])

    def parent(self, child: QModelIndex) -> QModelIndex:
        return QModelIndex()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        info = self._entries[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return info.name
            if column == 1:
                return info.size_formatted
            if column == 2:
                if info.modified_at is None:
                    return ""
                return info.modified_at.strftime("%Y-%m-%d %H:%M")
            if column == 3:
                return info.mode_str
            return None
        if role == Qt.ItemDataRole.DecorationRole and column == 0:
            if info.is_dir:
                return self._icons.icon(QFileIconProvider.IconType.Folder)
            return self._icons.icon(QFileIconProvider.IconType.File)
        if role == Qt.ItemDataRole.UserRole:
            return info
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation is Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _COLUMNS[section] if section < len(_COLUMNS) else None
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Sort rows by a column; directories always stay grouped on top."""
        if column < 0 or column >= len(_COLUMNS) or self.rowCount() <= 1:
            return

        def value(entry: RemoteFileInfo) -> Any:
            if column == 1:
                return entry.size if entry.size is not None else -1
            if column == 2:
                return entry.modified_at if entry.modified_at is not None else datetime.datetime.min
            if column == 3:
                return entry.mode_str
            return entry.name.casefold()

        reverse = order is Qt.SortOrder.DescendingOrder
        dirs = sorted((e for e in self._entries if e.is_dir), key=value, reverse=reverse)
        files = sorted((e for e in self._entries if not e.is_dir), key=value, reverse=reverse)
        self.beginResetModel()
        self._entries = dirs + files
        self.endResetModel()

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled

    # ── drag & drop metadata (remote panel lets the OS drop local files in) ──
    def mimeTypes(self) -> list[str]:
        return [RFILES_MIME]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        mime = QMimeData()
        paths = [str(info.path) for index in indexes if (info := self._entries[index.row()])]
        mime.setData(RFILES_MIME, QByteArray("\n".join(dict.fromkeys(paths)).encode("utf-8")))
        return mime

    # ── navigation ──────────────────────────────────────────
    def current_directory(self) -> str:
        return self._directory if self._directory else "/"

    def entry(self, row: int) -> RemoteFileInfo | None:
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def entries(self) -> list[RemoteFileInfo]:
        return list(self._entries)

    def cd(self, path: str) -> None:
        self._directory = path
        self.refresh()

    def refresh(self) -> None:
        if self._directory is None or self._loading:
            return
        self._refresh_seq += 1
        self._loading = True
        self.beginResetModel()
        self._entries = []
        self.endResetModel()
        self._executor.submit(self._load(self._directory, self._refresh_seq))

    async def _load(self, path: str, seq: int) -> tuple[str, list[RemoteFileInfo]]:
        cached = self._cache.get(path)
        if cached is None:
            cached = await self._list_dir(path)
            if cached is not None:
                self._cache[path] = cached
        return (path, cached)

    def _on_finished(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        path, entries = payload
        if path != self._directory:
            return
        self.beginResetModel()
        self._entries = [entry for entry in entries if self._show_hidden or not entry.hidden]
        self.endResetModel()
        self._loading = False
        self.directory_loaded.emit(path)

    def _on_error(self, message: str) -> None:
        self._loading = False
        self.listing_failed.emit(message)

    def toggle_hidden(self, show: bool) -> None:
        self._show_hidden = show
        self.refresh()

    def invalidate(self, path: str | None = None) -> None:
        if path is None:
            self._cache.clear()
            return
        prefix = path if path.endswith("/") else path + "/"
        for cached in [c for c in self._cache if c == path or c.startswith(prefix)]:
            self._cache.pop(cached, None)


__all__ = ["RFILES_MIME", "LocalFileModel", "RemoteFileModel"]
