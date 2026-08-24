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


CORE_QSS = """/* ===== БРУТАЛИСТСКАЯ КАРТОЧНАЯ КАРТОТЕКА (ai/brutalist-archive) ===== */
QWidget { font-family: "Segoe UI", Arial, sans-serif; font-size: 12px; color: @text_primary; }
QMainWindow { background: @bg_primary; }
QDialog { background: @bg_dialog; }

QToolTip {
    background: @bg_tooltip; color: @text_on_accent;
    border: none; border-radius: 4px; padding: 6px 10px; font-size: 12px;
}

/* ===== САЙДБАР ===== */
#CashControlSidebar {
    background: @bg_elevated;
    border-right: 1px solid @border_subtle;
}
#CashControlSidebar QToolButton {
    border-radius: 20px;
    background: transparent;
    border: 1px solid transparent;
    padding: 9px;
}
#CashControlSidebar QToolButton:hover {
    background: @bg_hover; border-color: @border_subtle;
}
#CashControlSidebar QToolButton:pressed {
    background: @bg_pressed; border-color: @border_primary;
}

/* ===== ВКЛАДКИ ===== */
#sessionTabArea {
    background: @bg_secondary;
    border-bottom: 1px solid @border_subtle;
}
#sessionTabArea QTabBar::tab {
    background: @bg_secondary;
    color: @text_secondary;
    border: 1px solid @border_subtle;
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    padding: 6px 14px;
    min-width: 120px;
    max-width: 220px;
    font-size: 12px;
}
#sessionTabArea QTabBar::tab:selected {
    background: @bg_card;
    color: @text_primary;
    border-bottom: 2px solid @accent;
}
#sessionTabArea QTabBar::tab:hover:!selected {
    background: @bg_hover;
    border-bottom: 1px solid @tab_hover_border;
}

/* ===== ТОЧКА ПИНГА ===== */
#pingDot {
    border-radius: 4px;
    background: @text_tertiary;
}
#pingDot[ping="ok"] { background: @success; }
#pingDot[ping="slow"] { background: @warning; }
#pingDot[ping="timeout"] { background: @error; }
#pingDot[ping="unknown"] { background: @text_tertiary; }

/* ===== ТУЛБАР 66×54 ===== */
#CashToolbar {
    background: @bg_elevated;
    border-bottom: 1px solid @border_subtle;
    padding: 3px 8px;
}
#ActionButton {
    border-radius: 6px;
    border: 1px solid @border_subtle;
    background: @bg_surface;
    padding: 6px 2px 3px 2px;
    font-size: 10px;
    color: @text_primary;
}
#ActionButton:hover {
    background: @bg_hover; border-color: @accent;
}
#ActionButton:pressed {
    background: @bg_pressed; border-color: @border_focus;
}
#ActionButton:disabled {
    background: @bg_disabled; color: @text_disabled;
    border-color: @border_subtle;
}
#btnReboot {
    background: @btn_danger_bg; border-color: @btn_danger_bg;
    color: @text_on_accent;
}
#btnReboot:hover {
    background: @btn_danger_hover; border-color: @btn_danger_hover;
}
#btnRestart {
    background: @accent_fill; border-color: @accent;
    color: @accent_text;
}
#btnRestart:hover {
    background: @accent_fill_hover; border-color: @accent_fill_hover;
}

/* ===== VNC ===== */
#vncPanel {
    background: @vnc_bg;
    border: 1px solid @border_primary;
}

/* ===== КАРТОЧКИ ===== */
#InfoCard {
    background: @bg_card;
    border: 1px solid @border_subtle;
    border-left: 3px solid @accent;
    border-radius: 8px;
    padding: 12px;
    margin: 0 8px 8px 8px;
}
#InfoCard[status="loading"]  { border-left-color: @text_tertiary; }
#InfoCard[status="data"]     { border-left-color: @accent; }
#InfoCard[status="timeout"] {
    border-left-color: @warning;
    background: @warning_bg;
}
#InfoCard[status="error"] {
    border-left-color: @error;
    background: @bg_danger;
}
#InfoCardTitle {
    font-size: 13px; font-weight: 600;
    color: @text_heading; padding-bottom: 6px;
}
#InfoCard[status="timeout"] #InfoCardTitle { color: @warning_text; }
#InfoCard[status="error"] #InfoCardTitle { color: @error; }

/* ===== СТАТУС-БАР ===== */
#StatusBar {
    background: @bg_secondary;
    border-top: 1px solid @border_subtle;
}
#notificationPanel {
    background: @bg_surface;
    border: 1px solid @border_default;
    border-radius: 6px 6px 0 0;
}

/* ===== DB VIEWER ===== */
#DbGrid {
    background: @bg_card;
    border: 1px solid @border_primary;
    alternate-background-color: @bg_table_alt;
    gridline-color: @border_subtle;
    selection-background-color: @accent_subtle;
    selection-color: @text_primary;
}
#DbGrid QHeaderView::section {
    background: @table_header_bg;
    color: @table_header_text;
    padding: 6px 12px;
    border-right: 1px solid @border_subtle;
    border-bottom: 1px solid @border_subtle;
    font-weight: 600;
    font-size: 12px;
}
#DbGrid::item { padding: 4px 8px; }

#TableList {
    background: @bg_surface;
    border-right: 1px solid @border_subtle;
    outline: none;
}
#TableList::item {
    padding: 6px 12px; min-height: 28px; border-radius: 4px;
}
#TableList::item:selected { background: @accent_subtle; }

/* ===== SQL / ЛОГИ / МОНО ===== */
#SqlConsole {
    background: @sql_bg; color: @sql_text;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    border-top: 1px solid @border_primary;
    padding: 4px;
}
#logViewer {
    background: @bg_code; color: @text_code;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}
#MonoPanel {
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px; background: @bg_code; color: @text_code;
}

/* ===== СКЕЛЕТОН ===== */
#skeletonBar {
    background: @control_fill; border-radius: 2px;
}

/* ===== ПОЛЯ 30px ===== */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: @bg_input; border: 1px solid @border_input;
    border-radius: 4px; padding: 7px 10px;
    color: @text_primary;
    selection-background-color: @accent_subtle; selection-color: @text_primary;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid @border_focus;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    background: @bg_disabled; color: @text_disabled;
}

/* ===== КНОПКИ ===== */
QPushButton {
    background: @control_fill; border: 1px solid @border_secondary;
    border-radius: 4px; padding: 6px 16px;
    color: @text_primary;
}
QPushButton:hover { background: @control_fill_hover; }
QPushButton:pressed { background: @control_fill_pressed; }
QPushButton:disabled { background: @control_fill_disabled; color: @text_disabled; }
QPushButton:focus { border: 1px solid @border_focus; }

/* ===== МЕНЮ ===== */
QMenu {
    background: @bg_elevated; border: 1px solid @border_primary;
    border-radius: 6px; padding: 4px;
}
QMenu::item {
    padding: 8px 12px 8px 32px;
    min-height: 28px; border-radius: 4px;
}
QMenu::item:selected { background: @bg_hover; }
QMenu::item:disabled { color: @text_disabled; }
QMenu::separator { height: 1px; background: @separator; margin: 4px 8px; }

/* ===== СКРОЛЛБАРЫ ===== */
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }
QScrollBar::handle:vertical {
    background: @scrollbar_thumb; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: @scrollbar_thumb_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px 4px; }
QScrollBar::handle:horizontal {
    background: @scrollbar_thumb; border-radius: 5px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: @scrollbar_thumb_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: none; }

/* ===== ПРОЧЕЕ ===== */
QProgressBar {
    background: @control_fill; border: none;
    border-radius: 4px; text-align: center;
}
QProgressBar::chunk { background: @accent; border-radius: 4px; }

QTextBrowser {
    background: @bg_code; color: @text_code;
    border: none; padding: 8px;
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
        dark = isDarkTheme()
        qss = self._build_qss(_tc) + CORE_QSS
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
