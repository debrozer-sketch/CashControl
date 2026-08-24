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


CORE_QSS = """/* ---------------------- Общие -------------------- */
QWidget {
    color: @text-primary;
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog { background: @bg-base; }
QToolTip {
    background: @tooltip-bg;
    color: @tooltip-text;
    border: 1px solid @line-strong;
    border-radius: 4px;
    padding: 5px 8px;
    min-width: 120px;
}
QScrollArea { background: transparent; border: none; }

/* ---------------------- Сайдбар -------------------- */
QToolButton#SideNavButton {
    border: none;
    border-radius: 18px;
    background: transparent;
    color: @text-secondary;
    padding: 8px;
}
QToolButton#SideNavButton:hover {
    background: @bg-hover;
    color: @text-primary;
}
QToolButton#SideNavButton:pressed {
    background: @bg-pressed;
}

/* ---------------------- Таб-бар -------------------- */
QWidget#CashTabBar { background: @bg-base; }

/* ---------------------- Тулбар -------------------- */
QFrame#ActionToolbar {
    background: @bg-base;
    border-bottom: 1px solid @line-weak;
}
QToolButton#ActionButton {
    border: none;
    border-radius: 6px;
    background: transparent;
    color: @text-secondary;
    font-size: 11px;
    padding: 4px 8px;
}
QToolButton#ActionButton:hover {
    background: @bg-hover;
    color: @text-primary;
}
QToolButton#ActionButton:pressed {
    background: @bg-pressed;
}
QToolButton#ActionButton:disabled {
    color: @text-disabled;
}
QToolButton#ActionButton[role="danger"]:hover {
    background: @soft-err;
    color: @err;
}

/* ---------------------- VNC -------------------- */
#vncPanel { background: @vnc-bg; border: 1px solid @line-strong; border-radius: 8px; }

/* ---------------------- Карточки -------------------- */
#InfoCard {
    background: @bg-elev;
    border: 1px solid @line-strong;
    border-radius: 8px;
}
#InfoCard[state="loading"] { border-color: @info; }
#InfoCard[state="timeout"] { background: @soft-warn; border-color: @warn; }
#InfoCard[state="error"] { background: @soft-err; border-color: @err; }

/* ---------------------- Поля / редакторы -------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, ComboBox {
    background: @bg-elev;
    color: @text-primary;
    border: 1px solid @line-strong;
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: @sel-bg;
    selection-color: @sel-text;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
ComboBox:focus { border-color: @accent; }
QLineEdit:disabled, QPlainTextEdit:disabled {
    color: @text-disabled;
    background: @bg-sunken;
}
QPlainTextEdit#MonoPanel,
QPlainTextEdit#SqlConsole {
    background: @bg-sunken;
    color: @text-primary;
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 12px;
    border-radius: 8px;
}

/* ---------------------- Списки / таблицы -------------------- */
QListView, QTreeView, QListWidget {
    background: @bg-base; color: @text-primary;
    border: 1px solid @line-weak; border-radius: 6px; outline: none;
}
QListView::item, QTreeView::item, QListWidget::item {
    border-radius: 4px; padding: 4px 8px; min-height: 24px;
}
QListView::item:hover, QTreeView::item:hover, QListWidget::item:hover {
    background: @bg-hover;
}
QListView::item:selected, QTreeView::item:selected, QListWidget::item:selected {
    background: @soft-accent; color: @text-primary;
    border-left: 3px solid @accent;
}
QTableView {
    background: @bg-base;
    alternate-background-color: @bg-elev;
    gridline-color: @line-weak;
    border: none;
    selection-background-color: @sel-bg;
    selection-color: @sel-text;
}
QTableView::item { min-height: 24px; padding: 2px 6px; }
QTableView::item:hover { background: @bg-hover; }
QHeaderView::section {
    background: @bg-base;
    color: @text-secondary;
    border: none;
    padding: 0 6px;
    min-height: 28px;
    font-weight: 600;
}

/* ---------------------- Статус-бар -------------------- */
#StatusBar {
    background: @bg-sunken;
    border-top: 1px solid @line-strong;
    min-height: 26px;
}

/* ---------------------- Меню -------------------- */
QMenu, RoundMenu {
    background: @bg-elev; color: @text-primary;
    border: 1px solid @line-strong; border-radius: 8px; padding: 4px;
}
QMenu::item, RoundMenu::item {
    border-radius: 4px; padding: 6px 24px 6px 28px; min-height: 24px;
}
QMenu::item:selected, RoundMenu::item:selected { background: @bg-hover; }
QMenu::separator, RoundMenu::separator {
    height: 1px; background: @line-weak; margin: 4px 8px;
}

/* ---------------------- Кнопки (мягко, без width) -------- */
QPushButton {
    background: @bg-elev; color: @text-primary;
    border: 1px solid @line-strong; border-radius: 4px;
    padding: 5px 14px;
}
QPushButton:hover { background: @bg-hover; border-color: @accent; }
QPushButton:pressed { background: @bg-pressed; }
QPushButton:disabled { color: @text-disabled; background: @bg-sunken; }
PrimaryPushButton {
    background: @accent; color: #FFFFFF; border: none; border-radius: 4px;
    padding: 5px 14px;
}
PrimaryPushButton:hover { background: @accent-hover; }
PrimaryPushButton:pressed { background: @accent-pressed; }
TransparentToolButton { background: transparent; border: none; border-radius: 6px; }
TransparentToolButton:hover { background: @bg-hover; }

/* ---------------------- Скроллбары ------------------------ */
QScrollBar:vertical { background: @bg-base; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: @scroll-handle; border-radius: 4px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: @text-secondary; }
QScrollBar:horizontal { background: @bg-base; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: @scroll-handle; border-radius: 4px; min-width: 28px;
}
QScrollBar::handle:horizontal:hover { background: @text-secondary; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

QSplitter::handle { background: @line-weak; }
QSplitter::handle:hover { background: @line-strong; }
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
