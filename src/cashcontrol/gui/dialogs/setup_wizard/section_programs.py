"""Пути к вспомогательным программам для окна первоначальной настройки.

Раньше это была страница ``QWizard``. Окно настройки стало одним экраном,
поэтому класс — обычная карточка. Имена методов (``_auto_find``,
``_find_row``, ``load``, ``save``, ``status_text``) оставлены прежними: на них
завязаны и тесты, и сам диалог.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QSizePolicy, QVBoxLayout
from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PushButton, SubtitleLabel

from cashcontrol.gui.theme_helper import _label_minimum
from cashcontrol.infrastructure.config_manager import (
    SSH_CLIENT_NAMES,
    VNC_CLIENT_NAMES,
    WINSCP_CLIENT_NAMES,
)
from cashcontrol.infrastructure.path_resolver import find_soft_program

# «KiTTY:», «VNC:», «WinSCP:» — короткие подписи, колонка настроек (220) им не нужна.
_LABEL_W = 80

# Порядок строк зафиксирован списком: индексы используются в load/save и в
# автопоиске, и разъезжаться они больше не должны.
_ROW_LABELS = (
    ("KiTTY:", "kitty", SSH_CLIENT_NAMES),
    ("VNC:", "vncviewer_new", VNC_CLIENT_NAMES),
    ("WinSCP:", "WinSCP", WINSCP_CLIENT_NAMES),
)


class ProgramsSection(CardWidget):
    """Пути к KiTTY, VNC и WinSCP."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._edits: list[LineEdit] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("Внешние программы", self))

        for label, placeholder, names in _ROW_LABELS:
            layout.addLayout(self._path_row(label, placeholder, names))

        auto_btn = PushButton("Автопоиск", self)
        auto_btn.clicked.connect(self._auto_find)
        layout.addWidget(auto_btn)

        self._status = BodyLabel("", self)
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        layout.addWidget(self._status)

    def _path_row(
        self, label: str, placeholder: str, names: tuple[str, ...]
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label, self)
        lbl.setMinimumWidth(_label_minimum(lbl, _LABEL_W))
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        edit = LineEdit(self)
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        browse_btn = PushButton("Обзор…", self)
        browse_btn.clicked.connect(lambda: self._browse(edit))
        default_btn = PushButton("По умолчанию", self)
        default_btn.clicked.connect(lambda: self._set_default(edit, names))
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        row.addWidget(browse_btn)
        row.addWidget(default_btn)
        self._edits.append(edit)
        return row

    def _browse(self, edit: LineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите программу", edit.text() or ""
        )
        if path:
            edit.setText(path)

    def _set_default(self, edit: LineEdit, names: tuple[str, ...]) -> None:
        found = find_soft_program(*names)
        if found is not None:
            edit.setText(str(found))
            self._set_status(f"Найдено: {found.name}")
        else:
            self._set_status(f"Не найдено ни одного из: {', '.join(names)}")

    def _auto_find(self) -> None:
        found: list[str] = []
        missing: list[str] = []
        for index, (label, _placeholder, names) in enumerate(_ROW_LABELS):
            edit = self._edits[index]
            candidate = find_soft_program(*names)
            if candidate is None:
                missing.append(label)
                continue
            if not edit.text().strip():
                edit.setText(str(candidate))
                found.append(f"{label} — {candidate.name}")

        parts = []
        if found:
            parts.append("Найдено: " + ", ".join(found))
        if missing:
            parts.append("Не найдено: " + ", ".join(missing))
        self._set_status("; ".join(parts) or "Ничего не найдено")

    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text.strip()))

    def status_text(self) -> str:
        return self._status.text()

    def _find_row(self, index: int) -> LineEdit | None:
        if 0 <= index < len(self._edits):
            return self._edits[index]
        return None

    def load(self, config) -> None:
        p = config.settings.programs
        for index, value in (
            (0, p.ssh_client_path),
            (1, p.vnc_client_path),
            (2, p.winscp_path),
        ):
            edit = self._find_row(index)
            if edit is not None and value:
                edit.setText(value)

    def save(self, config) -> None:
        """Сохранить три выбранных пути.

        Вызывается окном при нажатии «Настроить».
        """
        config.update(
            "programs",
            ssh_client_path=self._find_row(0).text().strip() or None,
            vnc_client_path=self._find_row(1).text().strip() or None,
            winscp_path=self._find_row(2).text().strip() or None,
        )
