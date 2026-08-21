"""
Command result dialog — Fluent-style dialog for displaying command output.

Shows the result of executing a cash command:
  - Success/failure status
  - Message
  - Full output text
  - Error details (if any)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CardWidget, SubtitleLabel

if TYPE_CHECKING:
    from cashcontrol.actions_registry import ActionResult


class CommandResultDialog(QDialog):
    """
    Fluent-style dialog displaying the result of a command execution.

    Usage:
        result: ActionResult = await registry.execute_action(...)
        dlg = CommandResultDialog(result, parent=self, title="Перезагрузка ПО")
        dlg.exec()
    """

    def __init__(
        self,
        result: ActionResult,
        parent: QWidget | None = None,
        title: str = "Результат выполнения",
    ) -> None:
        super().__init__(parent)
        self._result = result
        self._title = title
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self.setMinimumHeight(340)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Title ──────────────────────────────────────────────
        title_label = SubtitleLabel(self._title, self)
        root.addWidget(title_label)

        # ── Status card ────────────────────────────────────────
        status_card = CardWidget(self)
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)

        from cashcontrol.gui.theme_helper import color as _tc
        if self._result.success:
            icon_text = "✅"
            status_color = _tc('success')
        else:
            icon_text = "❌"
            status_color = _tc('error')

        icon_label = QLabel(icon_text, status_card)
        icon_label.setStyleSheet("font-size: 24px;")
        status_layout.addWidget(icon_label)

        msg_label = QLabel(self._result.message or ("Успешно" if self._result.success else "Ошибка"))
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"font-size: 14px; color: {status_color}; font-weight: 500;")
        status_layout.addWidget(msg_label, stretch=1)

        root.addWidget(status_card)

        # ── Output ─────────────────────────────────────────────
        output_text = self._build_output_text()
        if output_text:
            output_card = CardWidget(self)
            output_card_layout = QVBoxLayout(output_card)
            output_card_layout.setContentsMargins(12, 10, 12, 10)
            output_card_layout.setSpacing(4)

            out_label = QLabel("Вывод:", output_card)
            out_label.setStyleSheet("font-weight: 600; font-size: 12px;")
            output_card_layout.addWidget(out_label)

            text_edit = QPlainTextEdit(output_card)
            text_edit.setReadOnly(True)
            text_edit.setPlainText(output_text)
            text_edit.setMinimumHeight(120)
            text_edit.setMaximumHeight(260)
            text_edit.setStyleSheet(
                "font-family: monospace; font-size: 12px; background: transparent; border: none;"
            )
            output_card_layout.addWidget(text_edit)
            root.addWidget(output_card, stretch=1)
        else:
            root.addStretch(1)

        # ── Button ─────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def _build_output_text(self) -> str:
        """Build full output text from result."""
        parts: list[str] = []

        if self._result.details:
            output = self._result.details.get("output", "")
            if output and output.strip():
                parts.append(output.strip())

        if self._result.error:
            parts.append(f"ОШИБКА: {self._result.error.strip()}")

        return "\n\n".join(parts)