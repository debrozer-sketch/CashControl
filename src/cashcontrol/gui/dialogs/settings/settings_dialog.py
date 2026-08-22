"""Unified settings dialog with tabbed categories."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTabWidget, QVBoxLayout

from cashcontrol.gui.dialogs.settings.tab_connection import TabConnection
from cashcontrol.gui.dialogs.settings.tab_general import TabGeneral
from cashcontrol.gui.dialogs.settings.tab_logs import TabLogs
from cashcontrol.gui.dialogs.settings.tab_programs import TabPrograms
from cashcontrol.infrastructure.audit_logger import audit_log
from cashcontrol.infrastructure.config_manager import ConfigManager


class SettingsDialog(QDialog):
    """Single dialog with all settings organized in tabs."""

    def __init__(self, parent=None, start_tab: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(740)
        self.setMinimumHeight(600)
        self.resize(780, 680)

        self._config = ConfigManager()

        self._tabs = QTabWidget(self)
        self._tab_conn = TabConnection(self)
        self._tab_prog = TabPrograms(self)
        self._tab_general = TabGeneral(self)
        self._tab_logs = TabLogs(self)

        self._tabs.addTab(self._tab_conn, "Подключение")
        self._tabs.addTab(self._tab_prog, "Программы")
        self._tabs.addTab(self._tab_general, "Общие")
        self._tabs.addTab(self._tab_logs, "Логи")
        self._tabs.setCurrentIndex(start_tab)

        btn_box = QDialogButtonBox(self)
        self._save_btn = btn_box.addButton("Сохранить", QDialogButtonBox.ButtonRole.AcceptRole)
        self._apply_btn = btn_box.addButton("Применить", QDialogButtonBox.ButtonRole.ApplyRole)
        self._cancel_btn = btn_box.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)

        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        self._apply_btn.clicked.connect(self._on_apply)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)
        root.addWidget(self._tabs, stretch=1)
        root.addWidget(btn_box)

        self._load_all()

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
            from qfluentwidgets import MessageBox
            MessageBox("Успешно", "Настройки сохранены", self).exec()
            self.accept()

    def _on_apply(self) -> None:
        if self._save_all():
            from qfluentwidgets import MessageBox
            MessageBox("Успешно", "Настройки применены", self).exec()