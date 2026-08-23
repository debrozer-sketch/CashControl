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


CORE_QSS = """/* ===== GLOBAL ===== */
QWidget {
    color: @text_primary;
    font-family: "Segoe UI", "Inter", "Calibri", sans-serif;
    font-size: 12px;
    outline: none;
}

QToolTip {
    background-color: @bg_surface;
    color: @text_primary;
    border: 1px solid @border_default;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 11px;
}

QScrollArea { border: none; }

/* ===== SIDEBAR ===== */
#CashControlSidebar {
    background-color: @bg_app;
    border-right: 1px solid @border_default;
}

#CashControlSidebar QToolButton {
    border-radius: 18px;
    background: transparent;
    color: @text_secondary;
    border: none;
}

#CashControlSidebar QToolButton:hover {
    background: @bg_hover;
    color: @text_primary;
}

#CashControlSidebar QToolButton:pressed {
    background: @bg_pressed;
    color: @accent;
}

#CashControlSidebar QToolButton:checked {
    background: @bg_surface;
    color: @accent;
    border-left: 2px solid @accent;
}

/* ===== TAB BAR ===== */
#CashTabBar {
    background: @bg_surface_alt;
    border-bottom: 1px solid @border_subtle;
}

/* ===== TOOLBAR ===== */
#CashToolbar {
    background: @bg_surface;
    border-bottom: 1px solid @border_default;
    spacing: 4px;
    padding: 4px 8px;
}

#CashToolbar QToolButton {
    min-width: 60px;
    max-width: 76px;
    border-radius: 4px;
    background: transparent;
    color: @text_secondary;
    font-size: 9px;
    padding-top: 2px;
}

#CashToolbar QToolButton:hover {
    background: @bg_hover;
    color: @text_primary;
}

#CashToolbar QToolButton:pressed {
    background: @bg_pressed;
    color: @accent;
}

#CashToolbar QToolButton:disabled {
    color: @text_muted;
}

QToolButton[ccClass="danger"] {
    color: @timeout;
}

QToolButton[ccClass="danger"]:hover {
    background: @bg_timeout;
}

/* ===== VNC PANEL ===== */
#vncPanel { background: @bg_app; }

#vncStrip {
    background: @bg_surface_alt;
    border-top: 1px solid @border_subtle;
    min-height: 32px;
}

#vncStrip QToolButton {
    height: 28px;
    border-radius: 4px;
    background: transparent;
    color: @text_secondary;
    font-size: 10px;
    padding: 0 8px;
}

#vncStrip QToolButton:hover {
    background: @bg_hover;
    color: @text_primary;
}

/* ===== INFO CARDS ===== */
#InfoCard {
    background: @bg_surface;
    border: 1px solid @border_default;
    border-radius: 6px;
    border-left: 3px solid @accent;
}

#InfoCard[status="loading"] { border-left-color: @slow; }

#InfoCard[status="timeout"] { border-left-color: @timeout; }

#InfoCard[status="error"] {
    border-left-color: @timeout;
    background: @bg_timeout;
}

/* ===== STATUS BAR ===== */
#StatusBar {
    background: @bg_surface_alt;
    border-top: 1px solid @border_subtle;
    min-height: 24px;
}

#notificationPanel {
    background: @bg_surface;
    border: 1px solid @border_default;
    border-radius: 6px 6px 0 0;
}

/* ===== INPUTS ===== */
QLineEdit, QComboBox, QSpinBox {
    min-height: 28px;
    background: @bg_input;
    border: 1px solid @border_default;
    border-radius: 4px;
    padding: 0 8px;
    color: @text_primary;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid @border_focus;
}

/* ===== DB VIEWER ===== */
#dbSide {
    background: @bg_surface_alt;
    border-right: 1px solid @border_default;
}

#dbGrid QHeaderView::section {
    background: @bg_surface_alt;
    color: @text_primary;
    font-weight: 600;
    font-size: 11px;
    padding: 4px;
    border-bottom: 1px solid @border_default;
    border-right: 1px solid @border_subtle;
}

QTableView {
    gridline-color: @border_subtle;
    font-size: 11px;
    selection-background-color: @accent;
    selection-color: @text_inverse;
}

QTableView::item { padding: 2px 4px; }

QTableView::item:alternate { background: @bg_surface_alt; }

#dbConsolePanel {
    border-top: 1px solid @border_default;
    background: @bg_surface;
}

#dbConsolePanel QPlainTextEdit {
    background: @bg_input;
    color: @mono_text;
    font-family: "Cascadia Mono", monospace;
    font-size: 12px;
    border: none;
    selection-background-color: @accent;
    selection-color: @text_inverse;
}

/* ===== SCROLLBARS ===== */
QScrollBar:vertical { width: 8px; background: @bg_app; }

QScrollBar::handle:vertical {
    background: @border_default;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover { background: @text_secondary; }

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

QScrollBar:horizontal { height: 8px; background: @bg_app; }

QScrollBar::handle:horizontal {
    background: @border_default;
    min-width: 20px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover { background: @text_secondary; }

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }

/* ===== DIALOGS ===== */
QDialog { background: @bg_app; }

QPushButton {
    min-height: 32px;
    border-radius: 4px;
    padding: 0 16px;
    font-size: 12px;
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
        from cashcontrol.gui.theme_helper import (
            _COLORS,
        )
        from cashcontrol.gui.theme_helper import (
            color as _tc,
        )
        qss = self._build_qss(_tc) + CORE_QSS
        dark = isDarkTheme()
        for key, (light, dark_v) in _COLORS.items():
            qss = qss.replace("@" + key, dark_v if dark else light)
        app = QApplication.instance()
        if app:
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
