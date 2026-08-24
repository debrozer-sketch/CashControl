"""
Logs Viewer Dialog — просмотр журналов приложения.

Возможности:
- Две вкладки: Основной лог / Журнал действий (audit)
- Выбор файла по дате из выпадающего списка
- Фильтр по уровню (DEBUG / INFO / WARNING / ERROR)
- Поиск по тексту (Ctrl+F)
- Цветовая подсветка строк по уровню
- Автопрокрутка вниз при открытии
- Кнопка «Обновить» (перечитать файл)
- Кнопка «Открыть папку» (открыть logs/ в проводнике)
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon,
    LineEdit,
    PushButton,
    SubtitleLabel,
)

from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_logs_dir

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger()

# ── Цвета подсветки уровней (токены темы) ──────────────────────────────────
_LEVEL_TOKENS: dict[str, str] = {
    "DEBUG": "text_tertiary", "INFO": "text_code", "SUCCESS": "success",
    "WARNING": "warning", "ERROR": "error", "CRITICAL": "error", "AUDIT": "info",
}

_LEVEL_BG_TOKENS: dict[str, str] = {
    "WARNING": "bg_warning", "ERROR": "bg_danger", "CRITICAL": "bg_danger",
}

# Regex для парсинга строки лога
_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,]\d+)"   # timestamp
    r"\s*\|\s*"
    r"(\w+)"                                             # level
    r"\s*\|.*$"
)

_AUDIT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,]\d+)"
    r"\s*\|\s*(?:AUDIT\s*\|\s*)?"
    r"(.+)$"
)


class _LogPanel(QWidget):
    """Single log viewer panel (one log type)."""

    def __init__(
        self,
        file_pattern: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pattern = file_pattern   # e.g. "cashcontrol_*.log"
        self._logs_dir = get_logs_dir()
        self._current_file: Path | None = None
        self._init_ui()
        self._refresh_file_list()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        # File selector
        toolbar.addWidget(BodyLabel("Файл:", self))
        self._file_combo = ComboBox(self)
        self._file_combo.setMinimumWidth(200)
        self._file_combo.currentIndexChanged.connect(self._on_file_changed)
        toolbar.addWidget(self._file_combo)

        # Level filter
        toolbar.addWidget(BodyLabel("Уровень:", self))
        self._level_combo = ComboBox(self)
        self._level_combo.addItems(["Все", "DEBUG", "INFO", "WARNING", "ERROR"])
        self._level_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self._level_combo)

        # Search
        self._search_edit = LineEdit(self)
        self._search_edit.setPlaceholderText("Поиск")
        self._search_edit.setMaximumWidth(200)
        self._search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search_edit)

        # Refresh
        self._refresh_btn = PushButton("Обновить", self, FluentIcon.SYNC)
        self._refresh_btn.clicked.connect(self._load_current_file)
        toolbar.addWidget(self._refresh_btn)

        # Open folder
        self._folder_btn = PushButton("Папка", self, FluentIcon.FOLDER)
        self._folder_btn.clicked.connect(self._open_folder)
        toolbar.addWidget(self._folder_btn)

        toolbar.addStretch()

        # Line count label
        self._count_label = BodyLabel("", self)
        self._count_label.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        toolbar.addWidget(self._count_label)

        layout.addLayout(toolbar)

        # ── Log text area ────────────────────────────────────────────────────
        self._text = QPlainTextEdit(self)
        self._text.setObjectName("MonoPanel")
        from cashcontrol.gui.theme_helper import set_visual_role

        set_visual_role(self._text, "logViewer")
        self._text.setReadOnly(True)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._text.setFont(font)
        self._text.setStyleSheet(
            "QPlainTextEdit {"
            f"  background: {_tc('bg_code')};"
            f"  color: {_tc('text_code')};"
            f"  border: 1px solid {_tc('border_primary')};"
            "  border-radius: 4px;"
            "}"
        )
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._text, stretch=1)

    # ── File management ───────────────────────────────────────────────────────

    def _refresh_file_list(self) -> None:
        """Reload list of log files matching pattern."""
        files = sorted(self._logs_dir.glob(self._pattern), reverse=True)
        self._file_combo.blockSignals(True)
        self._file_combo.clear()
        for f in files:
            self._file_combo.addItem(f.name, f)
        self._file_combo.blockSignals(False)

        if files:
            self._file_combo.setCurrentIndex(0)
            self._load_file(files[0])
        else:
            self._text.setPlainText("Лог-файлы не найдены.")

    def _on_file_changed(self, index: int) -> None:
        path = self._file_combo.itemData(index)
        if path:
            self._load_file(path)

    def _load_file(self, path: Path) -> None:
        self._current_file = path
        self._load_current_file()

    def _load_current_file(self) -> None:
        if not self._current_file or not self._current_file.exists():
            self._text.setPlainText("Файл не найден.")
            return
        try:
            content = self._current_file.read_text(encoding="utf-8", errors="replace")
            self._all_lines = content.splitlines()
            self._apply_filter()
        except Exception as e:
            self._text.setPlainText(f"Ошибка чтения файла:\n{e}")

    # ── Filtering & rendering ────────────────────────────────────────────────

    def _apply_filter(self) -> None:
        level_filter = self._level_combo.currentText()
        search_text  = self._search_edit.text().lower()

        _level_order = {"DEBUG": 0, "INFO": 1, "SUCCESS": 1,
                        "WARNING": 2, "ERROR": 3, "CRITICAL": 3, "AUDIT": 1}
        min_order = _level_order.get(level_filter, -1)

        visible_lines: list[str] = []
        for line in getattr(self, "_all_lines", []):
            # Level filter
            if level_filter != "Все":
                m = _LOG_RE.match(line) or _AUDIT_RE.match(line)
                if m:
                    lvl = m.group(2) if _LOG_RE.match(line) else "AUDIT"
                    if _level_order.get(lvl, 0) < min_order:
                        continue
                else:
                    if min_order > 1:  # hide unknown lines for WARNING/ERROR
                        continue
            # Search filter
            if search_text and search_text not in line.lower():
                continue
            visible_lines.append(line)

        self._render_lines(visible_lines, search_text)
        self._count_label.setText(f"{len(visible_lines)} строк")

    def _render_lines(self, lines: list[str], highlight: str = "") -> None:
        """Render lines with color-coding by level."""
        self._text.clear()
        cursor = self._text.textCursor()

        base_fmt = QTextCharFormat()
        base_fmt.setForeground(QColor(_tc("text_code")))

        for line in lines:
            # Determine level for this line
            level = "INFO"
            m = _LOG_RE.match(line)
            if m:
                level = m.group(2).strip()
            elif "AUDIT" in line:
                level = "AUDIT"

            fmt = QTextCharFormat()
            fmt.setForeground(QColor(_tc(_LEVEL_TOKENS.get(level, "text_code"))))
            bg_token = _LEVEL_BG_TOKENS.get(level)
            if bg_token:
                fmt.setBackground(QColor(_tc(bg_token)))

            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(line + "\n", fmt)

        # Highlight search term
        if highlight:
            hl_fmt = QTextCharFormat()
            hl_fmt.setBackground(QColor(_tc("accent")))
            hl_fmt.setForeground(QColor(_tc("text_on_accent")))

            doc = self._text.document()
            cursor = QTextCursor(doc)
            while True:
                cursor = doc.find(highlight, cursor,
                                  doc.FindFlag(0))  # case-insensitive not available simply
                if cursor.isNull():
                    break
                cursor.mergeCharFormat(hl_fmt)

        # Scroll to bottom
        self._text.moveCursor(QTextCursor.MoveOperation.End)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _open_folder(self) -> None:
        path = str(self._logs_dir)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def refresh(self) -> None:
        """Public method — refresh file list and reload current file."""
        self._refresh_file_list()


# ── Main Dialog ───────────────────────────────────────────────────────────────

class LogsViewerDialog(QDialog):
    """
    Log viewer dialog with two tabs:
    - Main log (cashcontrol_*.log) — all messages
    - Audit log (audit_*.log)      — security/action events
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Журнал действий")
        self.setMinimumSize(920, 600)
        self.resize(1050, 680)
        self.setWindowModality(Qt.WindowModality.NonModal)  # non-blocking
        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        root.addWidget(SubtitleLabel("Журнал действий", self))

        # Tabs
        self._tabs = QTabWidget(self)

        self._main_panel = _LogPanel("app_*.log", self)
        self._tabs.addTab(self._main_panel, "Основной лог")

        self._audit_panel = _LogPanel("audit*.log", self)
        self._tabs.addTab(self._audit_panel, "Журнал действий")

        root.addWidget(self._tabs, stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        refresh_all = PushButton("Обновить всё", self, FluentIcon.SYNC)
        refresh_all.clicked.connect(self._refresh_all)
        btn_row.addWidget(refresh_all)

        close_btn = PushButton("Закрыть", self)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _refresh_all(self) -> None:
        self._main_panel.refresh()
        self._audit_panel.refresh()
