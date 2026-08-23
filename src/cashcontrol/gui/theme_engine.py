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


CORE_QSS = """QWidget[ccRole="appRoot"],
QDialog[ccRole="dialogRoot"] {
    font-family: "Segoe UI";
    font-size: 9pt;
    color: @text_primary;
    background: @bg_primary;
}

QFrame[ccRole="surface"] {
    background: @bg_surface;
    border: 1px solid @border_subtle;
    border-radius: 10px;
}

QLabel[ccRole="versionText"] { color: @text_tertiary; font-size: 8pt; }

QPushButton[ccRole="button"],
QToolButton[ccRole="button"] {
    min-height: 32px;
    padding: 0 12px;
    color: @text_primary;
    background: @bg_surface;
    border: 2px solid @border_primary;
    border-radius: 8px;
}

QPushButton[ccRole="button"]:hover:!disabled,
QToolButton[ccRole="button"]:hover:!disabled {
    background: @bg_hover; border-color: @border_strong;
}

QPushButton[ccRole="button"]:pressed:!disabled,
QToolButton[ccRole="button"]:pressed:!disabled {
    background: @bg_pressed; border-color: @border_strong;
}

QPushButton[ccRole="button"]:focus:!disabled,
QToolButton[ccRole="button"]:focus:!disabled { border-color: @border_focus; }

QPushButton[ccRole="button"]:disabled,
QToolButton[ccRole="button"]:disabled {
    color: @text_disabled; background: @bg_disabled; border-color: @border_subtle;
}

QPushButton[ccRole="button"]:checked:!disabled,
QToolButton[ccRole="button"]:checked:!disabled {
    color: @accent; background: @bg_selected; border-color: @accent;
}

QPushButton[ccRole="button"][ccTone="primary"],
QToolButton[ccRole="button"][ccTone="primary"] {
    color: @text_on_accent; background: @accent; border-color: @accent;
}

QPushButton[ccRole="button"][ccTone="primary"]:hover:!disabled {
    background: @accent_hover; border-color: @accent_hover;
}

QPushButton[ccRole="button"][ccTone="primary"]:pressed:!disabled {
    background: @accent_pressed; border-color: @accent_pressed;
}

QToolButton[ccRole="button"][ccVariant="toolbar"] {
    min-width: 88px; min-height: 56px; padding: 4px 12px 5px 12px; border-radius: 8px;
}

QToolButton[ccRole="button"][ccVariant="sidebar"] {
    min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px;
    padding: 0; color: @text_secondary; background: @transparent;
    border-color: @transparent; border-radius: 20px;
}

QToolButton[ccRole="button"][ccVariant="sidebar"]:hover:!disabled {
    color: @text_primary; background: @bg_hover; border-color: @transparent;
}

QToolButton[ccRole="button"][ccVariant="sidebar"]:pressed:!disabled {
    background: @bg_pressed; border-color: @transparent;
}

QToolButton[ccRole="button"][ccVariant="sidebar"]:checked:!disabled {
    color: @accent; background: @bg_selected; border-color: @transparent;
}

QToolButton[ccRole="button"][ccTone="quietDanger"] {
    color: @danger; background: @bg_surface; border-color: @border_primary;
}

QToolButton[ccRole="button"][ccTone="quietDanger"]:hover:!disabled {
    color: @danger; background: @danger_subtle; border-color: @danger;
}

QToolButton[ccRole="button"][ccTone="quietDanger"]:pressed:!disabled {
    color: @text_on_danger; background: @danger; border-color: @danger;
}

QLineEdit[ccRole="field"],
QTextEdit[ccRole="field"],
QPlainTextEdit[ccRole="field"],
QComboBox[ccRole="field"] {
    min-height: 32px; padding: 0 10px; color: @text_primary;
    background: @bg_input; border: 2px solid @border_primary; border-radius: 6px;
    selection-background-color: @bg_selected; selection-color: @text_primary;
}

QTextEdit[ccRole="field"], QPlainTextEdit[ccRole="field"] { padding: 8px 10px; }

QLineEdit[ccRole="field"]:hover:!disabled,
QTextEdit[ccRole="field"]:hover:!disabled,
QPlainTextEdit[ccRole="field"]:hover:!disabled,
QComboBox[ccRole="field"]:hover:!disabled { border-color: @border_strong; }

QLineEdit[ccRole="field"]:focus:!disabled,
QTextEdit[ccRole="field"]:focus:!disabled,
QPlainTextEdit[ccRole="field"]:focus:!disabled,
QComboBox[ccRole="field"]:focus:!disabled { border-color: @border_focus; }

QLineEdit[ccRole="field"]:disabled,
QTextEdit[ccRole="field"]:disabled,
QPlainTextEdit[ccRole="field"]:disabled,
QComboBox[ccRole="field"]:disabled {
    color: @text_disabled; background: @bg_disabled; border-color: @border_subtle;
}

QLineEdit[ccRole="field"][ccState="error"],
QTextEdit[ccRole="field"][ccState="error"],
QPlainTextEdit[ccRole="field"][ccState="error"],
QComboBox[ccRole="field"][ccState="error"] { border-color: @danger; }

QFrame[ccRole="sidebar"] {
    min-width: 64px; max-width: 64px; background: @bg_sidebar;
    border: none; border-right: 1px solid @border_subtle;
}

QWidget[ccRole="tabStrip"] {
    min-height: 40px; max-height: 40px; background: @bg_primary;
    border-bottom: 1px solid @border_subtle;
}

QToolButton[ccRole="tabClose"] {
    min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;
    padding: 0; color: @text_secondary; background: @transparent;
    border: 1px solid @transparent; border-radius: 6px;
}

QToolButton[ccRole="tabClose"]:hover:!disabled {
    color: @danger; background: @danger_subtle; border-color: @transparent;
}

QFrame[ccRole="toolbar"] {
    min-height: 72px; max-height: 72px; background: @bg_surface;
    border: none; border-bottom: 1px solid @border_subtle;
}

QFrame[ccRole="keyboardPanel"] {
    background: @bg_surface_alt; border: 1px solid @border_subtle; border-radius: 8px;
}

QFrame[ccRole="infoCard"] {
    background: @bg_surface; border: 1px solid @border_subtle; border-radius: 10px;
}

QFrame[ccRole="infoCard"]:hover { border-color: @border_primary; }

QFrame[ccRole="infoCard"][ccState="loading"] { border-color: @info; }

QFrame[ccRole="infoCard"][ccState="timeout"] {
    background: @warning_subtle; border-color: @warning;
}

QFrame[ccRole="infoCard"][ccState="error"] {
    background: @danger_subtle; border-color: @danger;
}

QLabel[ccRole="infoCardTitle"] { color: @text_primary; font-size: 10pt; font-weight: 600; }

QStatusBar[ccRole="statusBar"] {
    min-height: 32px; max-height: 32px; color: @text_secondary;
    background: @bg_surface; border: none; border-top: 1px solid @border_subtle;
}

QMenu {
    padding: 6px; color: @text_primary; background: @bg_raised;
    border: 1px solid @border_primary; border-radius: 10px;
}

QMenu::item {
    min-height: 32px; padding: 0 26px 0 10px; color: @text_primary;
    background: @transparent; border-radius: 6px;
}

QMenu::item:selected { background: @bg_hover; }

QMenu::item:checked { color: @accent; background: @bg_selected; }

QMenu::item:disabled { color: @text_disabled; background: @bg_disabled; }

QMenu::separator { height: 1px; margin: 6px 4px; background: @border_subtle; }

QListView, QTreeView, QListWidget {
    color: @text_primary; background: @bg_surface;
    border: 1px solid @border_subtle; border-radius: 8px; outline: none;
}

QListView::item, QTreeView::item, QListWidget::item {
    min-height: 32px; padding: 0 8px; color: @text_primary;
    background: @transparent; border-radius: 6px;
}

QListView::item:hover, QTreeView::item:hover, QListWidget::item:hover {
    background: @bg_hover;
}

QListView::item:selected, QTreeView::item:selected, QListWidget::item:selected {
    color: @text_primary; background: @bg_selected;
}

QTableView {
    color: @text_primary; background: @bg_surface;
    alternate-background-color: @bg_surface_alt; gridline-color: @border_subtle;
    border: 1px solid @border_subtle; border-radius: 8px;
    selection-background-color: @bg_selected; selection-color: @text_primary;
}

QTableView::item { min-height: 32px; padding: 0 8px;
    border-bottom: 1px solid @border_subtle; }

QTableView::item:hover { background: @bg_hover; }

QTableView::item:selected { color: @text_primary; background: @bg_selected; }

QHeaderView::section {
    min-height: 34px; padding: 0 8px; color: @text_secondary;
    background: @bg_surface_alt; border: none;
    border-right: 1px solid @border_subtle;
    border-bottom: 1px solid @border_primary; font-weight: 600;
}

QHeaderView::section:hover { color: @text_primary; background: @bg_hover; }

QPlainTextEdit[ccRole="logViewer"],
QPlainTextEdit[ccRole="sqlConsole"] {
    padding: 10px 12px; color: @text_primary; background: @bg_code;
    border: 1px solid @border_subtle; border-radius: 8px;
    selection-background-color: @bg_selected; selection-color: @text_primary;
    font-family: "Cascadia Mono", "Consolas"; font-size: 9pt;
}

QPlainTextEdit[ccRole="logViewer"]:focus,
QPlainTextEdit[ccRole="sqlConsole"]:focus { border-color: @border_focus; }

QTextBrowser { color: @text_primary; background: @bg_surface; border: none; }

QScrollBar:vertical { width: 12px; margin: 4px 2px; background: @transparent; }

QScrollBar::handle:vertical { min-height: 28px; background: @scrollbar;
    border-radius: 4px; }

QScrollBar::handle:vertical:hover { background: @scrollbar_hover; }

QScrollBar:horizontal { height: 12px; margin: 2px 4px; background: @transparent; }

QScrollBar::handle:horizontal { min-width: 28px; background: @scrollbar;
    border-radius: 4px; }

QScrollBar::handle:horizontal:hover { background: @scrollbar_hover; }

QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: @transparent; border: none;
}

QSplitter::handle { background: @border_subtle; }

QSplitter::handle:hover { background: @border_strong; }

QToolTip {
    padding: 6px 8px; color: @text_primary; background: @bg_raised;
    border: 1px solid @border_primary; border-radius: 6px;
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
            color as _tc,
        )
        from cashcontrol.gui.theme_helper import (
            render_theme_tokens,
        )
        qss = self._build_qss(_tc)
        qss = render_theme_tokens(qss, isDarkTheme())
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

        # ── Fluent Data Surface (ai/gpt-5.6-terra-xhigh.txt §5) ──────
        qss = common + theme_style + CORE_QSS
        from cashcontrol.gui.theme_helper import render_theme_tokens

        return render_theme_tokens(qss, dark)
