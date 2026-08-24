"""
theme_engine.py — singleton, единственная точка управления темой.

Usage:
    ThemeEngine.instance().apply("dark")

Подписка на смену темы:
    ThemeEngine.instance().theme_changed.connect(my_slot)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor

if TYPE_CHECKING:
    from collections.abc import Callable


CORE_QSS = """
/* ===== ROOT / APP ===== */
QMainWindow, QDialog, QWidget#appRoot {
    background-color: @bg.app;
    color: @text.primary;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}

QToolTip {
    background-color: @bg.overlay;
    color: @text.primary;
    border: 1px solid @border.subtle;
    padding: 6px 8px;
    border-radius: 4px;
    font-size: 12px;
}

/* ===== SIDEBAR ===== */
QWidget#sidebar {
    background-color: @bg.sidebar;
    border-right: 1px solid @border.subtle;
    min-width: 56px;
    max-width: 56px;
}
QToolButton#sidebarBtn {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 10px;
    margin: 4px 8px;
    color: @text.secondary;
}
QToolButton#sidebarBtn:hover {
    background: @bg.hover;
    color: @text.primary;
}
QToolButton#sidebarBtn:pressed {
    background: @bg.pressed;
}
QToolButton#sidebarBtn[checked="true"],
QToolButton#sidebarBtn:checked {
    background: @accent.muted;
    color: @accent.default;
}
QLabel#appVersion {
    color: @text.tertiary;
    font-size: 11px;
    qproperty-alignment: AlignCenter;
    padding: 8px 4px;
}

/* ===== TAB BAR ===== */
QWidget#tabBar {
    background: @bg.surface;
    border-bottom: 1px solid @border.subtle;
    min-height: 36px;
}
QToolButton#cashTab {
    background: @bg.tab;
    color: @text.secondary;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 10px;
    margin: 4px 2px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    font-weight: 600;
    min-width: 128px;
    max-width: 180px;
}
QToolButton#cashTab:hover {
    background: @bg.hover;
    color: @text.primary;
}
QToolButton#cashTab[active="true"] {
    background: @bg.tab.active;
    color: @text.primary;
    border-bottom: 2px solid @accent.default;
}
QToolButton#tabAddBtn {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px;
    color: @text.secondary;
    margin: 4px;
}
QToolButton#tabAddBtn:hover {
    background: @bg.hover;
    color: @text.primary;
}
/* ping dot via property on child QLabel */
QLabel#pingDot[ping="ok"]      { background: @semantic.ok; border-radius: 4px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }
QLabel#pingDot[ping="slow"]    { background: @semantic.slow; border-radius: 4px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }
QLabel#pingDot[ping="timeout"] { background: @semantic.err; border-radius: 4px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }
QLabel#pingDot[ping="unknown"]{ background: @semantic.unknown; border-radius: 4px; min-width: 8px; max-width: 8px; min-height: 8px; max-height: 8px; }

/* ===== TOOLBAR ===== */
QWidget#actionToolbar {
    background: @bg.surface;
    border-bottom: 1px solid @border.subtle;
    min-height: 64px;
    padding: 4px 8px;
}
QToolButton#actionBtn {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 8px;
    color: @text.primary;
    font-size: 11px;
    min-width: 64px;
    min-height: 52px;
}
QToolButton#actionBtn:hover { background: @bg.hover; }
QToolButton#actionBtn:pressed { background: @bg.pressed; }
QToolButton#actionBtn:disabled { color: @text.tertiary; }
QToolButton#actionBtn[danger="true"] { color: @danger.btn; }
QToolButton#actionBtn[danger="true"]:hover {
    background: @semantic.err.muted;
    color: @danger.btn.hover;
}
QFrame#toolbarSep {
    background: @border.subtle;
    max-width: 1px;
    margin: 12px 6px;
}

/* ===== SPLITTER / VNC ===== */
QSplitter#mainSplitter::handle {
    background: @border.subtle;
    width: 1px;
    margin: 0;
}
QSplitter#mainSplitter::handle:hover { background: @accent.default; }

QWidget#vncPanel { background: @bg.sunken; }
QWidget#vncLetterbox { background: @vnc.letterbox; }
QWidget#vncEmptyState { background: @bg.sunken; }
QLabel#vncEmptyTitle { color: @text.secondary; font-size: 13px; }
QLabel#vncErrorText { color: @semantic.err; font-size: 12px; }
QWidget#vncControls {
    background: @bg.surface2;
    border-top: 1px solid @border.subtle;
    min-height: 36px;
}

/* ===== INFO CARDS ===== */
QScrollArea#infoScroll {
    background: @bg.app;
    border: none;
}
QWidget#infoScrollContent { background: @bg.app; }

QFrame#infoCard {
    background: @bg.surface2;
    border: 1px solid @border.subtle;
    border-radius: 8px;
    padding: 12px 14px;
}
QFrame#infoCard[state="error"] {
    border-left: 3px solid @semantic.err;
}
QFrame#infoCard[state="timeout"] {
    border-left: 3px solid @semantic.slow;
}
QFrame#infoCard[state="loading"] {
    border-left: 3px solid @border.strong;
}
QLabel#cardTitle {
    color: @text.secondary;
    font-size: 12px;
    font-weight: 600;
    padding-bottom: 8px;
}
QLabel#cardKey {
    color: @data.key;
    font-size: 12px;
    font-family: "Segoe UI", sans-serif;
}
QLabel#cardValue {
    color: @data.mono;
    font-size: 12px;
    font-family: "Cascadia Mono", "Consolas", monospace;
}
QFrame#problemRow {
    border-radius: 4px;
    padding: 8px 10px;
    margin: 3px 0;
}
QFrame#problemRow[severity="error"] {
    background: @semantic.err.muted;
    border-left: 3px solid @semantic.err;
}
QFrame#problemRow[severity="warning"] {
    background: @semantic.slow.muted;
    border-left: 3px solid @semantic.slow;
}
QLabel#skeletonBar {
    background: @bg.hover;
    border-radius: 4px;
    min-height: 10px;
    max-height: 10px;
}

/* ===== STATUS BAR ===== */
QWidget#statusBar {
    background: @bg.surface;
    border-top: 1px solid @border.subtle;
    min-height: 28px;
}
QLabel#statusText {
    color: @text.secondary;
    font-size: 11px;
    padding-left: 10px;
}
QLabel#notifBadge {
    background: @bg.hover;
    color: @text.primary;
    border-radius: 8px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#notifBadge[hasUnread="true"] {
    background: @semantic.err;
    color: @text.inverse;
}
QWidget#statusPanel {
    background: @bg.overlay;
    border-top: 1px solid @border.subtle;
}
QListWidget#historyList, QListWidget#notifList {
    background: transparent;
    border: none;
    outline: none;
    font-size: 12px;
}
QListWidget#historyList::item, QListWidget#notifList::item {
    padding: 6px 8px;
    border-radius: 4px;
    color: @text.primary;
}
QListWidget#historyList::item:hover, QListWidget#notifList::item:hover {
    background: @bg.hover;
}

/* ===== BUTTONS (shared) ===== */
QPushButton#primaryBtn {
    background: @accent.default;
    color: @text.inverse;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 600;
    min-height: 32px;
}
QPushButton#primaryBtn:hover { background: @accent.hover; }
QPushButton#primaryBtn:pressed { background: @accent.pressed; }
QPushButton#primaryBtn:disabled {
    background: @bg.hover;
    color: @text.tertiary;
}
QPushButton#secondaryBtn {
    background: transparent;
    color: @text.primary;
    border: 1px solid @border.strong;
    border-radius: 6px;
    padding: 6px 16px;
    min-height: 32px;
}
QPushButton#secondaryBtn:hover { background: @bg.hover; }
QPushButton#secondaryBtn:pressed { background: @bg.pressed; }

/* ===== INPUTS ===== */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background: @bg.sunken;
    color: @text.primary;
    border: 1px solid @border.subtle;
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: @accent.muted;
    selection-color: @text.primary;
    font-size: 13px;
    min-height: 28px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QComboBox:focus {
    border: 1px solid @border.focus;
}
QLineEdit:disabled, QTextEdit:disabled {
    color: @text.tertiary;
    background: @bg.surface;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: @bg.surface2;
    border: 1px solid @border.subtle;
    selection-background-color: @accent.muted;
    color: @text.primary;
}

/* ===== SETTINGS ===== */
QWidget#settingsNav {
    background: @bg.sunken;
    border-right: 1px solid @border.subtle;
    min-width: 180px;
}
QListWidget#settingsNavList {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget#settingsNavList::item {
    padding: 10px 14px;
    border-radius: 4px;
    margin: 2px 8px;
    color: @text.secondary;
}
QListWidget#settingsNavList::item:hover {
    background: @bg.hover;
    color: @text.primary;
}
QListWidget#settingsNavList::item:selected {
    background: @accent.muted;
    color: @accent.default;
    border-left: 2px solid @accent.default;
}

/* ===== DB VIEWER ===== */
QWidget#dbSidebar {
    background: @bg.surface;
    border-right: 1px solid @border.subtle;
    max-width: 260px;
}
QListWidget#tableList {
    background: transparent;
    border: none;
    outline: none;
    font-size: 12px;
}
QListWidget#tableList::item {
    padding: 5px 8px;
    border-radius: 4px;
    min-height: 28px;
    color: @text.primary;
}
QListWidget#tableList::item:hover { background: @bg.hover; }
QListWidget#tableList::item:selected {
    background: @bg.selected;
    color: @text.primary;
}
QTableView#dbGrid {
    background: @bg.surface2;
    alternate-background-color: @grid.alt;
    gridline-color: @grid.line;
    color: @data.mono;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    border: none;
    selection-background-color: @bg.selected;
    selection-color: @text.primary;
}
QTableView#dbGrid::item { padding: 4px 8px; }
QHeaderView::section {
    background: @bg.sunken;
    color: @text.secondary;
    border: none;
    border-right: 1px solid @grid.line;
    border-bottom: 1px solid @border.subtle;
    padding: 6px 8px;
    font-family: "Segoe UI", sans-serif;
    font-size: 12px;
    font-weight: 600;
    min-height: 28px;
}
QWidget#sqlConsole {
    background: @code.bg;
    border-top: 1px solid @border.subtle;
}
QPlainTextEdit#sqlEditor {
    background: @code.bg;
    color: @data.mono;
    border: none;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    padding: 8px;
}
QLabel#sqlResultBar {
    background: @bg.surface;
    color: @text.secondary;
    font-size: 11px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    padding: 4px 10px;
    border-top: 1px solid @border.subtle;
}
QLabel#sqlResultBar[error="true"] { color: @semantic.err; }

/* ===== SCROLLBARS ===== */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: @scrollbar;
    border-radius: 4px;
    min-height: 32px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover { background: @scrollbar.hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: @scrollbar;
    border-radius: 4px;
    min-width: 32px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: @scrollbar.hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ===== MENUS ===== */
QMenu {
    background: @bg.surface2;
    color: @text.primary;
    border: 1px solid @border.subtle;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 8px 28px 8px 12px;
    border-radius: 4px;
    font-size: 13px;
}
QMenu::item:selected { background: @bg.hover; }
QMenu::item:disabled { color: @text.tertiary; }
QMenu::separator {
    height: 1px;
    background: @border.subtle;
    margin: 4px 8px;
}

/* ===== MONO OUTPUT (command result, logs) ===== */
QPlainTextEdit#monoOutput, QTextEdit#logView {
    background: @code.bg;
    color: @data.mono;
    border: 1px solid @border.subtle;
    border-radius: 6px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    padding: 8px;
}
"""


class ThemeEngine(QObject):
    theme_changed = Signal(str)

    _instance: ThemeEngine | None = None

    @classmethod
    def instance(cls) -> ThemeEngine:
        if cls._instance is None:
            cls._instance = ThemeEngine()
        return cls._instance

    def apply(self, theme: str) -> None:
        _map = {
            "light": Theme.LIGHT,
            "dark":  Theme.DARK,
            "auto":  Theme.AUTO,
        }
        setTheme(_map.get(theme, Theme.AUTO))
        from cashcontrol.gui.theme_helper import color as _tc_a

        setThemeColor(QColor(_tc_a("accent")))
        self._apply_stylesheet()
        current = "dark" if isDarkTheme() else "light"
        self.theme_changed.emit(current)

    def current(self) -> str:
        return "dark" if isDarkTheme() else "light"

    def _apply_stylesheet(self) -> None:
        from cashcontrol.gui.theme_helper import color as _tc
        from cashcontrol.gui.theme_helper import resolve
        qss = self._build_qss(_tc) + CORE_QSS
        app = QApplication.instance()
        if app:
            app.setStyleSheet(resolve(qss))

    def _build_qss(self, _tc: Callable[[str], str]) -> str:
        from qfluentwidgets import isDarkTheme
        dark = isDarkTheme()

        # ── Общий блок — работает для обеих тем ──────────────────────────
        common = f"""
            QToolTip {{
                background-color: {_tc('bg_tooltip')};
                color: {_tc('text_primary')};
                border: 1px solid {_tc('border_primary')};
                padding: 4px 8px;
                border-radius: 3px;
                font-size: 12px;
            }}
            QSplitter::handle {{
                background-color: {_tc('border_primary')};
            }}
            QMenu {{
                background-color: {_tc('bg_surface')};
                color: {_tc('text_primary')};
                border: 1px solid {_tc('border_primary')};
                border-radius: 4px;
                padding: 2px;
            }}
            QMenu::item {{
                padding: 4px 20px 4px 12px;
                border-radius: 3px;
            }}
            QMenu::item:selected {{
                background-color: {_tc('accent')};
                color: {_tc('text_on_accent')};
            }}
            QMenu::item:disabled {{
                color: {_tc('text_tertiary')};
            }}
            QMenu::separator {{
                background-color: {_tc('border_primary')};
                height: 1px;
                margin: 3px 8px;
            }}
            QMessageBox {{
                background-color: {_tc('bg_primary')};
            }}
            QMessageBox QLabel {{
                color: {_tc('text_primary')};
            }}
            QDialog {{
                background-color: {_tc('bg_primary')};
            }}
        """

        if dark:
            theme_style = f"""
                QMainWindow {{
                    background-color: {_tc('bg_primary')};
                }}
                QWidget#CashControlMainWindow {{
                    background-color: {_tc('bg_primary')};
                }}
                QFrame[frameShape="5"] {{
                    background-color: {_tc('border_primary')};
                }}
                QLabel {{
                    color: {_tc('text_primary')};
                }}
                QStatusBar {{
                    background-color: {_tc('bg_primary')};
                    color: {_tc('text_secondary')};
                }}
                QScrollArea {{
                    background-color: {_tc('bg_primary')};
                    border: none;
                }}
                QScrollArea > QWidget > QWidget {{
                    background-color: {_tc('bg_primary')};
                }}
                QGroupBox {{
                    color: {_tc('text_primary')};
                    border: 1px solid {_tc('border_primary')};
                    border-radius: 4px;
                    margin-top: 8px;
                }}
                QGroupBox::title {{
                    color: {_tc('text_primary')};
                }}
                QPlainTextEdit {{
                    background-color: {_tc('bg_surface')};
                    color: {_tc('text_primary')};
                    border: 1px solid {_tc('border_primary')};
                }}
                QSpinBox {{
                    background-color: {_tc('bg_surface')};
                    color: {_tc('text_primary')};
                    border: 1px solid {_tc('border_primary')};
                }}
                QCheckBox {{
                    color: {_tc('text_primary')};
                }}
                QListWidget {{
                    background-color: {_tc('bg_surface')};
                    color: {_tc('text_primary')};
                    border: 1px solid {_tc('border_primary')};
                }}
                QListWidget::item:selected {{
                    background-color: {_tc('accent')};
                    color: {_tc('text_on_accent')};
                }}
                QListWidget::item:hover {{
                    background-color: {_tc('bg_hover')};
                }}
                QPushButton {{
                    background-color: {_tc('bg_surface')};
                    color: {_tc('text_primary')};
                    border: 1px solid {_tc('border_primary')};
                    border-radius: 4px;
                    padding: 4px 12px;
                }}
                QPushButton:hover {{
                    background-color: {_tc('bg_hover')};
                }}
                QPushButton:pressed {{
                    background-color: {_tc('bg_pressed')};
                }}
                TabBar {{
                    background-color: {_tc('bg_secondary')};
                    border-bottom: 1px solid {_tc('border_primary')};
                }}
                TabBar::tab {{
                    background-color: {_tc('bg_tertiary')};
                    color: {_tc('text_primary')};
                    border: 1px solid {_tc('border_primary')};
                    border-bottom: none;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                    padding: 6px 16px;
                    margin-right: 2px;
                    margin-top: 2px;
                }}
                TabBar::tab:selected {{
                    background-color: {_tc('bg_primary')};
                    color: {_tc('text_primary')};
                    border: 2px solid {_tc('accent')};
                    border-bottom: none;
                    margin-top: 0px;
                    padding: 7px 17px;
                    font-weight: bold;
                }}
                TabBar::tab:hover:!selected {{
                    background-color: {_tc('bg_hover')};
                    border-color: {_tc('tab_hover_border')};
                }}
            """
        else:
            theme_style = f"""
                QMainWindow {{
                    background-color: {_tc('bg_secondary')};
                }}
                QFrame[frameShape="5"] {{
                    background-color: {_tc('border_primary')};
                }}
                QLabel {{
                    color: {_tc('text_primary')};
                }}
                QListWidget {{
                    background-color: {_tc('bg_surface')};
                    color: {_tc('text_primary')};
                    border: 1px solid {_tc('border_primary')};
                }}
                QListWidget::item:selected {{
                    background-color: {_tc('accent')};
                    color: {_tc('text_on_accent')};
                }}
                QListWidget::item:hover {{
                    background-color: {_tc('bg_hover')};
                }}
                QGroupBox {{
                    border: 1px solid {_tc('border_primary')};
                    border-radius: 4px;
                    margin-top: 8px;
                }}
                TabBar {{
                    background-color: {_tc('bg_secondary')};
                    border-bottom: 1px solid {_tc('border_input')};
                }}
                TabBar::tab {{
                    background-color: {_tc('bg_hover')};
                    border: 1px solid {_tc('border_input')};
                    border-bottom: none;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                    padding: 6px 16px;
                    margin-right: 2px;
                    margin-top: 2px;
                }}
                TabBar::tab:selected {{
                    background-color: {_tc('bg_primary')};
                    border: 2px solid {_tc('accent')};
                    border-bottom: none;
                    margin-top: 0px;
                    padding: 7px 17px;
                    font-weight: bold;
                }}
                TabBar::tab:hover:!selected {{
                    background-color: {_tc('bg_pressed')};
                    border-color: {_tc('tab_hover_border')};
                }}
            """

        return common + theme_style
