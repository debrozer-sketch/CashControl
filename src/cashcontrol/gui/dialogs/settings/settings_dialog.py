"""Unified settings dialog with sidebar navigation."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
)
from qfluentwidgets import FluentIcon, PrimaryPushButton, PushButton

from cashcontrol.gui.dialogs.settings.tab_connection import TabConnection
from cashcontrol.gui.dialogs.settings.tab_general import TabGeneral
from cashcontrol.gui.dialogs.settings.tab_logs import TabLogs
from cashcontrol.gui.dialogs.settings.tab_programs import TabPrograms
from cashcontrol.infrastructure.audit_logger import audit_log
from cashcontrol.infrastructure.config_manager import ConfigManager

_PAGES = [
    (FluentIcon.LINK, "Подключение"),
    (FluentIcon.APPLICATION, "Программы"),
    (FluentIcon.SETTING, "Общие"),
    (FluentIcon.DOCUMENT, "Логи"),
]


class SettingsDialog(QDialog):
    """Single dialog with settings organized as a left-side menu."""

    def __init__(self, parent=None, start_tab: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(740)
        self.setMinimumHeight(560)
        self.resize(780, 620)

        self._config = ConfigManager()

        self._stack = QStackedWidget(self)
        self._tab_conn = TabConnection(self)
        self._tab_prog = TabPrograms(self)
        self._tab_general = TabGeneral(self)
        self._tab_logs = TabLogs(self)
        for page in (self._tab_conn, self._tab_prog, self._tab_general, self._tab_logs):
            self._stack.addWidget(page)

        self._menu = QListWidget(self)
        self._menu.setFixedWidth(176)
        self._menu.setIconSize(QSize(18, 18))
        self._menu.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._menu.setStyleSheet(
            "QListWidget::item { min-height: 34px; padding: 0 10px;"
            " margin: 2px 4px; border-radius: 6px; }"
        )
        for icon, title in _PAGES:
            self._menu.addItem(QListWidgetItem(icon.icon(), title))
        self._menu.setCurrentRow(start_tab)
        self._menu.currentRowChanged.connect(self._stack.setCurrentIndex)

        from cashcontrol.gui.theme_engine import ThemeEngine
        ThemeEngine.instance().theme_changed.connect(self._refresh_menu_icons)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        self._save_btn = PrimaryPushButton("Сохранить", self)
        self._apply_btn = PushButton("Применить", self)
        self._cancel_btn = PushButton("Отмена", self)
        for b in (self._save_btn, self._apply_btn, self._cancel_btn):
            b.setFixedWidth(120)
            btn_row.addWidget(b)

        self._save_btn.clicked.connect(self._on_save)
        self._cancel_btn.clicked.connect(self.reject)
        self._apply_btn.clicked.connect(self._on_apply)

        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._menu)
        body.addWidget(self._stack, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)
        root.addLayout(body, stretch=1)
        root.addLayout(btn_row)

        self._load_all()

    def _refresh_menu_icons(self, _theme: str = "") -> None:
        for i, (icon, _title) in enumerate(_PAGES):
            item = self._menu.item(i)
            if item is not None:
                item.setIcon(icon.icon())

    def _load_all(self) -> None:
        self._tab_conn.load(self._config)
        self._tab_prog.load(self._config)
        self._tab_general.load(self._config)
        self._tab_logs.load(self._config)

    def _save_all(self) -> bool:
        try:
            self._tab_conn.save(self._config)
            self._tab_prog.save(self._config)
            self._tab_general.save(self._config)
            self._tab_logs.save(self._config)
            self._config.save()
            return True
        except Exception as e:
            from qfluentwidgets import MessageBox
            MessageBox("Ошибка", f"Не удалось сохранить настройки:\n{e}", self).exec()
            return False

    def _on_save(self) -> None:
        if self._save_all():
            audit_log(action_type="settings", action_name="update_settings", result="success")
            from qfluentwidgets import InfoBar, InfoBarPosition
            parent = self.parent() or self
            InfoBar.success(title="Сохранено", content="Настройки сохранены",
                            parent=parent, position=InfoBarPosition.TOP_RIGHT,
                            duration=2000)
            self.accept()

    def _on_apply(self) -> None:
        if self._save_all():
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success(title="Сохранено", content="Настройки применены",
                            parent=self, position=InfoBarPosition.TOP_RIGHT,
                            duration=2000)
