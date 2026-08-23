"""
theme_engine.py — singleton, единственная точка управления темой.

Usage:
    ThemeEngine.instance().apply("dark")

Подписка на смену темы:
    ThemeEngine.instance().theme_changed.connect(my_slot)
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor

CORE_QSS = """            QWidget { color: @text_primary; font-family: "Segoe UI", system-ui; font-size: 9pt; }
            QMainWindow, QDialog, QWizard { background: @bg_app; }
            QLabel { background: transparent; }

            /* === САЙДБАР === */
            #CashControlSidebar { background: @bg_app; border-right: 1px solid @border_subtle; }
            #CashControlSidebar QToolButton { background: transparent; border: none;
                border-radius: 20px; margin: 2px 6px; }
            #CashControlSidebar QToolButton:hover { background: @bg_surface_hover; }
            #CashControlSidebar QToolButton:pressed { background: @control_fill_pressed; }
            #CashControlSidebar QToolButton:checked { background: @accent_subtle;
                color: @accent; border-left: 3px solid @accent; border-radius: 4px;
                margin-left: 3px; }
            #CashControlSidebar QToolButton:disabled { background: transparent;
                color: @text_disabled; }

            /* === TAB BAR === */
            #CashTabBar { background: @bg_app; border-bottom: 1px solid @border_subtle; }
            #CashTabBar::tab { background: transparent; color: @text_secondary;
                padding: 8px 14px; border-top-left-radius: 6px;
                border-top-right-radius: 6px; margin-right: 2px; }
            #CashTabBar::tab:hover { background: @bg_surface_hover; }
            #CashTabBar::tab:selected { background: @bg_surface; color: @text_primary;
                border: 1px solid @border_subtle; border-bottom: 2px solid @accent;
                font-weight: 600; }

            /* === ТУЛБАР И КНОПКИ === */
            #CashToolbar { background: @bg_app; border-bottom: 1px solid @border_subtle; }
            #CashToolbar QToolButton { background: transparent; border: none;
                border-radius: 6px; padding: 4px; color: @text_primary; }
            #CashToolbar QToolButton:hover { background: @control_fill_hover; }
            #CashToolbar QToolButton:disabled { color: @text_disabled; }
            PushButton, ToolButton { background: @control_fill;
                border: 1px solid @border_primary; border-radius: 4px;
                padding: 5px 12px; min-height: 24px; }
            PushButton:hover, ToolButton:hover { background: @control_fill_hover; }
            PushButton:pressed, ToolButton:pressed { background: @control_fill_pressed; }
            PushButton:disabled, ToolButton:disabled { background: @control_fill;
                color: @text_disabled; border-color: @border_subtle; }
            PrimaryPushButton { background: @accent; color: @text_on_accent;
                border: none; border-radius: 4px; padding: 5px 12px; }
            PrimaryPushButton:hover { background: @accent_hover; }
            PrimaryPushButton:pressed { background: @accent_pressed; }
            TransparentToolButton { background: transparent; border: none;
                border-radius: 6px; padding: 4px; }
            TransparentToolButton:hover { background: @control_fill_hover; }

            /* === ПОЛЯ ВВОДА === */
            LineEdit, SearchLineEdit, PlainTextEdit, TextEdit, QComboBox,
            ComboBox, QSpinBox { background: @control_fill; color: @text_primary;
                border: 1px solid @border_primary; border-bottom: 2px solid @border_primary;
                border-radius: 4px; padding: 4px 8px;
                selection-background-color: @accent_subtle; }
            LineEdit:focus, SearchLineEdit:focus, PlainTextEdit:focus, TextEdit:focus,
            QComboBox:focus, ComboBox:focus, QSpinBox:focus {
                border-bottom: 2px solid @accent; background: @bg_surface; }
            LineEdit:disabled, ComboBox:disabled { background: @control_fill;
                color: @text_disabled; }

            /* === ИНФО-ПАНЕЛЬ === */
            #InfoCard { background: @bg_surface; border: 1px solid @border_subtle;
                border-radius: 8px; padding: 12px; }
            #InfoCard[state="warn"] { border-left: 3px solid @status_warn; }
            #InfoCard[state="error"] { border-left: 3px solid @status_error; }

            /* === ТАБЛИЦЫ, ДЕРЕВЬЯ, СПИСКИ === */
            QTableView, QTreeView, QListView, QListWidget { background: @bg_surface;
                color: @text_primary; border: 1px solid @border_subtle;
                border-radius: 4px; outline: none; gridline-color: @border_subtle; }
            QTableView::item, QTreeView::item, QListView::item, QListWidget::item {
                min-height: 26px; padding: 2px 6px; border: none; border-radius: 4px; }
            QTableView::item:hover, QTreeView::item:hover, QListView::item:hover,
            QListWidget::item:hover { background: @bg_surface_hover; }
            QTableView::item:selected, QTreeView::item:selected,
            QListView::item:selected, QListWidget::item:selected {
                background: @accent_subtle; color: @text_primary; }
            QHeaderView::section { background: @bg_surface_hover;
                color: @text_secondary; border: none;
                border-bottom: 1px solid @border_primary; padding: 0 8px;
                font-size: 8.5pt; font-weight: 600; }

            /* === МЕНЮ === */
            RoundMenu, QMenu { background: @bg_elevated; color: @text_primary;
                border: 1px solid @border_primary; border-radius: 8px; padding: 4px; }
            RoundMenu::item, QMenu::item { border-radius: 4px;
                padding: 6px 28px 6px 30px; min-height: 24px; }
            RoundMenu::item:selected, QMenu::item:selected {
                background: @control_fill_hover; }
            RoundMenu::separator, QMenu::separator { height: 1px;
                background: @border_subtle; margin: 4px 8px; }

            /* === СТАТУС-БАР === */
            #StatusBar { background: @bg_surface; border-top: 1px solid @border_subtle; }

            /* === SQL / ЛОГИ === */
            #SqlConsole { background: @sql_bg; color: @sql_text;
                font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9pt;
                border: none; border-top: 1px solid @border_subtle; padding: 6px; }

            /* === СКРОЛЛБАР === */
            QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
            QScrollBar::handle:vertical { background: @scrollbar_thumb;
                border-radius: 4px; min-height: 30px; }
            QScrollBar::handle:vertical:hover { background: @scrollbar_hover; }
            QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
            QScrollBar::handle:horizontal { background: @scrollbar_thumb;
                border-radius: 4px; min-width: 30px; }
            QScrollBar::add-line, QScrollBar::sub-line { background: none;
                border: none; height: 0; width: 0; }
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
        qss = self._build_qss(_tc)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(qss)

    def _build_qss(self, _tc) -> str:
        """Ядро 'Fluent 2 Compact Density' (ai/qwen3.6-max-preview.txt) +
        удержанные правила; @токены подставляются по активной теме."""
        from cashcontrol.gui.theme_helper import _COLORS

        dark = isDarkTheme()
        qss = CORE_QSS

        for key, (light, dark_v) in _COLORS.items():
            qss = qss.replace("@" + key, dark_v if dark else light)

        qss += f"""
            QSplitter::handle {{ background-color: {_tc('border_subtle')}; }}
            QFrame[frameShape="5"] {{ background-color: {_tc('border_subtle')}; }}
            QMessageBox {{ background-color: {_tc('bg_elevated')}; }}
            QScrollArea {{ background-color: {_tc('bg_app')}; border: none; }}
        """
        return qss
