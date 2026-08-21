from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget, QWizardPage
from qfluentwidgets import BodyLabel, LineEdit, StrongBodyLabel, SubtitleLabel, TextEdit


class ConnectionPage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Параметры подключения")
        self.setSubTitle("Настройте SSH и доступ к базе данных")

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 20, 40, 20)

        layout.addWidget(SubtitleLabel("SSH", content))

        row, self.ssh_login = self._field_row("Логин:", content)
        self.ssh_login.setPlaceholderText("tc")
        layout.addLayout(row)

        row, self.ssh_port = self._port_row("Порт:", content)
        self.ssh_port.setPlaceholderText("22")
        layout.addLayout(row)

        pwd_lbl = StrongBodyLabel("Пароли:", content)
        layout.addWidget(pwd_lbl)
        self.ssh_passwords = TextEdit(content)
        self.ssh_passwords.setPlaceholderText("Введите пароли, по одному на строку")
        self.ssh_passwords.setFixedHeight(80)
        layout.addWidget(self.ssh_passwords)

        layout.addWidget(SubtitleLabel("PostgreSQL", content))

        row, self.db_login = self._field_row("Логин:", content)
        self.db_login.setPlaceholderText("postgres")
        layout.addLayout(row)

        row, self.db_port = self._port_row("Порт:", content)
        self.db_port.setPlaceholderText("5432")
        layout.addLayout(row)

        db_pwd_lbl = StrongBodyLabel("Пароли БД:", content)
        layout.addWidget(db_pwd_lbl)
        self.db_passwords = TextEdit(content)
        self.db_passwords.setPlaceholderText("Введите пароли БД, по одному на строку")
        self.db_passwords.setFixedHeight(80)
        layout.addWidget(self.db_passwords)

        layout.addStretch()

        scroll.setWidget(content)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)

        self.registerField("ssh_login", self.ssh_login, "text", self.ssh_login.textChanged)
        self.registerField("ssh_port", self.ssh_port, "text", self.ssh_port.textChanged)
        self.registerField("db_login", self.db_login, "text", self.db_login.textChanged)
        self.registerField("db_port", self.db_port, "text", self.db_port.textChanged)

    def _field_row(self, label_text: str, parent: QWidget):
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label_text)
        lbl.setFixedWidth(80)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        edit = LineEdit(parent)
        edit.setClearButtonEnabled(True)
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        return row, edit

    def _port_row(self, label_text: str, parent: QWidget):
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label_text)
        lbl.setFixedWidth(80)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        edit = LineEdit(parent)
        edit.setFixedWidth(90)
        edit.setValidator(QIntValidator(1, 65535))
        row.addWidget(lbl)
        row.addWidget(edit)
        row.addStretch()
        return row, edit

    def isComplete(self) -> bool:
        return bool(self.ssh_login.text().strip())