"""Connection settings tab — SSH, DB, VNC."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    LineEdit,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TextEdit,
)

from cashcontrol.core.security import decrypt_passwords, encrypt_passwords
from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import audit_log, get_logger

if TYPE_CHECKING:
    from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()
_LABEL_W = 120


class TabConnection(QWidget):
    """SSH / DB / VNC connection settings."""

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
        inner_layout.addWidget(self._make_db_card())
        inner_layout.addWidget(self._make_vnc_card())
        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

    def _field_row(self, parent, label_text: str) -> tuple[QHBoxLayout, LineEdit]:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label_text, parent)
        lbl.setFixedWidth(_LABEL_W)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        edit = LineEdit(parent)
        edit.setClearButtonEnabled(True)
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        return row, edit

    def _port_row(self, parent, label_text: str) -> tuple[QHBoxLayout, LineEdit]:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label_text, parent)
        lbl.setFixedWidth(_LABEL_W)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        edit = LineEdit(parent)
        edit.setFixedWidth(90)
        edit.setValidator(QIntValidator(1, 65535))
        row.addWidget(lbl)
        row.addWidget(edit)
        row.addStretch()
        return row, edit

    def _make_ssh_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("SSH Подключение", card))

        login_row, self.ssh_login = self._field_row(card, "Логин:")
        self.ssh_login.setPlaceholderText("tc")
        layout.addLayout(login_row)

        port_row, self.ssh_port = self._port_row(card, "Порт:")
        self.ssh_port.setPlaceholderText("22")
        layout.addLayout(port_row)

        pwd_lbl = StrongBodyLabel("Пароли:", card)
        layout.addWidget(pwd_lbl)
        self.ssh_passwords = TextEdit(card)
        self.ssh_passwords.setPlaceholderText("Введите пароли, по одному на строку")
        self.ssh_passwords.setFixedHeight(110)
        layout.addWidget(self.ssh_passwords)

        ssh_btns = QHBoxLayout()
        self.btn_show_ssh = PushButton("👁 Показать", card)
        self.btn_show_ssh.setFixedHeight(28)
        self.btn_show_ssh.clicked.connect(self._show_ssh_passwords)
        ssh_btns.addWidget(self.btn_show_ssh)
        self.btn_clear_ssh = PushButton("🗑 Очистить пароли SSH", card)
        self.btn_clear_ssh.setFixedHeight(28)
        self.btn_clear_ssh.clicked.connect(self._clear_ssh_passwords)
        ssh_btns.addWidget(self.btn_clear_ssh)
        ssh_btns.addStretch()
        layout.addLayout(ssh_btns)

        hint = BodyLabel("Пароли хранятся в зашифрованном виде", card)
        hint.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        layout.addWidget(hint)
        return card

    def _make_db_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("PostgreSQL База данных", card))

        login_row, self.db_login = self._field_row(card, "Логин:")
        self.db_login.setPlaceholderText("postgres")
        layout.addLayout(login_row)

        port_row, self.db_port = self._port_row(card, "Порт:")
        self.db_port.setPlaceholderText("5432")
        layout.addLayout(port_row)

        pwd_lbl = StrongBodyLabel("Пароли:", card)
        layout.addWidget(pwd_lbl)
        self.db_passwords = TextEdit(card)
        self.db_passwords.setPlaceholderText("Введите пароли БД, по одному на строку")
        self.db_passwords.setFixedHeight(110)
        layout.addWidget(self.db_passwords)

        db_btns = QHBoxLayout()
        self.btn_show_db = PushButton("👁 Показать", card)
        self.btn_show_db.setFixedHeight(28)
        self.btn_show_db.clicked.connect(self._show_db_passwords)
        db_btns.addWidget(self.btn_show_db)
        self.btn_clear_db = PushButton("🗑 Очистить пароли БД", card)
        self.btn_clear_db.setFixedHeight(28)
        self.btn_clear_db.clicked.connect(self._clear_db_passwords)
        db_btns.addWidget(self.btn_clear_db)
        db_btns.addStretch()
        layout.addLayout(db_btns)

        hint = BodyLabel("Если не заданы — используются SSH пароли", card)
        hint.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        layout.addWidget(hint)
        return card

    def _make_vnc_card(self) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("VNC Просмотр", card))

        port_row, self.vnc_port = self._port_row(card, "Порт VNC:")
        self.vnc_port.setPlaceholderText("5900")
        layout.addLayout(port_row)

        # ── Quality ──
        q_row = QHBoxLayout()
        q_row.setSpacing(8)
        q_lbl = BodyLabel("Качество:", card)
        q_lbl.setFixedWidth(_LABEL_W)
        q_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.vnc_quality = ComboBox(card)
        self.vnc_quality.addItems(["Auto", "High", "Medium", "Low", "Custom"])
        self.vnc_quality.setMinimumWidth(140)
        q_row.addWidget(q_lbl)
        q_row.addWidget(self.vnc_quality)
        q_row.addStretch()
        layout.addLayout(q_row)

        # ── Color level ──
        c_row = QHBoxLayout()
        c_row.setSpacing(8)
        c_lbl = BodyLabel("Глубина цвета:", card)
        c_lbl.setFixedWidth(_LABEL_W)
        c_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.vnc_color_level = ComboBox(card)
        self.vnc_color_level.addItems(["rgb111 — 8 цветов", "rgb222 — 64 цвета", "pal8 — 256 цветов", "full — True Color"])
        self.vnc_color_level.setMinimumWidth(200)
        c_row.addWidget(c_lbl)
        c_row.addWidget(self.vnc_color_level)
        c_row.addStretch()
        layout.addLayout(c_row)

        hint = BodyLabel(
            "Настройки применяются при следующем открытии VNC в полном экране.\n"
            "Путь к vncviewer.exe задаётся на вкладке Программы.",
            card,
        )
        hint.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return card

    # ── Show / Clear passwords ─────────────────────────

    def _show_ssh_passwords(self) -> None:
        conn = self._config.settings.connection
        try:
            pwds = decrypt_passwords(conn.ssh_passwords_encrypted)
        except Exception:
            pwds = []
        if pwds:
            self.ssh_passwords.setPlainText("\n".join(pwds))
        else:
            self.ssh_passwords.setPlaceholderText("SSH пароли не заданы")

    def _show_db_passwords(self) -> None:
        conn = self._config.settings.connection
        try:
            pwds = decrypt_passwords(conn.db_passwords_encrypted)
        except Exception:
            pwds = []
        if pwds:
            self.db_passwords.setPlainText("\n".join(pwds))
        else:
            self.db_passwords.setPlaceholderText("Пароли БД не заданы")

    def _clear_ssh_passwords(self) -> None:
        reply = QMessageBox.warning(
            self, "Очистить SSH пароли",
            "Удалить все сохранённые SSH пароли?\nВы не сможете подключаться к кассам.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._config.update("connection", ssh_passwords_encrypted=[])
            self.ssh_passwords.clear()
            self.ssh_passwords.setPlaceholderText("SSH пароли очищены")
            audit_log(action_type="settings", action_name="clear_ssh_passwords", result="success")
            logger.info("SSH passwords cleared by user")

    def _clear_db_passwords(self) -> None:
        reply = QMessageBox.warning(
            self, "Очистить пароли БД",
            "Удалить все сохранённые пароли PostgreSQL?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._config.update("connection", db_passwords_encrypted=[])
            self.db_passwords.clear()
            self.db_passwords.setPlaceholderText("Пароли БД очищены")
            audit_log(action_type="settings", action_name="clear_db_passwords", result="success")
            logger.info("DB passwords cleared by user")

    # ── Load / Save ────────────────────────────────────

    def _set_vnc_color_level(self, val: str) -> None:
        mapping = {"rgb111": 0, "rgb222": 1, "pal8": 2, "full": 3}
        idx = mapping.get(val, 1)
        if 0 <= idx < self.vnc_color_level.count():
            self.vnc_color_level.setCurrentIndex(idx)

    def _get_vnc_color_level(self) -> str:
        mapping = {0: "rgb111", 1: "rgb222", 2: "pal8", 3: "full"}
        return mapping.get(self.vnc_color_level.currentIndex(), "rgb222")

    def load(self, config: ConfigManager) -> None:
        self._config = config
        conn = config.settings.connection

        self.ssh_login.setText(conn.ssh_login)
        self.ssh_port.setText(str(conn.ssh_port))
        self.db_login.setText(conn.db_login)
        self.db_port.setText(str(conn.db_port))
        self.vnc_port.setText(str(conn.vnc_port))

        vnc = config.settings.vnc_preview
        idx = self.vnc_quality.findText(vnc.quality)
        if idx >= 0:
            self.vnc_quality.setCurrentIndex(idx)
        self._set_vnc_color_level(vnc.color_level)

        ssh_count = len(conn.ssh_passwords_encrypted)
        db_count = len(conn.db_passwords_encrypted)

        if ssh_count:
            self.ssh_passwords.setPlaceholderText(
                f"Сохранено {ssh_count} паролей\nОставьте пустым чтобы не менять"
            )
        if db_count:
            self.db_passwords.setPlaceholderText(
                f"Сохранено {db_count} паролей\nОставьте пустым чтобы не менять"
            )

    def save(self, config: ConfigManager) -> None:
        ssh_port = max(1, min(65535, int(self.ssh_port.text() or 22)))
        db_port = max(1, min(65535, int(self.db_port.text() or 5432)))
        vnc_port = max(1, min(65535, int(self.vnc_port.text() or 5900)))

        config.update(
            "connection",
            ssh_login=self.ssh_login.text().strip(),
            ssh_port=ssh_port,
            db_login=self.db_login.text().strip(),
            db_port=db_port,
            vnc_port=vnc_port,
        )

        config.update(
            "vnc_preview",
            quality=self.vnc_quality.currentText(),
            color_level=self._get_vnc_color_level(),
        )

        ssh_text = self.ssh_passwords.toPlainText().strip()
        if ssh_text:
            ssh_pwds = [p.strip() for p in ssh_text.splitlines() if p.strip()]
            if ssh_pwds:
                config.update("connection", ssh_passwords_encrypted=encrypt_passwords(ssh_pwds))
                logger.info(f"Updated {len(ssh_pwds)} SSH passwords")

        db_text = self.db_passwords.toPlainText().strip()
        if db_text:
            db_pwds = [p.strip() for p in db_text.splitlines() if p.strip()]
            if db_pwds:
                config.update("connection", db_passwords_encrypted=encrypt_passwords(db_pwds))
                logger.info(f"Updated {len(db_pwds)} DB passwords")