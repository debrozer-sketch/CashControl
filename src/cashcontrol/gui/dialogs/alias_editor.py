from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout
from qfluentwidgets import BodyLabel, LineEdit, PrimaryPushButton, PushButton

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        current_lbl = BodyLabel(f"Текущее значение: {current_value}", self)
        current_lbl.setWordWrap(True)
        layout.addWidget(current_lbl)

        if builtin_value:
            builtin_lbl = BodyLabel(
                f"Из встроенного справочника: {builtin_value}", self
            )
            builtin_lbl.setWordWrap(True)
            layout.addWidget(builtin_lbl)

        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel("Новое название:", self)
        lbl.setFixedWidth(120)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self._name_edit = LineEdit(self)
        self._name_edit.setPlaceholderText("Введите название")
        if am.has_alias(alias_key):
            self._name_edit.setText(am.resolve(alias_key))
        else:
            self._name_edit.setText(current_value)
        self._name_edit.selectAll()
        row.addWidget(lbl)
        row.addWidget(self._name_edit, stretch=1)
        layout.addLayout(row)

        hint = BodyLabel(
            "Это название будет использоваться во всей программе "
            "для данного оборудования.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = PrimaryPushButton("Сохранить", self)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = PushButton("Отмена", self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _on_save(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setPlaceholderText("Введите название")
            self._name_edit.setFocus()
            return
        get_alias_manager().set_alias(self._key, name)
        self.accept()
