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
        setThemeColor(QColor(_tc_a('accent')))
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
        from cashcontrol.gui.theme_helper import _COLORS

        dark = isDarkTheme()

        # ── Ядро «Fluent 2 Compact» (ai/adamant-ananke.txt §4) ───────────
        qss = """
            QWidget { color: @text_primary; font-family: "Segoe UI"; font-size: 9pt; }
            QMainWindow, QDialog { background: @bg_primary; }
            QLabel { background: transparent; }
            QToolTip { background: @bg_elevated; color: @text_primary;
                       border: 1px solid @border_primary; border-radius: 4px; padding: 6px 8px; }

            /* ── Сайдбар ── */
            #CashControlSidebar, #Sidebar { background: @bg_secondary;
                border-right: 1px solid @border_subtle; }
            #CashControlSidebar QToolButton, #Sidebar QToolButton {
                background: transparent; border: none; border-radius: 20px; }
            #CashControlSidebar QToolButton:hover, #Sidebar QToolButton:hover {
                background: @control_fill_hover; }
            #CashControlSidebar QToolButton:pressed { background: @control_fill_pressed; }
            #CashControlSidebar QToolButton:checked { background: @accent_subtle; }
            #CashControlSidebar QLabel { color: @text_tertiary; font-size: 8pt; }

            /* ── Кнопки ── */
            QPushButton { background: @control_fill; color: @text_primary;
              border: 1px solid @border_primary; border-radius: 4px;
              padding: 5px 12px; min-height: 20px; }
            QPushButton:hover { background: @control_fill_hover; }
            QPushButton:pressed { background: @control_fill_pressed; color: @text_secondary; }
            QPushButton:disabled { background: @control_fill_disabled;
              color: @text_disabled; border-color: @border_subtle; }
            PushButton, ToolButton { background: @control_fill;
              border: 1px solid @border_primary; border-radius: 4px; padding: 5px 12px; }
            PushButton:hover, ToolButton:hover { background: @control_fill_hover; }
            PushButton:pressed, ToolButton:pressed { background: @control_fill_pressed;
              color: @text_secondary; }
            PushButton:disabled, ToolButton:disabled { background: @control_fill_disabled;
              color: @text_disabled; border-color: @border_subtle; }
            PrimaryPushButton { background: @accent_fill; color: @text_on_accent;
              border: 1px solid transparent; border-radius: 4px; padding: 5px 12px; }
            PrimaryPushButton:hover { background: @accent_fill_hover; }
            PrimaryPushButton:pressed { background: @accent_fill_pressed; }
            PrimaryPushButton:disabled { background: @control_fill_disabled;
              color: @text_disabled; }
            TransparentToolButton, TransparentPushButton, TransparentDropDownToolButton {
              background: transparent; border: none; border-radius: 6px; }
            TransparentToolButton:hover, TransparentDropDownToolButton:hover {
              background: @control_fill_hover; }
            TransparentToolButton:pressed { background: @control_fill_pressed; }
            HyperlinkButton { color: @accent_text; background: transparent; border: none; }

            /* ── Тулбар кассы ── */
            #CashToolbar { background: @bg_primary; border-bottom: 1px solid @border_subtle; }
            #CashToolbar ToolButton, #CashToolbar DropDownToolButton {
              background: transparent; border: none; border-radius: 6px;
              min-width: 64px; min-height: 48px; padding: 4px 6px; font-size: 8pt; }
            #CashToolbar ToolButton:hover, #CashToolbar DropDownToolButton:hover {
              background: @control_fill_hover; }
            #CashToolbar ToolButton:pressed { background: @control_fill_pressed; }
            #CashToolbar ToolButton:disabled { color: @text_disabled; }

            /* ── Поля ввода (Fluent bottom-line) ── */
            LineEdit, SearchLineEdit, PlainTextEdit, TextEdit, QComboBox,
            ComboBox, QSpinBox {
              background: @control_fill; border: 1px solid @border_primary;
              border-bottom: 1px solid @control_border_bottom;
              border-radius: 4px; padding: 4px 8px;
              selection-background-color: @accent_subtle; selection-color: @text_primary; }
            LineEdit:focus, SearchLineEdit:focus, PlainTextEdit:focus, TextEdit:focus,
            QComboBox:focus, ComboBox:focus, QSpinBox:focus {
              border-bottom: 2px solid @accent; background: @bg_card; }
            LineEdit:disabled, PlainTextEdit:disabled { background: @control_fill_disabled;
              color: @text_disabled; }

            /* ── Меню / flyout ── */
            QMenu, RoundMenu { background: @bg_elevated; color: @text_primary;
              border: 1px solid @border_primary; border-radius: 8px; padding: 4px; }
            QMenu::item { border-radius: 4px; padding: 6px 28px 6px 30px; min-height: 20px; }
            QMenu::item:selected { background: @control_fill_hover; }
            QMenu::item:disabled { color: @text_disabled; }
            QMenu::separator { height: 1px; background: @border_subtle; margin: 4px 8px; }

            /* ── Списки / деревья / грид ── */
            QTreeView, QListView, QTableView, QListWidget {
              background: @bg_card; alternate-background-color: @bg_card;
              border: 1px solid @border_subtle; border-radius: 4px; outline: none;
              color: @text_primary; }
            QTreeView::item, QListView::item, QListWidget::item {
              min-height: 24px; border-radius: 4px; }
            QTreeView::item:hover, QListView::item:hover, QListWidget::item:hover {
              background: @control_fill_hover; }
            QTreeView::item:selected, QListView::item:selected,
            QListWidget::item:selected { background: @accent_subtle; color: @text_primary; }
            QHeaderView::section { background: @bg_secondary; color: @text_secondary;
              border: none; border-bottom: 1px solid @border_primary;
              padding: 0 8px; min-height: 28px; font-size: 8.5pt; }
            QTableView { gridline-color: @border_subtle;
              font-family: "Cascadia Mono","Consolas"; }
            QTableView::item { min-height: 24px; border: none;
              border-bottom: 1px solid @border_subtle; }
            QTableView::item:hover { background: @control_fill_hover; }
            QTableView::item:selected { background: @accent_subtle; color: @text_primary; }
            QTableCornerButton::section { background: @bg_secondary; border: none; }

            /* ── SQL-консоль / логи ── */
            #SqlConsole { background: @sql_bg; color: @sql_text;
              font-family: "Cascadia Mono","Consolas"; font-size: 9pt;
              border: none; }

            /* ── Карточки инфо-панели ── */
            #InfoCard { background: @bg_card; border: 1px solid @border_subtle;
              border-radius: 8px; }
            #InfoCard[state="warn"] { border-left: 3px solid @status_warn; }
            #InfoCard[state="error"] { border-left: 3px solid @status_error; }

            /* ── Статус-бар ── */
            #StatusBar { background: @bg_secondary; border-top: 1px solid @border_subtle; }

            /* ── Скроллбар ── */
            QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
            QScrollBar::handle:vertical { background: @scrollbar_thumb;
              border-radius: 4px; min-height: 30px; }
            QScrollBar::handle:vertical:hover { background: @scrollbar_thumb_hover; }
            QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
            QScrollBar::handle:horizontal { background: @scrollbar_thumb;
              border-radius: 4px; min-width: 30px; }
            QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page,
            QScrollBar::sub-page { background: none; border: none; width: 0; height: 0; }

            /* ── Прогресс ── */
            ProgressBar, QProgressBar { background: @border_subtle; border: none;
              border-radius: 2px; max-height: 4px; }
            QProgressBar::chunk { background: @accent; border-radius: 2px; }
        """

        for key, (light, dark_v) in _COLORS.items():
            qss = qss.replace("@" + key, dark_v if dark else light)

        # ── Удержанные правила предыдущей темы ───────────────────────────
        qss += f"""
            QSplitter::handle {{ background-color: {_tc('border_subtle')}; }}
            QFrame[frameShape="5"] {{ background-color: {_tc('border_subtle')}; }}
            QMainWindow {{ background-color: {_tc('bg_primary')}; }}
            QWidget#CashControlMainWindow {{ background-color: {_tc('bg_primary')}; }}
            QMessageBox {{ background-color: {_tc('bg_dialog')}; }}
            QScrollArea {{
                background-color: {_tc('bg_primary')}; border: none;
            }}
        """
        return qss
