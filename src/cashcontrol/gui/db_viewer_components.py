"""
db_viewer_components.py — shared components for the PostgreSQL editor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import contextlib

from PySide6.QtCore import QStringListModel, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QCompleter, QPlainTextEdit

from cashcontrol.infrastructure.audit_logger import get_logger

logger = get_logger()


# ── psycopg2 ──────────────────────────────────────────────────────────────────

try:
    import psycopg2
    from psycopg2 import Error as PsycopgError
    from psycopg2 import sql as pgsql
    _PSYCOPG2_OK = True
except ImportError:
    psycopg2 = None  # type: ignore
    pgsql = None     # type: ignore
    PsycopgError = Exception
    _PSYCOPG2_OK = False


# ── colors ────────────────────────────────────────────────────────────────────


def _get_colors():
    try:
        from qfluentwidgets import isDarkTheme
        dark = isDarkTheme()
    except Exception:
        dark = False

    class _Colors:
        if dark:
            PRIMARY   = "#4BA3E6"
            PRIMARY_H = "#3A8AD4"
            ACCENT    = "#2979C2"
            BG        = "#202020"
            SURFACE   = "#2b2b2b"
            BORDER    = "#3f3f3f"
            TEXT      = "#e0e0e0"
            TEXT_MUTE = "#888888"
            MODIFIED  = "#3d3000"
            MOD_BDR   = "#FFB300"
            ERROR_BG  = "#3d0a0a"
            SUCCESS   = "#66bb6a"
            DANGER    = "#ef5350"
            HDR_BG    = "#333333"
            HDR_TEXT  = "#e0e0e0"
            DISABLED_BG = "#444444"
            DISABLED_FG = "#888888"
            FLAT_HOVER  = "#3d3d3d"
            TAB_BG      = "#333333"
            DANGER_BTN  = "#c62828"
            DANGER_HOVER = "#a31515"
        else:
            PRIMARY   = "#1565C0"
            PRIMARY_H = "#0D47A1"
            ACCENT    = "#42A5F5"
            BG        = "#F4F6F9"
            SURFACE   = "#FFFFFF"
            BORDER    = "#DDE1E8"
            TEXT      = "#1A1A2E"
            TEXT_MUTE = "#7A8499"
            MODIFIED  = "#FFF8E1"
            MOD_BDR   = "#FFB300"
            ERROR_BG  = "#FFEBEE"
            SUCCESS   = "#2E7D32"
            DANGER    = "#C62828"
            HDR_BG    = "#1565C0"
            HDR_TEXT  = "#FFFFFF"
            DISABLED_BG = "#B0B8C8"
            DISABLED_FG = "#ffffff"
            FLAT_HOVER  = "#E8EDF5"
            TAB_BG      = "#E4EAF5"
            DANGER_BTN  = "#D32F2F"
            DANGER_HOVER = "#B71C1C"
    return _Colors


_C = _get_colors()


def _build_style() -> str:
    C = _get_colors()
    return f"""
QWidget {{
    background-color: {C.BG};
    color: {C.TEXT};
    font-family: 'Segoe UI', 'Arial', sans-serif;
    font-size: 13px;
}}
QTreeWidget, QTableWidget, QPlainTextEdit, QTextEdit, QLineEdit {{
    background-color: {C.SURFACE};
    border: 1px solid {C.BORDER};
    border-radius: 4px;
}}
QTreeWidget::item:selected, QTableWidget::item:selected {{
    background-color: {C.ACCENT};
    color: white;
}}
QPushButton {{
    background-color: {C.PRIMARY};
    color: white;
    border: none;
    padding: 5px 14px;
    border-radius: 4px;
    font-weight: 600;
    min-height: 26px;
}}
QPushButton:hover   {{ background-color: {C.PRIMARY_H}; }}
QPushButton:disabled {{ background-color: {C.DISABLED_BG}; color: {C.DISABLED_FG}; }}
QPushButton#danger {{
    background-color: {C.DANGER_BTN};
}}
QPushButton#danger:hover {{ background-color: {C.DANGER_HOVER}; }}
QPushButton#flat {{
    background-color: transparent;
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
}}
QPushButton#flat:hover {{ background-color: {C.FLAT_HOVER}; }}
QComboBox {{
    padding: 4px 8px;
    border: 1px solid {C.BORDER};
    border-radius: 4px;
    background-color: {C.SURFACE};
    min-height: 24px;
}}
QComboBox::drop-down {{ border: none; }}
QHeaderView::section {{
    background-color: {C.HDR_BG};
    color: {C.HDR_TEXT};
    padding: 5px 8px;
    border: none;
    font-weight: 600;
    font-size: 12px;
}}
QTabWidget::pane {{
    border: 1px solid {C.BORDER};
    border-radius: 4px;
    background: {C.SURFACE};
}}
QTabBar::tab {{
    background: {C.TAB_BG};
    color: {C.TEXT};
    padding: 6px 16px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {C.SURFACE};
    color: {C.PRIMARY};
    font-weight: 700;
    border-bottom: 2px solid {C.PRIMARY};
}}
QSplitter::handle {{
    background: {C.BORDER};
    width: 2px;
}}
QLabel#status {{
    color: white;
    padding: 2px 8px;
    background: transparent;
    font-size: 12px;
}}
"""


# ── SQL highlighting ──────────────────────────────────────────────────────────


class SQLHighlighter(QSyntaxHighlighter):
    KEYWORDS = {
        'SELECT','FROM','WHERE','AND','OR','NOT','IN','LIKE','ILIKE',
        'INSERT','INTO','VALUES','UPDATE','SET','DELETE','DROP','CREATE',
        'TABLE','DATABASE','INDEX','VIEW','SCHEMA','ALTER','ADD','COLUMN',
        'PRIMARY','KEY','FOREIGN','REFERENCES','CONSTRAINT','UNIQUE',
        'NULL','DEFAULT','CASCADE','JOIN','LEFT','RIGHT','INNER','OUTER',
        'ON','AS','DISTINCT','ORDER','BY','ASC','DESC','LIMIT','OFFSET',
        'GROUP','HAVING','UNION','EXISTS','CASE','WHEN','THEN','ELSE','END',
        'BEGIN','COMMIT','ROLLBACK','TRUNCATE','WITH','RETURNING',
    }
    DANGER = {'DROP','DELETE','TRUNCATE'}

    def __init__(self, doc: QTextDocument) -> None:
        super().__init__(doc)
        C = _get_colors()

        try:
            from cashcontrol.gui.theme_helper import color as _tc
            warning_color = _tc('warning')
        except Exception:
            warning_color = C.MOD_BDR

        self._kw = QTextCharFormat()
        self._kw.setForeground(QColor(C.PRIMARY))
        self._kw.setFontWeight(QFont.Weight.Bold)

        self._danger = QTextCharFormat()
        self._danger.setForeground(QColor(C.DANGER_BTN))
        self._danger.setFontWeight(QFont.Weight.Bold)

        self._str = QTextCharFormat()
        self._str.setForeground(QColor(C.SUCCESS))

        self._num = QTextCharFormat()
        self._num.setForeground(QColor(warning_color))

        self._cmt = QTextCharFormat()
        self._cmt.setForeground(QColor(C.TEXT_MUTE))
        self._cmt.setFontItalic(True)

    def highlightBlock(self, text: str) -> None:
        for word in self.KEYWORDS:
            fmt = self._danger if word in self.DANGER else self._kw
            for m in re.finditer(rf'\b{word}\b', text, re.IGNORECASE):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        for m in re.finditer(r"'[^']*'", text):
            self.setFormat(m.start(), m.end() - m.start(), self._str)
        for m in re.finditer(r'\b\d+\.?\d*\b', text):
            self.setFormat(m.start(), m.end() - m.start(), self._num)
        for m in re.finditer(r'--.*$', text):
            self.setFormat(m.start(), m.end() - m.start(), self._cmt)


# ── SQL autocomplete ──────────────────────────────────────────────────────────


class SQLCompleter(QCompleter):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.tables_dict: dict[str, list[str]] = {}
        self.all_keywords = [
            "SELECT","FROM","WHERE","JOIN","UPDATE","DELETE",
            "INSERT","INTO","VALUES","ORDER BY","LIMIT","AND","OR","AS",
        ]
        self._model = QStringListModel()
        self.setModel(self._model)
        self._update([])

    def _update(self, items: list[str]) -> None:
        self._model.setStringList(sorted(items))

    def load_schema(self, tables_dict: dict[str, list[str]]) -> None:
        self.tables_dict = tables_dict
        all_items: set = set(self.all_keywords)
        for tbl, cols in tables_dict.items():
            all_items.add(tbl)
            all_items.update(cols)
        self._update(list(all_items))


# ── SQL code editor ──────────────────────────────────────────────────────────


class SQLCodeEditor(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._comp: SQLCompleter | None = None

    def set_completer(self, c: SQLCompleter) -> None:
        self._comp = c
        c.setWidget(self)
        c.activated.connect(self._insert)

    def _insert(self, text: str) -> None:
        if self._comp and self._comp.widget() is self:
            tc = self.textCursor()
            extra = len(text) - len(self._comp.completionPrefix())
            tc.movePosition(QTextCursor.MoveOperation.Left)
            tc.movePosition(QTextCursor.MoveOperation.EndOfWord)
            tc.insertText(text[-extra:])
            self.setTextCursor(tc)

    def keyPressEvent(self, e) -> None:
        if self._comp and self._comp.popup().isVisible():
            if e.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return,
                           Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                e.ignore()
                return
        is_shortcut = (e.modifiers() & Qt.KeyboardModifier.ControlModifier and
                       e.key() == Qt.Key.Key_Space)
        if not is_shortcut:
            super().keyPressEvent(e)
        if not self._comp:
            return
        prefix = self._word_under_cursor()
        self._comp.setCompletionPrefix(prefix)
        popup = self._comp.popup()
        popup.setCurrentIndex(self._comp.completionModel().index(0, 0))
        cr = self.cursorRect()
        cr.setWidth(popup.sizeHintForColumn(0) +
                    popup.verticalScrollBar().sizeHint().width())
        self._comp.complete(cr)

    def _word_under_cursor(self) -> str:
        tc = self.textCursor()
        tc.select(QTextCursor.SelectionType.WordUnderCursor)
        return tc.selectedText()


# ── Query worker ──────────────────────────────────────────────────────────────


class QueryWorker(QThread):
    finished = Signal(object, list, float)
    error    = Signal(str)

    def __init__(self, conn_params: dict, query: str,
                 params: tuple | None = None, fetch: bool = True) -> None:
        super().__init__()
        self._params  = conn_params
        self._query   = query
        self._qparams = params
        self._fetch   = fetch
        self._cancelled = False

    def run(self) -> None:
        conn = None
        t0 = datetime.now()
        try:
            conn = psycopg2.connect(**self._params, connect_timeout=5)
            if self._cancelled:
                return
            with conn.cursor() as cur:
                if self._qparams:
                    cur.execute(self._query, self._qparams)
                else:
                    cur.execute(self._query)
                elapsed = (datetime.now() - t0).total_seconds()
                if self._fetch and cur.description:
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                    self.finished.emit(rows, cols, elapsed)
                else:
                    conn.commit()
                    self.finished.emit(cur.rowcount, [], elapsed)
        except PsycopgError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()

    def cancel(self) -> None:
        self._cancelled = True


# ── Cell change data ──────────────────────────────────────────────────────────


@dataclass
class CellChange:
    row: int
    column: int
    column_name: str
    old_value: Any
    new_value: Any
    primary_key: dict[str, Any]
