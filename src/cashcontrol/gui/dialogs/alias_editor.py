from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel

from cashcontrol.core.aliases.alias_manager import get_alias_manager


class AliasEditorDialog(QDialog):
    def __init__(
        self,
        alias_key: str,
        current_value: str,
        builtin_value: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Справочник оборудования")
        self.setFixedWidth(420)
        self._key = alias_key

        am = get_alias_manager()

        current_lbl = BodyLabel(f"Текущее значение: {current_value}")
        current_lbl.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(current_lbl)

        if builtin_value:
            builtin_lbl = BodyLabel(f"Из встроенного справочника: {builtin_value}")
            builtin_lbl.setWordWrap(True)
            layout.addWidget(builtin_lbl)

        layout.addSpacing(8)
        layout.addWidget(QLabel("Новое название:"))

        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("Введите название оборудования...")
        if am.has_alias(alias_key):
            self._name_edit.setText(am.resolve(alias_key))
        else:
            self._name_edit.setText(current_value)
        self._name_edit.selectAll()
        layout.addWidget(self._name_edit)

        hint = QLabel(
            "Это название будет использоваться во всей программе "
            "для данного оборудования."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setPlaceholderText("Введите название!")
            return
        get_alias_manager().set_alias(self._key, name)
        self.accept()