"""Interactive widgets: dual file panels, transfer side panel and log console."""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QMimeData,
    QObject,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QToolButton,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cashcontrol.builtin.file_manager.backends import default_config_dir
from cashcontrol.builtin.file_manager.gui.runtime import (
    RFILES_MIME,
    LocalFileModel,
    RemoteFileModel,
)
from cashcontrol.builtin.file_manager.models import TransferStatus, parent_remote

if TYPE_CHECKING:
    from cashcontrol.builtin.file_manager.service import TransferJob, TransferQueue


# ── File panel ──────────────────────────────────────────────────────────────
def _local_drives() -> list[str]:
    if not hasattr(os, "listdrives"):
        return []
    try:
        return sorted(os.listdrives())
    except OSError:
        return []


def _breadcrumb_target(path: str, char_index: int) -> str | None:
    """Resolve a click inside an address path to the directory to jump to.

    Returns ``None`` when the click lands on the last component (i.e. a
    directory that is already the current one) or out of the path.
    """
    segments: list[tuple[str, int]] = []
    start = 0
    for j, char in enumerate(path):
        if char in "/\\":
            segments.append((path[start:j], j))
            start = j + 1
    segments.append((path[start:], len(path)))
    if not segments:
        return None
    index = max(0, min(char_index, len(path)))
    target_seg = len(segments) - 1
    for pos, (_, end_idx) in enumerate(segments):
        if index <= end_idx:
            target_seg = pos
            break
    if target_seg >= len(segments) - 1:
        return None
    name, end_idx = segments[target_seg]
    if name.endswith(":"):
        return path[: end_idx + 1]
    if not name and path and path[0] in "/\\":
        return path[0]
    return path[:end_idx]


class BreadcrumbLineEdit(QLineEdit):
    """Address field whose parent path segments are clickable (WinSCP style).

    The segment under the mouse gets a soft highlight so the user sees what a
    click would jump to.
    """

    segment_clicked = Signal(str)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._hover: tuple[str, int, int] | None = None
        self.setMouseTracking(True)

    def mousePressEvent(self, event: Any) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not event.modifiers()
            and not self.hasSelectedText()
        ):
            target = self._target_at(event.position().x())
            if target is not None:
                self.segment_clicked.emit(target)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        hover = self._hit_segment(event.position().x())
        if hover != self._hover:
            self._hover = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)
        if self._hover is None:
            return
        name, char_start, char_end = self._hover
        if not name:
            return
        text = self.text()
        metrics = self.fontMetrics()
        scroll_x = self.cursorRect().x() - metrics.horizontalAdvance(text[: self.cursorPosition()])
        x0 = scroll_x + metrics.horizontalAdvance(text[:char_start])
        x1 = scroll_x + metrics.horizontalAdvance(text[:char_end])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 120, 215, 55))
        painter.drawRoundedRect(
            QRectF(x0, 2, max(x1 - x0, 4), self.height() - 4),
            3,
            3,
        )
        painter.end()

    def _hit_segment(self, view_x: float) -> tuple[str, int, int] | None:
        """Return (name, char_start, char_end_exclusive) of the hovered segment."""
        text = self.text()
        if not text:
            return None
        metrics = self.fontMetrics()
        scroll_x = self.cursorRect().x() - metrics.horizontalAdvance(text[: self.cursorPosition()])
        index = len(text)
        for i in range(1, len(text) + 1):
            if view_x < scroll_x + metrics.horizontalAdvance(text[:i]):
                index = i - 1
                break
        segments: list[tuple[str, int, int]] = []
        start = 0
        for j, char in enumerate(text):
            if char in "/\\":
                segments.append((text[start:j], start, j + 1))
                start = j + 1
        segments.append((text[start:], start, len(text)))
        for name, char_start, char_end in segments:
            if char_start <= index < char_end:
                return (name, char_start, char_end)
        return None

    def _target_at(self, view_x: float) -> str | None:
        text = self.text()
        if not text:
            return None
        metrics = self.fontMetrics()
        position = self.cursorPosition()
        scroll_x = self.cursorRect().x() - metrics.horizontalAdvance(text[:position])
        index = len(text)
        for i in range(1, len(text) + 1):
            if view_x < scroll_x + metrics.horizontalAdvance(text[:i]):
                index = i - 1
                break
        return _breadcrumb_target(text, index)


class PanelView(QTreeView):
    """QTreeView that understands OS file drops and remote path drags."""

    files_dropped = Signal(list)
    remote_paths_dropped = Signal(list)
    focus_gained = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setUniformRowHeights(True)
        self.setAnimated(False)
        self.setRootIsDecorated(False)
        self.setAllColumnsShowFocus(True)

    def focusInEvent(self, event: Any) -> None:
        super().focusInEvent(event)
        self.focus_gained.emit()

    def _acceptable(self, mime: QMimeData) -> bool:
        return mime.hasFormat("text/uri-list") or mime.hasFormat(RFILES_MIME)

    def dragEnterEvent(self, event: Any) -> None:
        if self._acceptable(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: Any) -> None:
        if self._acceptable(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        mime = event.mimeData()
        local_files = (
            [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
            if mime.hasUrls()
            else []
        )
        if mime.hasFormat(RFILES_MIME):
            payload = bytes(mime.data(RFILES_MIME)).decode("utf-8", errors="replace")
            remote_paths = [row for row in payload.splitlines() if row]
            if remote_paths:
                self.remote_paths_dropped.emit(remote_paths)
        if local_files:
            self.files_dropped.emit(local_files)
        event.acceptProposedAction()


class FilePanel(QWidget):
    """Local or remote file browser with an address bar and basic controls."""

    path_changed = Signal(str)
    open_file_requested = Signal(str)
    context_menu = Signal(object)
    focus_gained = Signal()
    error_raised = Signal(str)
    files_dropped_into = Signal(str, object, list)
    remote_paths_dropped_into = Signal(str, object, list)

    def __init__(self, kind: str, title: str, parent: Any = None, **kwargs: Any) -> None:
        super().__init__(parent)
        self.kind = kind
        self._directory: str | None = None
        if kind == "local":
            self._model: Any = LocalFileModel(self)
        else:
            self._model = RemoteFileModel(
                list_dir=kwargs.get("list_dir"),
                executor=kwargs.get("executor"),
                parent=self,
            )
            self._model.listing_failed.connect(self.error_raised)
        self._view = PanelView(self)
        self._view.setModel(self._model)
        self._view.doubleClicked.connect(lambda index: self._activate_index(index))
        self._view.focus_gained.connect(self.focus_gained)
        self._view.files_dropped.connect(self._on_files_dropped)
        self._view.remote_paths_dropped.connect(self._on_remote_paths_dropped)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        header = self._view.header()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self._view.setSortingEnabled(True)
        self._apply_sort()
        self._restore_paths: list[str] = []
        if kind == "local":
            self._model.directoryLoaded.connect(lambda _path: self._apply_sort())
            self._model.directoryLoaded.connect(self._restore_selection)
        else:
            self._model.directory_loaded.connect(lambda _path: self._apply_sort())
            self._model.directory_loaded.connect(self._restore_selection)

        self._address = BreadcrumbLineEdit(self)
        self._address.setPlaceholderText("Путь к каталогу")
        self._address.returnPressed.connect(lambda: self.cd(self._address.text().strip()))
        self._address.segment_clicked.connect(self.cd)

        self._up = QPushButton(self)
        self._up.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self._up.setIconSize(QSize(18, 18))
        self._up.setFixedSize(28, 28)
        self._up.setToolTip("Родительский каталог")
        self._up.clicked.connect(self.go_up)
        self._refresh = QPushButton(self)
        self._refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self._refresh.setIconSize(QSize(18, 18))
        self._refresh.setFixedSize(28, 28)
        self._refresh.setToolTip("Обновить")
        self._refresh.clicked.connect(self.refresh)
        self._hidden = QCheckBox("Скрытые", self)
        self._hidden.toggled.connect(self.toggle_hidden)

        bar = QHBoxLayout()
        if kind == "local":
            drives = _local_drives()
            if drives:
                self._drives = QToolButton(self)
                self._drives.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
                self._drives.setIconSize(QSize(18, 18))
                self._drives.setFixedSize(28, 28)
                self._drives.setAutoRaise(True)
                self._drives.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                self._drives.setToolTip("Выбор диска")
                menu = QMenu(self)
                for drive in drives:
                    action = menu.addAction(drive)
                    action.setData(drive)
                self._drives.setMenu(menu)
                self._drives.triggered.connect(self._on_drive_selected)
                bar.addWidget(self._drives)
        bar.addWidget(self._up)
        bar.addWidget(self._address, 1)
        bar.addWidget(self._refresh)
        bar.addWidget(self._hidden)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self._view, 1)
        self._summary: QLabel | None
        if kind == "remote":
            self._summary = QLabel("", self)
            self._summary.setStyleSheet("color: #6f7780; padding: 1px 8px 3px;")
            layout.addWidget(self._summary)
            self._model.directory_loaded.connect(lambda _path: self._update_summary())
        else:
            self._summary = None

    # ── navigation ──────────────────────────────────────────
    def current_dir(self) -> str | None:
        return self._directory

    def cd(self, path: str) -> None:
        if not path:
            return
        self._directory = path
        if self.kind == "local":
            self._model.setRootPath(path)
            self._view.setRootIndex(self._model.index(path))
        else:
            self._model.cd(path)
        self._address.setText(path)
        self._view.header().setStretchLastSection(False)
        for col in range(self._model.columnCount()):
            self._view.header().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self._apply_sort()
        self.path_changed.emit(path)

    def go_up(self) -> None:
        directory = self._directory
        if not directory:
            return
        parent = parent_remote(directory) if self.kind == "remote" else str(Path(directory).parent)
        if parent and parent != directory:
            self.cd(parent)

    def refresh(self) -> None:
        if self.kind == "remote":
            self._restore_paths = self.selected_paths()
            self._model.refresh()
            return
        root = self._directory
        if not root:
            return
        self._restore_paths = self.selected_paths()
        self._model.setRootPath(root)
        self._view.setRootIndex(self._model.index(root))
        self._apply_sort()

    def _restore_selection(self, _path: object) -> None:
        """Restore the previously selected entries after a model reload.

        ``beginResetModel()`` invalidates every existing QModelIndex, so Qt
        clears the selection before the directory listing has been refetched
        (see RemoteFileModel.refresh).  We snapshot the selected *paths* on
        refresh() and, once the fresh listing lands here, re-select the rows
        that still exist.
        """
        paths, self._restore_paths = self._restore_paths, []
        if not paths or self._view.selectionModel() is None:
            return
        wanted = set(paths)
        model = self._model
        selection = QItemSelection()
        if self.kind == "local":
            root = model.index(self._directory or "")
            for row in range(model.rowCount(root)):
                if model.filePath(model.index(row, 0, root)) in wanted:
                    top = model.index(row, 0, root)
                    bottom = model.index(row, model.columnCount(root) - 1, root)
                    selection.select(top, bottom)
        else:
            for row in range(model.rowCount()):
                info = model.entry(row)
                if info is not None and str(info.path) in wanted:
                    top = model.index(row, 0)
                    bottom = model.index(row, model.columnCount() - 1)
                    selection.select(top, bottom)
        if selection.indexes():
            self._view.selectionModel().select(
                selection,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )

    def _apply_sort(self) -> None:
        section = self._view.header().sortIndicatorSection()
        if section >= 0:
            self._view.sortByColumn(section, self._view.header().sortIndicatorOrder())

    def toggle_hidden(self, show: bool) -> None:
        if self.kind == "local":
            self._model.toggle_hidden(show)
        else:
            self._model.toggle_hidden(show)

    def _on_drive_selected(self, action: Any) -> None:
        self.cd(str(action.data()))

    # ── selection ───────────────────────────────────────────
    def selected_paths(self) -> list[str]:
        indexes = self._view.selectionModel().selectedRows()
        if self.kind == "local":
            return [self._model.filePath(index) for index in indexes if index.isValid()]
        return [str(self._model.entry(index.row()).path) for index in indexes if index.isValid()]

    def selected_count(self) -> int:
        return len(self._view.selectionModel().selectedRows())

    def focus(self) -> None:
        self._view.setFocus()

    # ── events ──────────────────────────────────────────────
    def _row_info(self, index: Any) -> Any:
        if self.kind == "local":
            path = self._model.filePath(index)
            return None if not path else ("dir" if Path(path).is_dir() else "file")
        info = self._model.entry(index.row())
        return None if info is None else ("dir" if info.is_dir else "file")

    def _activate_index(self, index: Any) -> None:
        if not index.isValid():
            return
        if self.kind == "local":
            path = self._model.filePath(index)
            if not path:
                return
            if Path(path).is_dir():
                self.cd(path)
            else:
                self.open_file_requested.emit(path)
            return
        info = self._model.entry(index.row())
        if info is None:
            return
        if info.is_dir:
            self.cd(info.path)
        else:
            self.open_file_requested.emit(info.path)

    def _on_files_dropped(self, local_files: list[str]) -> None:
        self.focus_gained.emit()
        self.files_dropped_into.emit(self.kind, self.current_dir(), local_files)

    def _on_remote_paths_dropped(self, remote_paths: list[str]) -> None:
        self.focus_gained.emit()
        self.remote_paths_dropped_into.emit(self.kind, self.current_dir(), remote_paths)

    def _on_context_menu(self, position: Any) -> None:
        self.context_menu.emit(self._view.viewport().mapToGlobal(position))

    def _update_summary(self) -> None:
        if self._summary is None:
            return
        files = [entry for entry in self._model.entries() if not entry.is_dir]
        size = sum(entry.size for entry in files if entry.size is not None)
        if files:
            self._summary.setText(f"Файлов: {len(files)}  •  Объём: {_bytes(size)}")
        else:
            self._summary.setText("Файлов нет")


# ── Transfer side panel ─────────────────────────────────────────────────────
_COLUMNS = ("Операция", "Источник", "Назначение", "Статус", "Прогресс", "Ошибка")

_OPERATION_RU = {
    "upload": "Загрузка",
    "download": "Скачивание",
    "delete": "Удаление",
    "copy": "Копирование",
}

_STATUS_RU = {
    "waiting": "В ожидании",
    "running": "Выполняется",
    "completed": "Готово",
    "failed": "Ошибка",
    "cancelled": "Отменено",
}

_FINISHED = {
    TransferStatus.COMPLETED,
    TransferStatus.FAILED,
    TransferStatus.CANCELLED,
}


class TransferWidget(QWidget):
    """Renders jobs to a flat table; mutations are marshalled via the relay."""

    def __init__(self, queue: TransferQueue, relay: Any, parent: Any = None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._items: dict[str, QTreeWidgetItem] = {}
        relay.changed.connect(self.on_updated)

        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(len(_COLUMNS))
        self._tree.setHeaderLabels(list(_COLUMNS))
        self._tree.setRootIsDecorated(False)
        self._tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setStretchLastSection(False)

        self._cancel_btn = QPushButton("Отменить", self)
        self._cancel_btn.clicked.connect(self._cancel_selected)
        self._retry_btn = QPushButton("Повторить", self)
        self._retry_btn.clicked.connect(self._retry_selected)
        self._clear_btn = QPushButton("Очистить завершённые", self)
        self._clear_btn.clicked.connect(self._clear_finished)

        buttons = QHBoxLayout()
        buttons.addWidget(self._cancel_btn)
        buttons.addWidget(self._retry_btn)
        buttons.addWidget(self._clear_btn)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree, 1)
        layout.addLayout(buttons)

    def on_updated(self, job: TransferJob) -> None:
        item = self._items.get(job.job_id)
        if item is None:
            item = QTreeWidgetItem(self._tree)
            item.setData(0, 256, job.job_id)
            self._items[job.job_id] = item
            self._tree.addTopLevelItem(item)
        progress = job.progress
        percent = ""
        if progress.total_size and progress.total_size > 0 and progress.total_transferred_bytes:
            percent = f"{int(progress.total_transferred_bytes * 100 / progress.total_size)}% "
        item.setText(0, _OPERATION_RU.get(progress.operation, progress.operation))
        item.setText(1, progress.source)
        item.setText(2, progress.destination)
        item.setText(3, _STATUS_RU.get(progress.status.value, progress.status.value))
        item.setText(4, percent + _bytes(progress.total_transferred_bytes) + " / " + _bytes(progress.total_size))
        item.setText(5, progress.error or "")

    def _selected_job_id(self) -> str | None:
        current = self._tree.currentItem()
        if current is None:
            return None
        return current.data(0, 256)

    def _cancel_selected(self) -> None:
        job_id = self._selected_job_id()
        if job_id:
            self._queue.cancel(job_id)

    def _retry_selected(self) -> None:
        job_id = self._selected_job_id()
        if job_id:
            self._queue.retry(job_id)

    def _clear_finished(self) -> None:
        for job in list(self._queue.jobs()):
            if job.progress.status in _FINISHED:
                self._queue.remove_job(job.job_id)
                item = self._items.pop(job.job_id, None)
                if item is not None:
                    self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(item))

    def count(self) -> int:
        return self._tree.topLevelItemCount()


def _bytes(value: int | None) -> str:
    if value is None:
        return "?"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(value) < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


# ── Log console ─────────────────────────────────────────────────────────────
LOGGER_NAME = "cashcontrol.builtin.file_manager"
RING_SIZE = 800
MAX_BLOCKS = 12_000
TRIM_BLOCKS = 2_000

_LOG_PATH: Any = None


def log_file_path() -> Any:
    """Path of the rotating log file captured by the log console."""
    global _LOG_PATH
    if _LOG_PATH is None:
        directory = default_config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        _LOG_PATH = directory / "cashcontrol.builtin.file_manager.log"
    return _LOG_PATH


def _format_record(record: logging.LogRecord) -> str:
    time = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
    origin = f"{record.name}.{record.funcName}:{record.lineno}"
    message = record.getMessage()
    if record.exc_info:
        message += "\n" + "".join(logging.Formatter().formatException(record.exc_info))
    return f"{time} {record.levelname:<7} {origin:<34} {message}"


class _BusHandler(logging.Handler):
    """Collects records into a thread-safe ring and forwards them to Qt."""

    def __init__(self, ring: deque[str], emit: Any) -> None:
        super().__init__(level=logging.NOTSET)
        self._ring = ring
        self._emit = emit
        self._lock = threading.Lock()
        self._file: Any = None

    def emit(self, record: logging.LogRecord) -> None:
        line = _format_record(record)
        with self._lock:
            self._ring.append(line)
            # файл открывается один раз и держится открытым (не на каждое сообщение)
            if self._file is None:
                self._file = log_file_path().open("a", encoding="utf-8")
            self._file.write(line + "\n")
            self._file.flush()
        with contextlib.suppress(RuntimeError):
            self._emit(line)

    def flush(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.flush()

    def close_file(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


class LogConsole(QObject):
    """Owns the ring buffer and the logging handler; lives on the GUI thread."""

    new_record = Signal(str)

    def __init__(self, parent: QObject | None = None, *, debug: bool = False) -> None:
        super().__init__(parent)
        self._ring: deque[str] = deque(maxlen=RING_SIZE)
        self._handler = _BusHandler(self._ring, self.new_record.emit)
        self.destroyed.connect(self._detach_handler)
        self.install(debug=debug)

    def _detach_handler(self, _: Any = None) -> None:
        """Remove the handler from loggers so records stop reaching a dead signal."""
        for name in (LOGGER_NAME, "asyncssh"):
            logging.getLogger(name).removeHandler(self._handler)
        self._handler.close_file()

    def install(self, *, debug: bool) -> None:
        for name in (LOGGER_NAME, "asyncssh"):
            logger = logging.getLogger(name)
            logger.addHandler(self._handler)
            logger.setLevel(logging.DEBUG if debug else logging.INFO)
            logger.propagate = False

    def set_debug(self, enabled: bool) -> None:
        level = logging.DEBUG if enabled else logging.INFO
        for name in (LOGGER_NAME, "asyncssh"):
            logging.getLogger(name).setLevel(level)

    def tail(self, limit: int = 120) -> list[str]:
        with self._handler._lock:
            return list(self._ring)[-limit:]


class LogPanel(QWidget):
    """Read-only scrolling log view with copy/clear controls."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._view = QPlainTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(MAX_BLOCKS)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._view.setFont(font)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        copy_btn = QPushButton("Копировать в буфер", self)
        copy_btn.clicked.connect(self.copy_all)
        clear_btn = QPushButton("Очистить", self)
        clear_btn.clicked.connect(self._view.clear)
        path_label = QLabel(f"Файл журнала: {log_file_path()}", self)
        path_label.setToolTip(str(log_file_path()))

        buttons = QHBoxLayout()
        buttons.addWidget(copy_btn)
        buttons.addWidget(clear_btn)
        buttons.addWidget(path_label, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view, 1)
        layout.addLayout(buttons)

    def append(self, line: str) -> None:
        self._view.appendPlainText(line)
        if self._view.blockCount() >= MAX_BLOCKS:
            cursor = self._view.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveOperation.KeepAnchor, TRIM_BLOCKS)
            cursor.removeSelectedText()

    def copy_all(self) -> None:
        # QPlainTextEdit.copy() копирует только выделенный фрагмент; без
        # выделения в буфер попадает пустая строка — выделяем весь лог.
        self._view.selectAll()
        self._view.copy()

    def scroll_to_bottom(self) -> None:
        self._view.moveCursor(self._view.textCursor().MoveOperation.End)


__all__ = [
    "LOGGER_NAME",
    "BreadcrumbLineEdit",
    "FilePanel",
    "LogConsole",
    "LogPanel",
    "PanelView",
    "TransferWidget",
    "log_file_path",
]
