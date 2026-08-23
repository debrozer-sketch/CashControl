from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWizard

from cashcontrol.core.security import decrypt_passwords, encrypt_passwords
from cashcontrol.gui.dialogs.setup_wizard.page_connection import ConnectionPage
from cashcontrol.gui.dialogs.setup_wizard.page_connection_test import ConnectionTestPage
from cashcontrol.gui.dialogs.setup_wizard.page_finish import FinishPage
from cashcontrol.gui.dialogs.setup_wizard.page_programs import ProgramsPage
from cashcontrol.gui.dialogs.setup_wizard.page_welcome import WelcomePage
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()


class CashControlSetupWizard(QWizard):
    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self._config = config

        self.setWindowTitle("Настройка CashControl")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setMinimumSize(680, 580)

        self.setButtonText(QWizard.BackButton,   "< Назад")
        self.setButtonText(QWizard.NextButton,   "Далее >")
        self.setButtonText(QWizard.FinishButton, "Завершить")
        self.setButtonText(QWizard.CancelButton, "Отмена")

        self._welcome_page = WelcomePage(self)
        self._conn_page = ConnectionPage(self)
        self._test_page = ConnectionTestPage(self)
        self._prog_page = ProgramsPage(self)
        self._finish_page = FinishPage(self)

        self.addPage(self._welcome_page)
        self.addPage(self._conn_page)
        self.addPage(self._test_page)
        self.addPage(self._prog_page)
        self.addPage(self._finish_page)

        self._init_fields()
        self.finished.connect(self._on_finished)

    def _init_fields(self) -> None:
        cfg = self._config.settings
        self.setField("ssh_login", cfg.connection.ssh_login or "tc")
        self.setField("ssh_port", str(cfg.connection.ssh_port or 22))
        self.setField("db_login", cfg.connection.db_login or "postgres")
        self.setField("db_port", str(cfg.connection.db_port or 5432))

        ssh_pwds = decrypt_passwords(cfg.connection.ssh_passwords_encrypted)
        self._conn_page.ssh_passwords.setPlainText("\n".join(ssh_pwds))

        db_pwds = decrypt_passwords(cfg.connection.db_passwords_encrypted)
        self._conn_page.db_passwords.setPlainText("\n".join(db_pwds))

    def _on_finished(self) -> None:
        try:
            ssh_pwds = self._conn_page.ssh_passwords.toPlainText().strip().splitlines()
            db_pwds = self._conn_page.db_passwords.toPlainText().strip().splitlines()

            self._config.update(
                "connection",
                ssh_login=self.field("ssh_login"),
                ssh_port=int(str(self.field("ssh_port")) or "22"),
                ssh_passwords_encrypted=encrypt_passwords(ssh_pwds),
                db_login=self.field("db_login"),
                db_port=int(str(self.field("db_port")) or "5432"),
                db_passwords_encrypted=encrypt_passwords(db_pwds),
            )
            self._config.update("general", setup_completed=True)
            self._config.save()
            logger.info("Setup wizard completed and config saved")
        except Exception as e:
            logger.exception(f"Failed to save config: {e}")
