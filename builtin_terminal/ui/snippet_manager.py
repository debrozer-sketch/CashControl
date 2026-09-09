"""Менеджер сниппетов: таблица + добавление/редактирование/удаление."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from data.snippets import Snippet, SnippetStore


class _SnippetEditDialog(QDialog):
    """Диалог добавления/правки одного сниппета."""

    def __init__(self, snippet: Optional[Snippet] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сниппет" if snippet else "Новый сниппет")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.edit_name = QLineEdit(snippet.name if snippet else "")
        self.edit_name.setPlaceholderText("Например: docker ps")
        form.addRow("Имя:", self.edit_name)

        self.edit_tags = QLineEdit(" ".join(snippet.tags) if snippet else "")
        self.edit_tags.setPlaceholderText("docker mon (через пробел)")
        form.addRow("Теги:", self.edit_tags)

        self.edit_description = QLineEdit(snippet.description if snippet else "")
        self.edit_description.setPlaceholderText("Необязательно")
        form.addRow("Описание:", self.edit_description)

        self.edit_command = QPlainTextEdit(snippet.command if snippet else "")
        self.edit_command.setPlaceholderText("docker ps --format 'table {{.Names}}\\t{{.Status}}'")
        self.edit_command.setFixedHeight(90)
        form.addRow("Команда:", self.edit_command)

        self.check_enter = QCheckBox("Отправлять с Enter (иначе — только вставить)")
        self.check_enter.setChecked(snippet.send_with_enter if snippet else True)
        form.addRow("", self.check_enter)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_snippet(self) -> Optional[Snippet]:
        name = self.edit_name.text().strip()
        command = self.edit_command.toPlainText().strip()
        if not name or not command:
            return None
        tags = [t for t in self.edit_tags.text().split() if t]
        return Snippet(
            name=name,
            command=command,
            description=self.edit_description.text().strip(),
            tags=tags,
            send_with_enter=self.check_enter.isChecked(),
        )


class SnippetManagerDialog(QDialog):
    def __init__(self, store: SnippetStore, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Сниппеты")
        self.resize(560, 420)

        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Добавить…")
        btn_add.clicked.connect(self._add)
        btn_edit = QPushButton("Изменить…")
        btn_edit.clicked.connect(self._edit)
        btn_del = QPushButton("Удалить")
        btn_del.clicked.connect(self._delete)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_del)
        layout.addLayout(btn_row)

        self.list_widget.itemDoubleClicked.connect(lambda *_: self._edit())
        self._reload()

    def _reload(self) -> None:
        self.list_widget.clear()
        for s in self._store.all():
            label = s.name
            if s.tags:
                label += f"   [{', '.join(s.tags)}]"
            hint = s.description or (s.command[:60] + "…" if len(s.command) > 60 else s.command)
            self.list_widget.addItem(f"{label}\n    {hint}")

    def _add(self) -> None:
        dlg = _SnippetEditDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            snip = dlg.result_snippet()
            if snip:
                self._store.upsert(snip)
                self._reload()

    def _edit(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        snip = self._store.all()[row]
        dlg = _SnippetEditDialog(snip, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.result_snippet()
            if updated:
                if updated.name != snip.name:
                    self._store.delete(snip.name)
                self._store.upsert(updated)
                self._reload()

    def _delete(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        snip = self._store.all()[row]
        self._store.delete(snip.name)
        self._reload()
