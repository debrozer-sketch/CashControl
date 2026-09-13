"""Диалог настроек: шрифт, scrollback, поведение копирования."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFontComboBox,
    QSpinBox,
    QVBoxLayout,
)

from data.profiles import ProfileStore


class SettingsDialog(QDialog):
    def __init__(self, store: ProfileStore, parent: Optional[QDialog] = None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.font_combo = QFontComboBox()
        current_font = store.settings.font_family
        if current_font:
            self.font_combo.setCurrentFont(
                self.font_combo.itemData(
                    next(
                        (i for i in range(self.font_combo.count())
                         if self.font_combo.itemText(i) == current_font),
                        0,
                    )
                )
            )
        form.addRow("Шрифт:", self.font_combo)

        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(6.0, 28.0)
        self.size_spin.setSingleStep(0.5)
        self.size_spin.setValue(store.settings.font_size)
        form.addRow("Размер шрифта:", self.size_spin)

        self.scrollback_spin = QSpinBox()
        self.scrollback_spin.setRange(1000, 100000)
        self.scrollback_spin.setSingleStep(1000)
        self.scrollback_spin.setValue(store.settings.scrollback_lines)
        self.scrollback_spin.setToolTip(
            "Сколько строк истории хранить выше видимого экрана"
        )
        form.addRow("Буфер прокрутки:", self.scrollback_spin)

        self.check_copy_select = QCheckBox("Копировать при выделении мышью")
        self.check_copy_select.setChecked(store.settings.copy_on_select)
        self.check_copy_select.setToolTip("Выделил текст — он уже в буфере обмена")
        form.addRow("", self.check_copy_select)

        # TERM: урезанные кассы не знают xterm-256color -> mc без alt-screen.
        # xterm (как PuTTY) — максимальная совместимость
        self.term_combo = QComboBox()
        self.term_combo.addItem("xterm (макс. совместимость, как PuTTY)", "xterm")
        self.term_combo.addItem("xterm-256color (256 цветов)", "xterm-256color")
        idx = 0 if store.settings.term_type == "xterm" else 1
        self.term_combo.setCurrentIndex(idx)
        self.term_combo.setToolTip(
            "Тип терминала для удалённого хоста. Если mc без цветов/рамок или\n"
            "портит экран при выходе — оставь xterm."
        )
        form.addRow("TERM:", self.term_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        s = self._store.settings
        s.font_family = self.font_combo.currentFont().family()
        s.font_size = float(self.size_spin.value())
        s.scrollback_lines = int(self.scrollback_spin.value())
        s.copy_on_select = self.check_copy_select.isChecked()
        s.term_type = self.term_combo.currentData()
        self._store.save_settings()
        super().accept()
