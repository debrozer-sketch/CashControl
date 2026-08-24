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


CORE_QSS = """/* ===== ТАБЛО И ЭМАЛЬ (ai/tablo-emal.txt) ===== */
QMainWindow { background: @bg_primary; }
QDialog { background: @bg_dialog; }
QToolTip {
    background: @bg_tooltip; color: @bg_primary;
    border: 1px solid @border_secondary; padding: 4px 8px;
}

/* --- скроллбары --- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: @scrollbar_thumb; border-radius: 2px;
    min-height: 24px; min-width: 24px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: @scrollbar_thumb_hover;
}
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* --- меню: маршрутная полоса на выбранном пункте --- */
QMenu {
    background: @bg_elevated; border: 1px solid @border_primary; padding: 4px;
}
QMenu::item {
    padding: 6px 28px 6px 12px; color: @text_primary;
    border-left: 3px solid transparent;
}
QMenu::item:selected { background: @accent_subtle; border-left: 3px solid @accent; }
QMenu::item:disabled { color: @text_disabled; }
QMenu::separator { height: 1px; background: @separator; margin: 4px 8px; }

/* --- поля: 30px задаёт код --- */
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: @bg_input; color: @text_primary;
    border: 1px solid @border_input; border-radius: 4px; padding: 4px 8px;
    selection-background-color: @accent_subtle; selection-color: @text_primary;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid @border_focus;
}
QLineEdit:disabled, QComboBox:disabled { background: @bg_disabled; color: @text_disabled; }
QComboBox QAbstractItemView {
    background: @bg_elevated; border: 1px solid @border_primary;
    selection-background-color: @accent_subtle; selection-color: @text_primary;
    outline: none;
}

/* --- сайдбар: жетоны --- */
#CashControlSidebar {
    background: @bg_secondary; border-right: 1px solid @border_primary;
}
#CashControlSidebar QToolButton {
    background: transparent; border: 1px solid transparent; border-radius: 20px;
}
#CashControlSidebar QToolButton:hover {
    background: @btn_flat_hover; border: 1px solid @accent;
}
#CashControlSidebar QToolButton:pressed { background: @accent_fill; }

/* --- вкладки-станции --- */
#sessionTabArea { background: @bg_primary; }
#TabRail { background: @rail; max-height: 2px; }

/* --- бусина пинга: цвет + форма --- */
#pingDot { border-radius: 5px; }
#pingDot[ping="ok"]      { background: @success; border: 1px solid @success; }
#pingDot[ping="slow"]    { background: transparent; border: 3px solid @warning; }
#pingDot[ping="timeout"] { background: @error; border: 1px solid @error; border-radius: 0; }
#pingDot[ping="unknown"] { background: transparent; border: 1px solid @text_tertiary; }

/* --- тулбар: эмалевые пластины 66x54 (размер — код) --- */
#CashToolbar, #actionToolbar {
    background: @bg_surface; border-bottom: 1px solid @border_primary;
}
#ActionButton {
    background: @control_fill; color: @text_secondary; font-size: 11px;
    border: 1px solid @border_subtle; border-radius: 4px; padding: 0;
}
#ActionButton:hover {
    background: @btn_flat_hover; color: @text_primary;
    border: 1px solid @border_primary;
}
#ActionButton:pressed {
    background: @accent_fill; color: @text_on_accent;
    border: 1px solid @accent_pressed;
}
#ActionButton:disabled {
    background: @control_fill_disabled; color: @text_disabled;
    border: 1px solid @border_subtle;
}
#ActionButton[danger="true"] { color: @error; border: 1px solid @error; }
#ActionButton[danger="true"]:hover {
    background: @btn_danger_bg; color: #FFFFFF;
}
#ActionButton[danger="true"]:pressed {
    background: @btn_danger_hover; color: #FFFFFF;
}
#ToolbarDivider { background: @separator; max-width: 1px; }

/* --- VNC --- */
#vncPanel {
    background: @vnc_bg; border: 1px solid @border_secondary; border-radius: 4px;
}

/* --- карточки с маршрутной линией --- */
#InfoCard {
    background: @bg_card; border: 1px solid @border_primary;
    border-left: 4px solid @route_idle;
    border-radius: 4px; padding: 12px;
}
#InfoCard[route="pos"]   { border-left: 4px solid @route_pos; }
#InfoCard[route="hw"]    { border-left: 4px solid @route_hw; }
#InfoCard[route="misc"]  { border-left: 4px solid @route_misc; }
#InfoCard[route="idle"]  { border-left: 4px solid @route_idle; }

#InfoCard[state="loading"] {
    border-left: 4px solid @route_idle; background: @bg_card;
}
#InfoCard[state="timeout"] {
    border: 1px dashed @warning_border;
    border-left: 4px solid @warning_border;
}
#InfoCard[state="error"] {
    border: 1px solid @error; border-left: 4px solid @error;
}

#CardTitle { color: @text_heading; font-size: 13px; font-weight: bold; background: transparent; }
#CardRule { background: @separator; max-height: 1px; }
#skeletonBar { background: @bg_tertiary; border-radius: 2px; }
#SeverityBadge[sev="warning"] {
    background: @bg_warning; color: @warning_text;
    border: 1px solid @warning_border; border-radius: 3px; padding: 1px 6px;
}
#SeverityBadge[sev="error"] {
    background: @bg_danger; color: @error;
    border: 1px solid @error; border-radius: 3px; padding: 1px 6px;
}

/* --- статус-бар / история --- */
#StatusBar {
    background: @bg_secondary; color: @text_secondary;
    border-top: 1px solid @border_primary;
}
#StatusChip[result="ok"]    { background: @success; max-width: 4px; }
#StatusChip[result="error"] { background: @error;   max-width: 4px; }
#StatusChip[result="idle"]  { background: @route_idle; max-width: 4px; }
#HistoryPanel {
    background: @bg_elevated; border: 1px solid @border_primary; border-bottom: none;
}

/* --- моно-поверхности --- */
#MonoPanel, #logViewer, #SqlConsole {
    background: @sql_bg; color: @sql_text; border: 1px solid @border_input;
    border-radius: 4px; font-family: Consolas, "Cascadia Mono"; font-size: 12px;
    padding: 6px 8px; selection-background-color: @accent_subtle;
}

/* --- DB Viewer --- */
#TableList { background: @bg_surface; border: 1px solid @border_primary; outline: none; }
#TableList::item {
    padding: 4px 8px; color: @text_primary; border-left: 3px solid transparent;
}
#TableList::item:hover { background: @bg_hover; }
#TableList::item:selected {
    background: @accent_subtle; border-left: 3px solid @accent; color: @text_primary;
}
#DbGrid {
    background: @bg_card; alternate-background-color: @bg_table_alt;
    border: 1px solid @border_primary; gridline-color: @border_subtle;
    selection-background-color: @bg_selected; selection-color: @text_primary;
    outline: none;
}
#DbGrid::item { padding: 2px 4px; }
QHeaderView::section {
    background: @table_header_bg; color: @table_header_text;
    font-weight: bold; border: none;
    border-right: 1px solid @border_subtle; border-bottom: 2px solid @border_secondary;
    padding: 3px 6px;
}
#SqlResultBar {
    background: @bg_surface; color: @text_secondary;
    border-top: 1px solid @border_subtle; font-family: Consolas;
}
#SqlResultBar[state="error"] { background: @bg_danger; color: @error; }

/* --- кнопки диалогов (32px — код) --- */
QPushButton {
    background: @control_fill; color: @text_primary;
    border: 1px solid @border_primary; border-radius: 4px; padding: 5px 16px;
}
QPushButton:hover { background: @control_fill_hover; }
QPushButton:pressed { background: @control_fill_pressed; }
QPushButton:disabled {
    background: @control_fill_disabled; color: @text_disabled;
    border: 1px solid @border_subtle;
}
QPushButton[primary="true"] {
    background: @accent_fill; color: @text_on_accent;
    border: 1px solid @accent_pressed;
}
QPushButton[primary="true"]:hover { background: @accent_fill_hover; }
QPushButton[primary="true"]:pressed { background: @accent_fill_pressed; }
QPushButton[cancel="true"] { background: @btn_cancel_bg; }
QPushButton[danger="true"] {
    background: @btn_danger_bg; color: #FFFFFF;
    border: 1px solid @btn_danger_hover;
}
QPushButton[danger="true"]:hover { background: @btn_danger_hover; }
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
