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
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor

if TYPE_CHECKING:
    from collections.abc import Callable


CORE_QSS = """            * { font-family: "Segoe UI", "Segoe UI Variable Display", sans-serif;
                font-size: 13px; }

            QMainWindow, QDialog { background-color: @bg_app; color: @text_primary; }
            QLabel { background: transparent; }

            /* ── САЙДБАР ── */
            #CashControlSidebar { background-color: @bg_app;
                border-right: 1px solid @border_light; }
            #CashControlSidebar QToolButton { border-radius: 6px;
                margin: 2px 4px; padding: 6px; background: transparent; border: none; }
            #CashControlSidebar QToolButton:hover { background-color: @bg_surface_hover; }
            #CashControlSidebar QToolButton:checked { background-color: @bg_surface;
                border-left: 3px solid @accent; }

            /* ── TAB BAR ── */
            #CashTabBar { background-color: @bg_app;
                border-bottom: 1px solid @border_light; }

            /* ── TOOLBAR ── */
            #CashToolbar { background-color: @bg_surface;
                border-bottom: 1px solid @border_light; }
            #CashToolbar QToolButton { color: @text_primary; border-radius: 4px;
                padding: 4px; background: transparent; border: none; }
            #CashToolbar QToolButton:hover { background-color: @bg_app; }
            #CashToolbar QToolButton:disabled { color: @text_secondary; }

            /* ── ИНФО-КАРТОЧКИ ── */
            #InfoCard { background-color: @bg_surface;
                border: 1px solid @border_light; border-radius: 8px; padding: 12px; }

            /* ── КНОПКИ ── */
            QPushButton { background-color: @bg_surface; color: @text_primary;
                border: 1px solid @border_light; border-radius: 4px; padding: 5px 12px; }
            QPushButton:hover { background-color: @bg_surface_hover; }
            QPushButton:pressed { background-color: @bg_app; }
            QPushButton:disabled { color: @text_secondary; }
            PushButton { background-color: @bg_surface; color: @text_primary;
                border: 1px solid @border_light; border-radius: 4px; padding: 5px 12px; }
            PushButton:hover { background-color: @bg_surface_hover; }
            PrimaryPushButton { background-color: @accent; color: #FFFFFF;
                border: none; border-radius: 4px; padding: 5px 12px; }
            PrimaryPushButton:hover { background-color: @accent_hover; }
            TransparentToolButton { background: transparent; border: none;
                border-radius: 4px; }
            TransparentToolButton:hover { background-color: @bg_surface_hover; }

            /* ── ПОЛЯ ── */
            LineEdit, SearchLineEdit, PlainTextEdit, TextEdit, QComboBox,
            ComboBox, QSpinBox {
                background: @bg_surface; color: @text_primary;
                border: 1px solid @border_light; border-radius: 4px; padding: 4px 8px;
                selection-background-color: @accent; selection-color: #FFFFFF; }
            LineEdit:focus, SearchLineEdit:focus, PlainTextEdit:focus,
            QComboBox:focus, ComboBox:focus, QSpinBox:focus {
                border: 1px solid @accent; }

            /* ── МЕНЮ ── */
            QMenu, RoundMenu { background-color: @bg_surface; color: @text_primary;
                border: 1px solid @border_light; border-radius: 8px; padding: 4px; }
            QMenu::item { border-radius: 4px; padding: 6px 24px 6px 28px;
                min-height: 20px; }
            QMenu::item:selected { background-color: @bg_surface_hover; }
            QMenu::separator { height: 1px; background-color: @border_light;
                margin: 4px 8px; }

            /* ── СПИСКИ / ДЕРЕВЬЯ / ТАБЛИЦЫ ── */
            QTreeView, QListView, QListWidget {
                background-color: @bg_surface; color: @text_primary;
                border: 1px solid @border_light; border-radius: 4px; outline: none; }
            QTreeView::item, QListView::item, QListWidget::item {
                min-height: 24px; border-radius: 4px; }
            QTreeView::item:hover, QListView::item:hover, QListWidget::item:hover {
                background-color: @bg_surface_hover; }
            QTreeView::item:selected, QListView::item:selected,
            QListWidget::item:selected { background-color: @accent;
                color: #FFFFFF; }
            QTableView { background-color: @bg_surface;
                alternate-background-color: @bg_surface_hover;
                border: 1px solid @border_light; gridline-color: @border_light;
                selection-background-color: transparent; color: @text_primary; }
            QTableView::item { padding: 2px 4px;
                border-bottom: 1px solid transparent; min-height: 24px; }
            QTableView::item:selected { background-color: @accent_subtle;
                color: @text_primary; border: 1px solid @accent; }
            QHeaderView::section { background-color: @bg_app;
                color: @text_secondary; border: none;
                border-right: 1px solid @border_light;
                border-bottom: 1px solid @border_light;
                padding: 4px; font-weight: 600; }
            QTableCornerButton::section { background-color: @bg_app; border: none; }

            /* ── СТАТУС-БАР ── */
            #StatusBar { background-color: @accent; color: #FFFFFF;
                border-top: 1px solid @border_light; }
            #StatusBar QLabel { color: #FFFFFF; }
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
        """Ядро 'Pro Fluent Density' (ai/gemini-3.1-pro-preview.txt) +
        удержанные правила; @токены подставляются по активной теме."""
        from cashcontrol.gui.theme_helper import _COLORS

        dark = isDarkTheme()
        qss = CORE_QSS

        for key, (light, dark_v) in _COLORS.items():
            qss = qss.replace("@" + key, dark_v if dark else light)

        qss += f"""
            QSplitter::handle {{ background-color: {_tc('border_light')}; }}
            QFrame[frameShape="5"] {{ background-color: {_tc('border_light')}; }}
            QMessageBox {{ background-color: {_tc('bg_surface')}; }}
            QScrollArea {{ background-color: {_tc('bg_app')}; border: none; }}
        """
        return qss
