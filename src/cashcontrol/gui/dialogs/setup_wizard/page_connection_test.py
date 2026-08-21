import asyncio

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWizardPage
from qfluentwidgets import BodyLabel, LineEdit, PushButton

from cashcontrol.infrastructure.audit_logger import get_logger

logger = get_logger()


class ConnectionTestPage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._test_task: asyncio.Task | None = None
        self.setTitle("Проверка подключения")
        self.setSubTitle("Проверьте доступ к кассе")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 20, 40, 20)

        ip_row = QHBoxLayout()
        ip_row.setSpacing(8)
        ip_lbl = BodyLabel("IP кассы:")
        ip_lbl.setFixedWidth(80)
        ip_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.ip_edit = LineEdit(self)
        self.ip_edit.setPlaceholderText("192.168.1.1")
        ip_row.addWidget(ip_lbl)
        ip_row.addWidget(self.ip_edit, stretch=1)

        self.test_btn = PushButton("Проверить", self)
        self.test_btn.setFixedWidth(120)
        self.test_btn.clicked.connect(self._run_test)
        ip_row.addWidget(self.test_btn)
        layout.addLayout(ip_row)

        self.result_label = QLabel("", self)
        self.result_label.setWordWrap(True)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.result_label, stretch=1)

    def _run_test(self) -> None:
        ip = self.ip_edit.text().strip()
        if not ip:
            self.result_label.setText("Введите IP-адрес кассы")
            return

        self.test_btn.setEnabled(False)
        self.test_btn.setText("Проверяю")
        self.result_label.setText("Подключение...")

        self._test_task = asyncio.ensure_future(self._do_test_async(ip))

    def cleanupPage(self) -> None:
        if self._test_task and not self._test_task.done():
            self._test_task.cancel()
        super().cleanupPage()

    async def _do_test_async(self, ip: str) -> None:
        w = self.wizard()
        ssh_login = w.field("ssh_login") or "tc"
        ssh_port = int(w.field("ssh_port") or 22)
        db_login = w.field("db_login") or "postgres"
        db_port = int(w.field("db_port") or 5432)

        conn_page = w.page(1)
        ssh_passwords = conn_page.ssh_passwords.toPlainText().strip().splitlines()
        db_passwords = conn_page.db_passwords.toPlainText().strip().splitlines()

        # Save credentials to config so CashSession/SSHSession can read them
        from cashcontrol.core.security import encrypt_passwords
        from cashcontrol.infrastructure.config_manager import ConfigManager
        _cfg = ConfigManager()
        _cfg.update("connection",
            ssh_login=ssh_login, ssh_port=ssh_port,
            ssh_passwords_encrypted=encrypt_passwords(ssh_passwords or [""]),
            db_login=db_login, db_port=db_port,
            db_passwords_encrypted=encrypt_passwords(db_passwords or [""]),
        )
        _cfg.save()

        from cashcontrol.core.session import CashSession

        session = CashSession(host=ip, ssh_port=ssh_port, db_port=db_port)
        try:
            ok = await asyncio.wait_for(session.connect(), timeout=10.0)
            if ok:
                text = f"SSH: подключение успешно ({ip}:{ssh_port})\n"
                if session.db_connected:
                    text += f"DB:  подключение успешно ({ip}:{db_port})"
                else:
                    text += "DB:  не подключена (проверьте пароли БД)"
                self.result_label.setText(text)
            else:
                self.result_label.setText(f"SSH: ошибка подключения к {ip}:{ssh_port}")
        except Exception as e:
            self.result_label.setText(f"Ошибка: {e}")
            logger.exception(f"Connection test failed for {ip}")
        finally:
            try:
                await session.disconnect()
            except Exception:
                # ожидаемо: disconnect может упасть, если соединения уже нет
                pass
            self.test_btn.setEnabled(True)
            self.test_btn.setText("Проверить")