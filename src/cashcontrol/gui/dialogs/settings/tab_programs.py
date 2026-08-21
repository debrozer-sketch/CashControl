"""Programs settings tab — external tool paths and args."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    LineEdit,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
)

from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()
_LABEL_W = 90
_BTN_SIZE = 32


class TabPrograms(QWidget):
    """External program paths and argument templates."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(4, 4, 8, 4)
        inner_layout.setSpacing(10)

        inner_layout.addWidget(self._make_ssh_card())
        inner_layout.addWidget(self._make_card(
            "VNC Клиент", "Просмотр удалённого рабочего стола",
            "vnc_client_path", "vnc_args_template",
            ["TightVNC:  {host}:{display}", "UltraVNC:  {host}::{port_vnc}",
             "RealVNC:   {host}:{display}"],
        ))
        inner_layout.addWidget(self._make_winscp_card())
        inner_layout.addWidget(self._make_card(
            "PostgreSQL Клиент", "Клиент для работы с базой данных кассы",
            "db_client_path", "db_args_template",
            ["psql:      -h {host} -p {db_port} -U {db_login}",
             "DBeaver:   Путь + аргументы зависят от версии"],
        ))
        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

    def _make_ssh_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("SSH Клиент (KiTTY)", card))

        desc = BodyLabel(
            "KiTTY автоматически подключается с паролем из настроек подключения.\n"
            "Укажите путь к kitty.exe или оставьте пустым (будет использован soft/kitty.exe).",
            card,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        layout.addWidget(desc)

        row = QHBoxLayout()
        lbl = BodyLabel("Путь:", card)
        lbl.setFixedWidth(_LABEL_W)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.ssh_client_path = LineEdit(card)
        self.ssh_client_path.setClearButtonEnabled(True)
        self.ssh_client_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        browse_btn = ToolButton(FluentIcon.FOLDER, card)
        browse_btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
        browse_btn.setToolTip("Выбрать файл")
        browse_btn.clicked.connect(lambda: self._browse_file(self.ssh_client_path))

        row.addWidget(lbl)
        row.addWidget(self.ssh_client_path, stretch=1)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        self.ssh_args_template = LineEdit(card)
        self.ssh_args_template.hide()
        return card

    def _make_winscp_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("WinSCP", card))

        desc = BodyLabel(
            "WinSCP запускается автоматически с нужным протоколом:\n"
            "TinyCore → SCP, Ubuntu → SFTP. Пароль берётся из настроек подключения.",
            card,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        layout.addWidget(desc)

        row = QHBoxLayout()
        lbl = BodyLabel("Путь:", card)
        lbl.setFixedWidth(_LABEL_W)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.winscp_path = LineEdit(card)
        self.winscp_path.setClearButtonEnabled(True)
        self.winscp_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        browse_btn = ToolButton(FluentIcon.FOLDER, card)
        browse_btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
        browse_btn.setToolTip("Выбрать файл")
        browse_btn.clicked.connect(lambda: self._browse_file(self.winscp_path))

        row.addWidget(lbl)
        row.addWidget(self.winscp_path, stretch=1)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        self.winscp_args_template = LineEdit(card)
        self.winscp_args_template.hide()
        return card

    def _make_card(self, title: str, description: str,
                   path_key: str, args_key: str, examples: list[str]) -> CardWidget:
        card = CardWidget(self)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel(title, card))

        desc_label = BodyLabel(description, card)
        desc_label.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        layout.addWidget(desc_label)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_lbl = BodyLabel("Путь:", card)
        path_lbl.setFixedWidth(_LABEL_W)
        path_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        path_row.addWidget(path_lbl)

        path_edit = LineEdit(card)
        path_edit.setPlaceholderText("Путь к .exe файлу программы\u2026")
        path_edit.setClearButtonEnabled(True)
        path_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        path_row.addWidget(path_edit, stretch=1)

        browse_btn = ToolButton(FluentIcon.FOLDER, card)
        browse_btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
        browse_btn.setToolTip("Выбрать файл")
        browse_btn.clicked.connect(lambda _checked=False, e=path_edit: self._browse_file(e))
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        args_row = QHBoxLayout()
        args_row.setSpacing(6)
        args_lbl = BodyLabel("Аргументы:", card)
        args_lbl.setFixedWidth(_LABEL_W)
        args_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        args_row.addWidget(args_lbl)

        args_edit = LineEdit(card)
        args_edit.setClearButtonEnabled(True)
        args_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        args_row.addWidget(args_edit, stretch=1)

        spacer = QWidget(card)
        spacer.setFixedSize(_BTN_SIZE, _BTN_SIZE)
        args_row.addWidget(spacer)
        layout.addLayout(args_row)

        vars_hint = BodyLabel(
            "Переменные: {host} {port} {login} {display} {db_port} {db_login}",
            card,
        )
        vars_hint.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 10px;")
        layout.addWidget(vars_hint)

        if examples:
            ex_label = QLabel("Примеры:", card)
            ex_label.setStyleSheet(
                f"color: {_tc('text_tertiary')}; font-size: 10px; font-style: italic; margin-top: 2px;"
            )
            layout.addWidget(ex_label)
            for ex in examples:
                ex_line = QLabel(f"  {ex}", card)
                ex_line.setStyleSheet(
                    f"color: {_tc('text_tertiary')}; font-size: 10px; font-family: monospace;"
                )
                layout.addWidget(ex_line)

        setattr(self, path_key, path_edit)
        setattr(self, args_key, args_edit)
        return card

    def _browse_file(self, line_edit: LineEdit) -> None:
        current = line_edit.text().strip()
        start_dir = str(Path(current).parent) if current else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите программу", start_dir,
            "Программы (*.exe);;Все файлы (*.*)",
        )
        if path:
            line_edit.setText(path)

    def load(self, config: ConfigManager) -> None:
        p = config.settings.programs
        self.ssh_client_path.setText(p.ssh_client_path or "")
        self.vnc_client_path.setText(p.vnc_client_path or "")
        self.winscp_path.setText(p.winscp_path or "")
        self.db_client_path.setText(p.db_client_path or "")
        self.ssh_client_path.setPlaceholderText(p.get_ssh_client())
        self.vnc_client_path.setPlaceholderText(p.get_vnc_client())
        self.winscp_path.setPlaceholderText(p.get_winscp())
        self.ssh_args_template.setText(p.ssh_args_template)
        self.vnc_args_template.setText(p.vnc_args_template)
        self.winscp_args_template.setText(p.winscp_args_template)
        self.db_args_template.setText(p.db_args_template)

    def save(self, config: ConfigManager) -> None:
        defaults = {
            "ssh_args_template": "-- ssh -o StrictHostKeyChecking=no -o PasswordAuthentication=yes -p {port} {login}@{host}",
            "vnc_args_template": "{host}:{display}",
            "winscp_args_template": "/open scp://{login}@{host}:{port}",
            "db_args_template": "-h {host} -p {db_port} -U {db_login}",
        }
        config.update(
            "programs",
            ssh_client_path=self.ssh_client_path.text().strip() or None,
            vnc_client_path=self.vnc_client_path.text().strip() or None,
            winscp_path=self.winscp_path.text().strip() or None,
            db_client_path=self.db_client_path.text().strip() or None,
            ssh_args_template=self.ssh_args_template.text().strip() or defaults["ssh_args_template"],
            vnc_args_template=self.vnc_args_template.text().strip() or defaults["vnc_args_template"],
            winscp_args_template=self.winscp_args_template.text().strip() or defaults["winscp_args_template"],
            db_args_template=self.db_args_template.text().strip() or defaults["db_args_template"],
        )