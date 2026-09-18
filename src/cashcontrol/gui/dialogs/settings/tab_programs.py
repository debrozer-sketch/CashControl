"""Programs settings tab — external tool paths and built-in software options."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    LineEdit,
    SubtitleLabel,
    ToolButton,
)

from cashcontrol.gui.theme_helper import color as _tc

if TYPE_CHECKING:
    from cashcontrol.infrastructure.config_manager import ConfigManager

_IS_LINUX = platform.system() == "Linux"

_LABEL_W = 110
_BTN_SIZE = 32
_ARG_W = 250

_LINUX_SSH_CLIENTS = [
    ("ssh (OpenSSH, по умолчанию)", "ssh"),
    ("kitty", "kitty"),
    ("gnome-terminal", "gnome-terminal"),
    ("konsole", "konsole"),
    ("xterm", "xterm"),
    ("alacritty", "alacritty"),
    ("foot (Wayland)", "foot"),
    ("mate-terminal", "mate-terminal"),
    ("custom...", ""),
]

_LINUX_VNC_CLIENTS = [
    ("remmina", "remmina"),
    ("xtightvncviewer", "xtightvncviewer"),
    ("tightvnc", "tightvnc"),
    ("rdesktop", "rdesktop"),
    ("xfreerdp", "xfreerdp"),
    ("custom...", ""),
]

_EXTERNAL_DEFAULTS = {
    "ssh_args_template": (
        "-- ssh -o StrictHostKeyChecking=no -o PasswordAuthentication=yes"
        " -p {port} {login}@{host}"
    ),
    "vnc_args_template": "{host}:{display}",
    "winscp_args_template": "/open scp://{login}@{host}:{port}",
    "db_args_template": "-h {host} -p {db_port} -U {db_login}",
}


class TabPrograms(QWidget):
    """External program paths and built-in software options."""

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
        inner_layout.setSpacing(8)

        inner_layout.addWidget(self._make_external_card())
        inner_layout.addWidget(self._make_builtin_card())
        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

    def _make_external_card(self) -> CardWidget:
        card = CardWidget(self)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(4)
        layout.addWidget(SubtitleLabel("Внешние программы", card))

        programs = [
            ("SSH-клиент", "ssh_client_path", "ssh_args_template"),
            ("VNC-клиент", "vnc_client_path", "vnc_args_template"),
            ("WinSCP", "winscp_path", "winscp_args_template"),
            ("PostgreSQL", "db_client_path", "db_args_template"),
        ]
        for name, path_key, args_key in programs:
            self._program_row(layout, card, name, path_key, args_key)

        if _IS_LINUX:
            hint = BodyLabel(
                "На Linux программы — системные пакеты (apt install). "
                "Если путь не задан — используется встроенный инструмент.",
                card,
            )
        else:
            hint = BodyLabel(
                "Переменные аргументов: {host} {port} {login} {display} {db_port} {db_login}. "
                "Если путь не задан или файл не найден — используется встроенный инструмент.",
                card,
            )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        layout.addWidget(hint)
        return card

    def _program_row(self, layout: QVBoxLayout, parent: QWidget,
                     name: str, path_key: str, args_key: str) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)

        name_lbl = BodyLabel(name, parent)
        name_lbl.setFixedWidth(_LABEL_W)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        if _IS_LINUX and path_key in ("ssh_client_path", "vnc_client_path"):
            # Linux: dropdown с терминалами (QComboBox из-за бага qfluentwidgets)
            from PySide6.QtWidgets import QComboBox
            combo = QComboBox(parent)
            if path_key == "ssh_client_path":
                for text, _ in _LINUX_SSH_CLIENTS:
                    combo.addItem(text)
            else:
                for text, _ in _LINUX_VNC_CLIENTS:
                    combo.addItem(text)
            combo.setFixedWidth(200)
            combo.setToolTip("Встроенный терминал или SSH-клиент" if path_key == "ssh_client_path" else "Встроенный VNC-клиент или внешний")
            combo.currentTextChanged.connect(
                lambda txt, k=path_key: None  # placeholder
            )
            setattr(self, path_key, combo)
            widget = combo
        else:
            path_edit = LineEdit(parent)
            path_edit.setPlaceholderText("Путь к программе…")
            path_edit.setClearButtonEnabled(True)
            path_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            setattr(self, path_key, path_edit)
            widget = path_edit

        if not _IS_LINUX:
            browse_btn = ToolButton(FluentIcon.FOLDER, parent)
            browse_btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
            browse_btn.setToolTip("Выбрать файл")
            browse_btn.clicked.connect(
                lambda _checked=False, e=widget: self._browse_file(e)
            )

        args_edit = LineEdit(parent)
        args_edit.setFixedWidth(_ARG_W)
        args_edit.setPlaceholderText(_EXTERNAL_DEFAULTS[args_key])
        args_edit.setClearButtonEnabled(True)
        args_edit.setToolTip("Аргументы запуска (см. описание ниже)")

        row.addWidget(name_lbl)
        row.addWidget(widget, stretch=1)
        if not _IS_LINUX:
            row.addWidget(browse_btn)
        row.addWidget(args_edit)
        layout.addLayout(row)

        setattr(self, args_key, args_edit)

    def _on_linux_combo_changed(self, text: str, path_key: str) -> None:
        """Handle Linux dropdown selection — set executable name."""
        if "custom" in text.lower():
            setattr(self, path_key, LineEdit(self))
            setattr(self, path_key, getattr(self, path_key))

    def _make_builtin_card(self) -> CardWidget:
        card = CardWidget(self)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(6)
        layout.addWidget(SubtitleLabel("Встроенное ПО", card))

        layout.addWidget(self._section_label(card, "Файловый менеджер"))
        fm_row = QHBoxLayout()
        fm_row.setSpacing(6)
        fm_lbl = BodyLabel("Каталог на кассе:", card)
        fm_lbl.setFixedWidth(_LABEL_W)
        fm_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.file_manager_start_dir = LineEdit(card)
        self.file_manager_start_dir.setPlaceholderText("/home/tc/storage")
        self.file_manager_start_dir.setClearButtonEnabled(True)
        self.file_manager_start_dir.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        fm_row.addWidget(fm_lbl)
        fm_row.addWidget(self.file_manager_start_dir, stretch=1)
        layout.addLayout(fm_row)

        layout.addWidget(self._section_label(card, "VNC-просмотр"))
        vnc_row = QHBoxLayout()
        vnc_row.setSpacing(6)
        mode_lbl = BodyLabel("Режим открытия:", card)
        mode_lbl.setFixedWidth(_LABEL_W)
        mode_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.vnc_start_mode = ComboBox(card)
        self.vnc_start_mode.addItems(["Окно", "Полный экран"])
        self.vnc_start_mode.setFixedWidth(150)
        vnc_row.addWidget(mode_lbl)
        vnc_row.addWidget(self.vnc_start_mode)
        vnc_row.addSpacing(8)
        depth_lbl = BodyLabel("Глубина цвета:", card)
        depth_lbl.setFixedWidth(110)
        depth_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.vnc_default_depth = ComboBox(card)
        self.vnc_default_depth.addItems(["8 бит", "16 бит", "32 бита"])
        self.vnc_default_depth.setFixedWidth(120)
        vnc_row.addWidget(depth_lbl)
        vnc_row.addWidget(self.vnc_default_depth)
        vnc_row.addStretch()
        layout.addLayout(vnc_row)

        term_label = self._section_label(card, "SSH-терминал")
        layout.addWidget(term_label)
        hotkeys = BodyLabel(
            "Горячие клавиши: Ctrl+N — новое подключение, Ctrl+W — закрыть вкладку, "
            "Ctrl+Tab — переключение вкладок, Ctrl+Space — выбрать сниппет, "
            "Ctrl++ / Ctrl+- — размер шрифта, Ctrl+0 — сброс, Ctrl+Shift+C/V — копировать/вставить, "
            "Shift+PgUp / Shift+PgDn — прокрутка.",
            card,
        )
        hotkeys.setWordWrap(True)
        hotkeys.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        layout.addWidget(hotkeys)
        return card

    def _section_label(self, parent: QWidget, text: str) -> BodyLabel:
        lbl = BodyLabel(text, parent)
        lbl.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: 11px; font-weight: bold;"
            " margin-top: 2px;"
        )
        return lbl

    def _browse_file(self, line_edit: LineEdit) -> None:
        current = line_edit.text().strip()
        start_dir = str(Path(current).parent) if current else str(Path.home())
        if _IS_LINUX:
            path, _ = QFileDialog.getOpenFileName(
                self, "Выберите программу", start_dir,
                "Все файлы (*.*)",
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Выберите программу", start_dir,
                "Программы (*.exe);;Все файлы (*.*)",
            )
        if path:
            line_edit.setText(path)

    def load(self, config: ConfigManager) -> None:
        p = config.settings.programs
        if _IS_LINUX:
            # Linux: заполняем dropdown
            ssh_val = p.ssh_client_path or "ssh"
            for i, (_, exec_name) in enumerate(_LINUX_SSH_CLIENTS):
                if exec_name == ssh_val:
                    self.ssh_client_path.setCurrentIndex(i)
                    break
            else:
                # custom or not found — use last item
                self.ssh_client_path.setCurrentIndex(len(_LINUX_SSH_CLIENTS) - 1)

            vnc_val = p.vnc_client_path or "remmina"
            for i, (_, exec_name) in enumerate(_LINUX_VNC_CLIENTS):
                if exec_name == vnc_val:
                    self.vnc_client_path.setCurrentIndex(i)
                    break
            else:
                self.vnc_client_path.setCurrentIndex(len(_LINUX_VNC_CLIENTS) - 1)
        else:
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

        b = config.settings.builtin
        self.file_manager_start_dir.setText(b.file_manager_start_dir or "/home/tc/storage")
        self.vnc_start_mode.setCurrentIndex(
            {"window": 0, "fullscreen": 1}.get(b.vnc_start_mode, 0)
        )
        self.vnc_default_depth.setCurrentIndex(
            {8: 0, 16: 1, 32: 2}.get(b.vnc_default_depth, 2)
        )

    def save(self, config: ConfigManager) -> None:
        if _IS_LINUX:
            # Linux: извлекаем executable из dropdown
            ssh_combo = self.ssh_client_path
            ssh_text = ssh_combo.currentText()
            ssh_exec = None
            for _, exec_name in _LINUX_SSH_CLIENTS:
                if ssh_text.startswith(f"{exec_name} ("):
                    ssh_exec = exec_name
                    break
            else:
                ssh_exec = None  # custom or unknown

            vnc_combo = self.vnc_client_path
            vnc_text = vnc_combo.currentText()
            vnc_exec = None
            for _, exec_name in _LINUX_VNC_CLIENTS:
                if vnc_text.startswith(f"{exec_name} ("):
                    vnc_exec = exec_name
                    break
            else:
                vnc_exec = None

            config.update(
                "programs",
                ssh_client_path=ssh_exec,
                vnc_client_path=vnc_exec,
                winscp_path=None,
                db_client_path=self.db_client_path.text().strip() or None,
                ssh_args_template=self.ssh_args_template.text().strip()
                or _EXTERNAL_DEFAULTS["ssh_args_template"],
                vnc_args_template=self.vnc_args_template.text().strip()
                or _EXTERNAL_DEFAULTS["vnc_args_template"],
                winscp_args_template=self.winscp_args_template.text().strip()
                or _EXTERNAL_DEFAULTS["winscp_args_template"],
                db_args_template=self.db_args_template.text().strip()
                or _EXTERNAL_DEFAULTS["db_args_template"],
            )
        else:
            config.update(
                "programs",
                ssh_client_path=self.ssh_client_path.text().strip() or None,
                vnc_client_path=self.vnc_client_path.text().strip() or None,
                winscp_path=self.winscp_path.text().strip() or None,
                db_client_path=self.db_client_path.text().strip() or None,
                ssh_args_template=self.ssh_args_template.text().strip()
                or _EXTERNAL_DEFAULTS["ssh_args_template"],
                vnc_args_template=self.vnc_args_template.text().strip()
                or _EXTERNAL_DEFAULTS["vnc_args_template"],
                winscp_args_template=self.winscp_args_template.text().strip()
                or _EXTERNAL_DEFAULTS["winscp_args_template"],
                db_args_template=self.db_args_template.text().strip()
                or _EXTERNAL_DEFAULTS["db_args_template"],
            )
        config.update(
            "builtin",
            file_manager_start_dir=self.file_manager_start_dir.text().strip() or "/home/tc/storage",
            vnc_start_mode=["window", "fullscreen"][self.vnc_start_mode.currentIndex()],
            vnc_default_depth=[8, 16, 32][self.vnc_default_depth.currentIndex()],
        )

