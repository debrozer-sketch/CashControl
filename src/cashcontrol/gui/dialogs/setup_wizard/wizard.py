from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWizard

from cashcontrol.core.security import encrypt_passwords
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

        ssh_pwds, self._ssh_decrypt_failed = self._safe_decrypt(
            cfg.connection.ssh_passwords_encrypted
        )
        self._conn_page.ssh_passwords.setPlainText("\n".join(ssh_pwds))

        db_pwds, self._db_decrypt_failed = self._safe_decrypt(
            cfg.connection.db_passwords_encrypted
        )
        self._conn_page.db_passwords.setPlainText("\n".join(db_pwds))

        self._prog_page.load(self._config)

    @staticmethod
    def _safe_decrypt(encrypted: list[str]) -> tuple[list[str], bool]:
        """Decrypt a password list, reporting failures instead of skipping them silently.

        Returns:
            (decrypted, failed) — `failed` is True when any stored token could
            not be decrypted; the caller must not then silently overwrite the
            stored values with an empty list.
        """
        from cashcontrol.core.security.encryption import EncryptionManager

        decrypted: list[str] = []
        failed = False
        for token in encrypted:
            if not token:
                continue
            try:
                decrypted.append(EncryptionManager().decrypt(token))
            except Exception:
                failed = True
        return decrypted, failed

    def _on_finished(self) -> None:
        from PySide6.QtWidgets import QDialog, QMessageBox

        if self.result() != QDialog.Accepted:
            logger.info("Setup wizard cancelled, no config changes")
            return
        try:
            ssh_pwds = self._conn_page.ssh_passwords.toPlainText().strip().splitlines()
            db_pwds = self._conn_page.db_passwords.toPlainText().strip().splitlines()

            conn_kwargs = {
                "ssh_login": self.field("ssh_login"),
                "ssh_port": int(str(self.field("ssh_port")) or "22"),
                "db_login": self.field("db_login"),
                "db_port": int(str(self.field("db_port")) or "5432"),
            }

            warnings: list[str] = []
            # Стирать сохранённые пароли, которые не удалось расшифровать, —
            # нельзя: покажем предупреждение и сохраним прежние зашифрованные.
            if not (self._ssh_decrypt_failed and not ssh_pwds):
                conn_kwargs["ssh_passwords_encrypted"] = encrypt_passwords(ssh_pwds)
            else:
                warnings.append("SSH-пароли не расшифровались и были оставлены без изменений")
            if not (self._db_decrypt_failed and not db_pwds):
                conn_kwargs["db_passwords_encrypted"] = encrypt_passwords(db_pwds)
            else:
                warnings.append("Пароли БД не расшифровались и были оставлены без изменений")

            self._config.update("connection", **conn_kwargs)
            self._config.update("general", setup_completed=True)
            self._prog_page.save(self._config)
            self._config.save()
            logger.info("Setup wizard completed and config saved")

            if warnings:
                QMessageBox.warning(
                    self,
                    "Внимание",
                    "Сохранённые пароли не удалось расшифровать (возможно, ключ "
                    "шифрования повреждён). Чтобы не потерять данные, пароли "
                    "сохранены в прежнем виде.\n\n" + "\n".join(warnings),
                )
        except Exception as e:
            logger.exception(f"Failed to save config: {e}")
