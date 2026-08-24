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
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor

if TYPE_CHECKING:
    from collections.abc import Callable


CORE_QSS = """/* ---------- Base ---------- */

QWidget {
    background-color: @bg_app;
    color: @text_primary;
    font-family: "Segoe UI";
    font-size: 12px;
}

QMainWindow,
QDialog,
QWizard {
    background-color: @bg_app;
}

QLabel {
    background: transparent;
    color: @text_primary;
}

QLabel[role="secondary"] {
    color: @text_secondary;
}

QLabel[role="muted"] {
    color: @text_muted;
}

QLabel[mono="true"],
QLineEdit[mono="true"],
QPlainTextEdit[mono="true"],
QTextEdit[mono="true"] {
    font-family: "Cascadia Mono";
}

QLabel[severity="success"] { color: @success; }
QLabel[severity="warning"] { color: @warning; }
QLabel[severity="error"]   { color: @danger; }
QLabel[severity="info"]    { color: @info; }

/* ---------- Inputs ---------- */

QLineEdit,
QTextEdit,
QPlainTextEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {
    min-height: 30px;
    padding: 0 8px;
    color: @text_primary;
    background-color: @bg_surface;
    border: 1px solid @border;
    border-radius: 5px;
    selection-background-color: @bg_selected;
    selection-color: @text_primary;
}

QTextEdit,
QPlainTextEdit {
    padding: 7px 8px;
}

QLineEdit:hover,
QTextEdit:hover,
QPlainTextEdit:hover,
QSpinBox:hover,
QDoubleSpinBox:hover,
QComboBox:hover {
    border-color: @border_strong;
}

QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus {
    border: 2px solid @focus;
}

QLineEdit[validation="error"],
QTextEdit[validation="error"],
QPlainTextEdit[validation="error"] {
    border: 1px solid @danger;
    background-color: @danger_soft;
}

QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled,
QComboBox:disabled {
    color: @text_disabled;
    background-color: @bg_disabled;
    border-color: @border_subtle;
}

/* ---------- Buttons ---------- */

QPushButton,
QToolButton {
    min-height: 30px;
    padding: 0 10px;
    color: @text_primary;
    background-color: @bg_surface;
    border: 1px solid @border;
    border-radius: 5px;
}

QPushButton:hover,
QToolButton:hover {
    background-color: @bg_hover;
    border-color: @border_strong;
}

QPushButton:pressed,
QToolButton:pressed {
    background-color: @bg_pressed;
}

QPushButton:checked,
QToolButton:checked {
    color: @accent;
    background-color: @accent_soft;
    border-color: @accent;
}

QPushButton:focus,
QToolButton:focus {
    border: 2px solid @focus;
}

QPushButton:disabled,
QToolButton:disabled {
    color: @text_disabled;
    background-color: @bg_disabled;
    border-color: @border_subtle;
}

QPushButton[role="primary"],
QToolButton[role="primary"] {
    color: @text_inverse;
    background-color: @accent;
    border-color: @accent;
    font-weight: 600;
}

QPushButton[role="primary"]:hover,
QToolButton[role="primary"]:hover {
    background-color: @accent_hover;
    border-color: @accent_hover;
}

QPushButton[role="primary"]:pressed,
QToolButton[role="primary"]:pressed {
    background-color: @accent_pressed;
    border-color: @accent_pressed;
}

QPushButton[role="danger"]:hover,
QToolButton[role="danger"]:hover {
    color: @danger;
    background-color: @danger_soft;
    border-color: @danger;
}

QPushButton[role="ghost"],
QToolButton[role="ghost"] {
    background-color: transparent;
    border-color: transparent;
}

QPushButton[role="ghost"]:hover,
QToolButton[role="ghost"]:hover {
    background-color: @bg_hover;
}

/* ---------- Sidebar ---------- */

QFrame#sidebar {
    min-width: 52px;
    max-width: 52px;
    background-color: @bg_sidebar;
    border-right: 1px solid @border_strong;
}

QToolButton#sidebarButton {
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    padding: 0;
    color: @text_sidebar;
    background-color: transparent;
    border: 0;
    border-radius: 18px;
}

QToolButton#sidebarButton:hover {
    background-color: @bg_pressed;
}

QToolButton#sidebarButton:pressed,
QToolButton#sidebarButton:checked {
    color: @text_inverse;
    background-color: @accent;
}

QLabel#versionLabel {
    color: @text_muted;
    font-size: 10px;
}

/* ---------- Tab bar ---------- */

QFrame#sessionTabArea {
    min-height: 40px;
    max-height: 40px;
    background-color: @bg_surface_raised;
    border-bottom: 1px solid @border;
}

QTabBar {
    background-color: transparent;
}

QTabBar::tab {
    min-width: 132px;
    max-width: 176px;
    min-height: 38px;
    padding: 0 9px;
    color: @text_secondary;
    background-color: transparent;
    border: 0;
    border-right: 1px solid @border_subtle;
}

QTabBar::tab:hover {
    color: @text_primary;
    background-color: @bg_hover;
}

QTabBar::tab:selected {
    color: @text_primary;
    background-color: @bg_surface;
    border-bottom: 2px solid @accent;
    font-weight: 600;
}

QLabel#pingDot {
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
    border-radius: 4px;
}

QLabel#pingDot[ping="ok"]      { background-color: @success; }
QLabel#pingDot[ping="slow"]    { background-color: @warning; }
QLabel#pingDot[ping="timeout"] { background-color: @danger; }
QLabel#pingDot[ping="unknown"] { background-color: @ping_unknown; }

QToolButton#addSessionButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 30px;
    max-height: 30px;
    padding: 0;
    border-radius: 5px;
}

/* ---------- Action toolbar ---------- */

QFrame#actionToolbar {
    min-height: 62px;
    max-height: 62px;
    background-color: @bg_surface;
    border-bottom: 1px solid @border;
}

QToolButton#actionButton {
    min-width: 66px;
    max-width: 78px;
    min-height: 52px;
    max-height: 52px;
    padding: 3px 5px;
    background-color: transparent;
    border-color: transparent;
    border-radius: 5px;
    font-size: 11px;
}

QToolButton#actionButton:hover {
    background-color: @bg_hover;
}

QToolButton#actionButton:checked {
    color: @accent;
    background-color: @accent_soft;
    border-color: @accent;
}

QToolButton#actionButton[role="danger"]:hover {
    color: @danger;
    background-color: @danger_soft;
    border-color: @danger;
}

QFrame#toolbarSeparator {
    min-width: 1px;
    max-width: 1px;
    min-height: 32px;
    max-height: 32px;
    background-color: @border_subtle;
    border: 0;
}

/* ---------- Work area / splitter ---------- */

QFrame#workArea {
    background-color: @bg_app;
}

QSplitter::handle {
    background-color: @border_subtle;
}

QSplitter::handle:horizontal {
    width: 5px;
    margin: 4px 1px;
}

QSplitter::handle:vertical {
    height: 5px;
    margin: 1px 4px;
}

QSplitter::handle:hover {
    background-color: @accent;
}

/* ---------- VNC ---------- */

QFrame#vncPanel,
QFrame#vncViewport {
    background-color: @vnc_bg;
    border: 1px solid @border;
    border-radius: 7px;
}

QFrame#vncControls {
    min-height: 38px;
    max-height: 38px;
    background-color: @bg_surface_raised;
    border: 1px solid @border;
    border-radius: 5px;
}

QLabel#vncEmptyTitle {
    color: @text_inverse;
    font-size: 15px;
    font-weight: 600;
}

QLabel#vncEmptyText {
    color: @text_muted;
}

/* ---------- Info cards ---------- */

QFrame#infoPanel {
    background-color: transparent;
}

QFrame#infoCard {
    background-color: @bg_surface;
    border: 1px solid @border;
    border-radius: 7px;
}

QFrame#infoCard:hover {
    border-color: @border_strong;
}

QFrame#cardHeader {
    min-height: 36px;
    max-height: 36px;
    background-color: @bg_surface_raised;
    border-bottom: 1px solid @border_subtle;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}

QLabel#cardTitle {
    font-size: 14px;
    font-weight: 600;
}

QFrame#cardStateRail {
    min-width: 3px;
    max-width: 3px;
    border: 0;
}

QFrame#cardStateRail[state="loading"] { background-color: @info; }
QFrame#cardStateRail[state="ready"]   { background-color: @success; }
QFrame#cardStateRail[state="timeout"] { background-color: @warning; }
QFrame#cardStateRail[state="error"]   { background-color: @danger; }
QFrame#cardStateRail[state="idle"]    { background-color: @ping_unknown; }

QFrame#infoRow {
    min-height: 28px;
    background-color: transparent;
    border-bottom: 1px solid @border_subtle;
}

QLabel#infoLabel {
    color: @text_secondary;
}

QLabel#infoValue {
    color: @text_primary;
}

QFrame#problemItem {
    min-height: 34px;
    background-color: @bg_surface_raised;
    border: 1px solid @border_subtle;
    border-radius: 5px;
}

QFrame#problemItem[severity="warning"] {
    background-color: @warning_soft;
    border-color: @warning;
}

QFrame#problemItem[severity="error"] {
    background-color: @danger_soft;
    border-color: @danger;
}

QFrame#connectionState {
    background-color: @bg_surface;
    border: 1px solid @border;
    border-radius: 7px;
}

QFrame#connectionState[state="error"] {
    background-color: @danger_soft;
    border-color: @danger;
}

/* ---------- Status bar and drawer ---------- */

QFrame#statusBar {
    min-height: 28px;
    max-height: 28px;
    background-color: @bg_surface_raised;
    border-top: 1px solid @border;
}

QFrame#statusDrawer {
    background-color: @bg_surface;
    border-top: 1px solid @border_strong;
}

QLabel#statusDot {
    min-width: 7px;
    max-width: 7px;
    min-height: 7px;
    max-height: 7px;
    border-radius: 3px;
}

QLabel#statusDot[status="success"] { background-color: @success; }
QLabel#statusDot[status="warning"] { background-color: @warning; }
QLabel#statusDot[status="error"]   { background-color: @danger; }
QLabel#statusDot[status="info"]    { background-color: @info; }

QLabel#notificationBadge {
    min-width: 18px;
    min-height: 18px;
    padding: 0 4px;
    color: @text_inverse;
    background-color: @accent;
    border-radius: 9px;
    font-size: 10px;
    font-weight: 600;
}

/* ---------- Navigation lists ---------- */

QListView,
QTreeView {
    color: @text_primary;
    background-color: @bg_surface;
    border: 1px solid @border;
    border-radius: 5px;
    selection-background-color: @bg_selected;
    selection-color: @text_primary;
}

QListView::item,
QTreeView::item {
    min-height: 30px;
    padding: 0 7px;
    border: 0;
}

QListView::item:hover,
QTreeView::item:hover {
    background-color: @bg_hover;
}

QListView::item:selected,
QTreeView::item:selected {
    color: @text_primary;
    background-color: @bg_selected;
}

QListView#settingsNavigation::item {
    min-height: 36px;
}

QListView#settingsNavigation::item:selected {
    color: @accent;
    background-color: @accent_soft;
    border-left: 3px solid @accent;
}

/* ---------- Tables / DB Viewer ---------- */

QTableView,
QTableWidget {
    color: @text_primary;
    background-color: @bg_surface;
    alternate-background-color: @table_alt;
    border: 1px solid @border;
    gridline-color: @table_grid;
    selection-background-color: @bg_selected;
    selection-color: @text_primary;
}

QTableView::item,
QTableWidget::item {
    min-height: 27px;
    padding: 0 6px;
    border: 0;
}

QTableView::item:hover,
QTableWidget::item:hover {
    background-color: @bg_hover;
}

QTableView::item:selected,
QTableWidget::item:selected {
    color: @text_primary;
    background-color: @bg_selected;
}

QHeaderView::section {
    min-height: 30px;
    padding: 0 7px;
    color: @text_secondary;
    background-color: @table_header;
    border: 0;
    border-right: 1px solid @table_grid;
    border-bottom: 1px solid @border_strong;
    font-weight: 600;
}

QHeaderView::section:hover {
    color: @text_primary;
    background-color: @bg_hover;
}

QFrame#dbSidebar,
QFrame#dbToolbar,
QFrame#paginationBar,
QFrame#sqlResultBar {
    background-color: @bg_surface_raised;
    border: 1px solid @border;
}

QPlainTextEdit#sqlEditor,
QPlainTextEdit#commandOutput,
QPlainTextEdit#logViewer {
    color: @code_text;
    background-color: @code_bg;
    border-color: @border;
    font-family: "Cascadia Mono";
    font-size: 12px;
}

/* ---------- Menus / tooltips ---------- */

QMenu {
    padding: 5px;
    color: @text_primary;
    background-color: @bg_surface;
    border: 1px solid @border_strong;
    border-radius: 7px;
}

QMenu::item {
    min-height: 30px;
    padding: 0 28px 0 10px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: @bg_hover;
}

QMenu::item:disabled {
    color: @text_disabled;
}

QMenu::separator {
    height: 1px;
    margin: 5px 7px;
    background-color: @border_subtle;
}

QToolTip {
    padding: 5px 7px;
    color: @tooltip_text;
    background-color: @tooltip_bg;
    border: 1px solid @border_strong;
    border-radius: 4px;
}

/* ---------- Scroll bars ---------- */

QScrollBar:vertical {
    width: 10px;
    margin: 0;
    background-color: @scroll_track;
    border: 0;
}

QScrollBar::handle:vertical {
    min-height: 32px;
    margin: 2px;
    background-color: @scroll_thumb;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background-color: @scroll_thumb_hover;
}

QScrollBar:horizontal {
    height: 10px;
    margin: 0;
    background-color: @scroll_track;
    border: 0;
}

QScrollBar::handle:horizontal {
    min-width: 32px;
    margin: 2px;
    background-color: @scroll_thumb;
    border-radius: 3px;
}

QScrollBar::handle:horizontal:hover {
    background-color: @scroll_thumb_hover;
}

QScrollBar::add-line,
QScrollBar::sub-line,
QScrollBar::add-page,
QScrollBar::sub-page {
    width: 0;
    height: 0;
    background: transparent;
    border: 0;
}

#infoCard[state="loading"] { border-left: 3px solid @info; }
#infoCard[state="timeout"] { border-left: 3px solid @warning; }
#infoCard[state="error"] { border-left: 3px solid @danger; }
#infoCard[state="ready"] { border-left: 3px solid @success; }
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
        from cashcontrol.gui.theme_helper import (
            _COLORS,
        )
        from cashcontrol.gui.theme_helper import (
            color as _tc,
        )
        dark = isDarkTheme()
        qss = self._build_qss(_tc) + CORE_QSS
        for key, (light, dark_v) in _COLORS.items():
            qss = qss.replace("@" + key, dark_v if dark else light)
        app = QApplication.instance()
        if app:
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(_tc("bg_app")))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(_tc("text_primary")))
            palette.setColor(QPalette.ColorRole.Base, QColor(_tc("bg_surface")))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(_tc("table_alt")))
            palette.setColor(QPalette.ColorRole.Text, QColor(_tc("text_primary")))
            palette.setColor(QPalette.ColorRole.Button, QColor(_tc("bg_surface")))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(_tc("text_primary")))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(_tc("bg_selected")))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(_tc("text_primary")))
            palette.setColor(QPalette.ColorRole.Link, QColor(_tc("accent")))
            palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(_tc("text_muted")))
            app.setPalette(palette)
            app.setStyleSheet(qss)

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
