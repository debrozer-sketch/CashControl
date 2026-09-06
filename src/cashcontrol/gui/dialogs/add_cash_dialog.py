"""
Add cash dialog — compact IP input for new tab.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout
from qfluentwidgets import BodyLabel, FluentIcon, LineEdit, PrimaryPushButton, PushButton


class AddCashDialog(QDialog):
    """Simple dialog for entering a POS terminal IP address."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Добавить кассу")
        self.setFixedSize(360, 104)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._ip_value = ""
        self._init_ui()

    def _init_ui(self) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = BodyLabel("IP-адрес кассы:", self)
        label.setFixedWidth(100)
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self._ip_input = LineEdit(self)
        self._ip_input.setPlaceholderText("192.168.1.10")
        self._ip_input.setClearButtonEnabled(True)
        self._ip_input.returnPressed.connect(self._on_ok)
        self._ip_input.textEdited.connect(self._sanitize_comma)
        row.addWidget(label)
        row.addWidget(self._ip_input, stretch=1)
        layout.addLayout(row)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        btn_layout.addStretch()

        self._ok_btn = PrimaryPushButton("Добавить", self, FluentIcon.ADD)
        self._ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(self._ok_btn)

        self._cancel_btn = PushButton("Отмена", self)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)

    def _sanitize_comma(self, text: str) -> None:
        """На лету заменить запятую на точку: 192,168,1,1 → 192.168.1.1."""
        if "," not in text:
            return
        pos = self._ip_input.cursorPosition()
        self._ip_input.setText(text.replace(",", "."))
        self._ip_input.setCursorPosition(pos)

    def _on_ok(self) -> None:
        """Validate and accept the dialog."""
        ip = self._ip_input.text().strip().replace(",", ".")

        if not ip:
            return

        # Basic IP validation (or hostname)
        ip_pattern = re.compile(
            r"^(\d{1,3}\.){3}\d{1,3}$"
        )
        if not ip_pattern.match(ip) and not self._is_valid_hostname(ip):
            self._ip_input.setFocus()
            return

        if ip_pattern.match(ip):
            # Validate each octet
            parts = ip.split(".")
            if any(int(p) > 255 for p in parts):
                self._ip_input.setFocus()
                return

        self._ip_value = ip
        self.accept()

    @staticmethod
    def _is_valid_hostname(hostname: str) -> bool:
        """Basic hostname validation."""
        if len(hostname) > 255:
            return False
        return bool(re.match(r"^[a-zA-Z0-9._-]+$", hostname))

    def get_ip(self) -> str:
        """Return the entered IP address."""
        return self._ip_value
