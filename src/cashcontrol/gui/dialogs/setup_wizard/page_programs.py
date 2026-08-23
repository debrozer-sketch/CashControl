from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWizardPage
from qfluentwidgets import BodyLabel, LineEdit, PushButton, SubtitleLabel

from cashcontrol.infrastructure.path_resolver import get_soft_dir


class ProgramsPage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Внешние программы")
        self.setSubTitle("Укажите пути к вспомогательным программам")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 20, 40, 20)

        layout.addWidget(SubtitleLabel("Пути к программам", self))

        self.kitty_row = self._path_row("KiTTY:", "kitty.exe", "kitty.exe")
        layout.addLayout(self.kitty_row)

        self.vnc_row = self._path_row("VNC:", "vncviewer_new.exe", "vncviewer_new.exe")
        layout.addLayout(self.vnc_row)

        self.winscp_row = self._path_row("WinSCP:", "WinSCP.exe", "WinSCP.exe")
        layout.addLayout(self.winscp_row)

        auto_btn = PushButton("Автопоиск", self)
        auto_btn.clicked.connect(self._auto_find)
        layout.addWidget(auto_btn)

        layout.addStretch()

    def _path_row(self, label: str, placeholder: str, default_name: str):
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label)
        lbl.setFixedWidth(60)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        edit = LineEdit(self)
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        browse_btn = PushButton("Обзор…", self)
        browse_btn.clicked.connect(lambda: self._browse(edit))
        default_btn = PushButton("По умолчанию", self)
        default_btn.clicked.connect(lambda: self._set_default(edit, default_name))
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        row.addWidget(browse_btn)
        row.addWidget(default_btn)
        return row

    def _browse(self, edit: LineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите программу", edit.text() or "")
        if path:
            edit.setText(path)

    def _set_default(self, edit: LineEdit, name: str) -> None:
        default = get_soft_dir() / name
        if default.exists():
            edit.setText(str(default))

    def _auto_find(self) -> None:
        soft_dir = get_soft_dir()
        defaults = {
            "kitty.exe": self._find_row(0),
            "vncviewer_new.exe": self._find_row(1),
            "WinSCP.exe": self._find_row(2),
        }
        for name, edit in defaults.items():
            candidate = soft_dir / name
            if candidate.exists() and not edit.text().strip():
                edit.setText(str(candidate))

    def _find_row(self, index: int):
        rows = [self.kitty_row, self.vnc_row, self.winscp_row]
        if 0 <= index < len(rows):
            for i in range(rows[index].count()):
                w = rows[index].itemAt(i).widget()
                if isinstance(w, LineEdit):
                    return w
        return None
