"""Диалог подключения: host/user/port/password + сохранённые профили."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from data.profiles import HostProfile, ProfileStore


class ConnectDialog(QDialog):
    """Простой PuTTY-подобный диалог входа."""

    def __init__(self, store: ProfileStore, parent: Optional[QDialog] = None) -> None:
        super().__init__(parent)
        self._store = store
        self.profile: Optional[HostProfile] = None

        self.setWindowTitle("Новое подключение")
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)

        # быстрый выбор профиля
        profiles = store.all_profiles()
        if profiles:
            row = QHBoxLayout()
            row.addWidget(QLabel("Профиль:"))
            self.combo_profiles = QComboBox()
            for p in profiles:
                self.combo_profiles.addItem(f"{p.name}  ({p.username}@{p.host}:{p.port})", p)
            self.combo_profiles.currentIndexChanged.connect(self._on_profile_selected)
            row.addWidget(self.combo_profiles, 1)
            layout.addLayout(row)

        form = QFormLayout()
        self.edit_host = QLineEdit()
        self.edit_host.setPlaceholderText("192.168.1.10 или hostname")
        self.edit_port = QLineEdit("22")
        self.edit_port.setFixedWidth(70)
        self.edit_user = QLineEdit("root")
        self.edit_password = QLineEdit()
        self.edit_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("необязательно")

        host_row = QHBoxLayout()
        host_row.addWidget(self.edit_host, 1)
        host_row.addWidget(QLabel(":"))
        host_row.addWidget(self.edit_port)
        form.addRow("Хост", host_row)
        form.addRow("Пользователь", self.edit_user)
        form.addRow("Пароль", self.edit_password)
        form.addRow("Имя профиля", self.edit_name)

        self.check_save = QPushButton("Сохранить профиль")
        self.check_save.setCheckable(True)
        self.check_save.setChecked(True)
        form.addRow("", self.check_save)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.edit_host.setFocus()

    def _on_profile_selected(self, index: int) -> None:
        p: Optional[HostProfile] = self.combo_profiles.itemData(index)
        if p is None:
            return
        self.edit_host.setText(p.host)
        self.edit_port.setText(str(p.port))
        self.edit_user.setText(p.username)
        self.edit_password.setText(p.password or "")
        self.edit_name.setText(p.name if p.name != f"{p.host}:{p.port}" else "")

    def accept(self) -> None:
        host = self.edit_host.text().strip()
        if not host:
            return
        try:
            port = int(self.edit_port.text().strip() or "22")
        except ValueError:
            port = 22
        user = self.edit_user.text().strip() or "root"
        name = self.edit_name.text().strip() or f"{user}@{host}"
        profile = HostProfile(
            name=name,
            host=host,
            username=user,
            port=port,
            password=self.edit_password.text() or None,
        )
        if self.check_save.isChecked():
            self._store.upsert(profile)
        self.profile = profile
        super().accept()
