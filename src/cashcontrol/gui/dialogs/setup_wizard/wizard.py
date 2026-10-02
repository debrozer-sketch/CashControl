"""Окно первоначальной настройки CashControl.

Раньше это был ``QWizard`` на пять страниц: приветствие, параметры
подключения, проверка подключения, внешние программы, завершение. Две
страницы из пяти были почти пустыми (192 и 102 пикселя содержимого при
474 доступной высоты), а переход между страницами заставлял каждый раз
возвращать мышь вниз окна к кнопкам «Далее/Назад».

Теперь это одно окно: поля подключения и кнопка «Проверить» стоят рядом,
пути к программам свёрнуты, а единственная кнопка внизу — «Настроить».
Пустой прогон для настройки не требует ни одного перехода мыши.

Публичный контракт не изменился: ``CashControlSetupWizard(config)``,
``exec()`` и ``take_warnings()``. Предупреждения копятся и отдаются
вызывающему коду (``main.py``) — сам диалог их не показывает, потому что
сигнал ``finished`` приходит после того, как Qt скрыл окно, и полоса с его
родителем показалась бы уже невидимому виджету.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    LineEdit,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TextEdit,
)

from cashcontrol.core.security import encrypt_passwords
from cashcontrol.gui.dialogs.setup_wizard.section_programs import ProgramsSection
from cashcontrol.gui.theme_helper import _label_minimum, control_size, font_size
from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()

# В окне две колонки, поэтому колонка подписей вдвое уже, чем в настройках
# (220). Подписи «Логин:», «Порт:», «IP кассы:» в неё помещаются, а
# _label_minimum всё равно не даст обрезать более длинную.
_LABEL_W = 110

# Высота однострочного поля — общий токен CONTROL_SIZE["row"], 32 пикселя.
# Списки паролей ниже: 72 пикселя показывают четыре строки, а 96 показывали
# шесть и съедали высоту, которой в окне с четырьмя карточками не хватает.
_ROW_H = control_size("row")
_PASSWORDS_H = 72


def _typed_passwords(edit) -> list[str] | None:
    """Пароли, введённые оператором, или ``None``, если поле оставлено пустым.

    Пустое поле — это «оставить как есть», а не «удалить». Смысл такой:
    расшифрованные пароли в окно не подставляются, и поле, оставленное
    нетронутым при правке логина, не должно стирать сохранённые значения.
    Удаление паролей — отдельное действие во вкладке настроек.
    """
    text = edit.toPlainText().strip()
    if not text:
        return None
    return text.splitlines()


class CashControlSetupWizard(QDialog):
    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._pending_warnings: list[str] = []
        self._test_task: asyncio.Task | None = None

        self.setWindowTitle("Настройка CashControl")
        self.setMinimumSize(540, 460)
        self.resize(660, 580)

        self._build_ui()
        self._init_fields()
        self.finished.connect(self._on_finished)

    # ── интерфейс ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(12, 4, 12, 4)
        inner_layout.setSpacing(10)
        # Все настройки одним списком, друг над другом: SSH, PostgreSQL,
        # проверка, пути к программам. Карточки не сворачиваются и не
        # прячутся — иначе часть полей пришлось бы искать.
        inner_layout.addWidget(self._build_ssh_card())
        inner_layout.addWidget(self._build_db_card())
        inner_layout.addWidget(self._build_check_card())
        self._programs = ProgramsSection(inner)
        inner_layout.addWidget(self._programs)
        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        # Кнопки вне прокрутки: на любом месте прокрутки «Сохранить» и
        # «Выход» остаются на одном и том же месте экрана.
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        layout = QVBoxLayout(header)
        layout.setContentsMargins(16, 14, 16, 10)
        layout.setSpacing(2)

        from cashcontrol import __version__

        layout.addWidget(SubtitleLabel(f"Настройка CashControl {__version__}", header))

        self._hint = BodyLabel(
            "Заполните доступ к кассе. Проверку можно пропустить и вернуться к ней "
            "в настройках программы.",
            header,
        )
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: {font_size('hint')}px;"
        )
        layout.addWidget(self._hint)
        return header

    def _build_ssh_card(self) -> CardWidget:
        return self._build_credentials_card(
            "SSH", "tc", "22", "Пароли:", "Введите пароли, по одному на строку"
        )

    def _build_db_card(self) -> CardWidget:
        return self._build_credentials_card(
            "PostgreSQL",
            "postgres",
            "5432",
            "Пароли БД:",
            "Введите пароли БД, по одному на строку",
        )

    def _build_credentials_card(
        self,
        title: str,
        login_placeholder: str,
        port_placeholder: str,
        passwords_label: str,
        passwords_placeholder: str,
    ) -> CardWidget:
        """Карточка «логин, порт, пароли» одним блоком сверху вниз."""
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel(title, card))

        row, login = self._field_row(card, "Логин:")
        login.setPlaceholderText(login_placeholder)
        layout.addLayout(row)

        row, port = self._port_row(card, "Порт:")
        port.setPlaceholderText(port_placeholder)
        layout.addLayout(row)

        layout.addWidget(StrongBodyLabel(passwords_label, card))
        passwords = TextEdit(card)
        passwords.setPlaceholderText(passwords_placeholder)
        passwords.setFixedHeight(_PASSWORDS_H)
        layout.addWidget(passwords)

        note = BodyLabel("", card)
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: {font_size('hint')}px;"
        )
        layout.addWidget(note)

        if title == "SSH":
            self.ssh_login = login
            self.ssh_port = port
            self.ssh_passwords = passwords
            self._ssh_passwords_note = note
        else:
            self.db_login = login
            self.db_port = port
            self.db_passwords = passwords
            self._db_passwords_note = note
        return card

    def _build_check_card(self) -> CardWidget:
        """Проверка доступа сразу под учётными данными, а не отдельным шагом."""
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("Проверка доступа", card))

        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel("IP кассы:", card)
        lbl.setMinimumWidth(_label_minimum(lbl, _LABEL_W))
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.ip_edit = LineEdit(card)
        self.ip_edit.setPlaceholderText("192.168.1.1")
        self.ip_edit.setFixedHeight(_ROW_H)
        self.ip_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.test_btn = PushButton("Проверить", card)
        self.test_btn.setFixedWidth(120)
        self.test_btn.setFixedHeight(_ROW_H)
        self.test_btn.clicked.connect(self._run_test)
        row.addWidget(lbl)
        row.addWidget(self.ip_edit, stretch=1)
        row.addWidget(self.test_btn)
        layout.addLayout(row)

        self._result_label = BodyLabel("", card)
        self._result_label.setWordWrap(True)
        self._result_label.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: {font_size('hint')}px;"
        )
        layout.addWidget(self._result_label)

        self._error_label = BodyLabel("", card)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            f"color: {_tc('error')}; font-size: {font_size('hint')}px;"
        )
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)
        return card

    def _build_footer(self) -> QWidget:
        footer = QWidget(self)
        footer.setObjectName("setupFooter")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(8)
        layout.addStretch()

        self._exit_btn = PushButton("Выход", footer)
        self._exit_btn.clicked.connect(self.reject)
        layout.addWidget(self._exit_btn)

        self._save_btn = PushButton("Сохранить", footer)
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._on_save)
        layout.addWidget(self._save_btn)
        return footer

    def _field_row(self, parent: QWidget, label_text: str) -> tuple[QHBoxLayout, LineEdit]:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label_text, parent)
        lbl.setMinimumWidth(_label_minimum(lbl, _LABEL_W))
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        edit = LineEdit(parent)
        edit.setClearButtonEnabled(True)
        edit.setFixedHeight(_ROW_H)
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(lbl)
        row.addWidget(edit, stretch=1)
        return row, edit

    def _port_row(self, parent: QWidget, label_text: str) -> tuple[QHBoxLayout, LineEdit]:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label_text, parent)
        lbl.setMinimumWidth(_label_minimum(lbl, _LABEL_W))
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        edit = LineEdit(parent)
        edit.setFixedWidth(90)
        edit.setFixedHeight(_ROW_H)
        edit.setValidator(QIntValidator(1, 65535))
        row.addWidget(lbl)
        row.addWidget(edit)
        row.addStretch()
        return row, edit

    # ── значения ─────────────────────────────────────────────────

    def _init_fields(self) -> None:
        cfg = self._config.settings
        self.ssh_login.setText(cfg.connection.ssh_login or "tc")
        self.ssh_port.setText(str(cfg.connection.ssh_port or 22))
        self.db_login.setText(cfg.connection.db_login or "postgres")
        self.db_port.setText(str(cfg.connection.db_port or 5432))

        # Сохранённые пароли в поле не подставляются: расшифрованные пароли
        # на экране — это чужие глаза, снимок экрана и запись в видео. Вместо них
        # подпись со счётчиком, а пустое поле означает «оставить как есть».
        self._ssh_decrypt_failed = not self._fill_passwords_note(
            self._ssh_passwords_note,
            cfg.connection.ssh_passwords_encrypted,
            "SSH",
        )
        self._db_decrypt_failed = not self._fill_passwords_note(
            self._db_passwords_note,
            cfg.connection.db_passwords_encrypted,
            "БД",
        )

        self._programs.load(self._config)

    @staticmethod
    def _fill_passwords_note(note, encrypted: list[str], what: str) -> bool:
        """Подпись под полем паролей: сколько их сохранено и целы ли они.

        Возвращает ``True``, если сохранённые пароли расшифровываются. Сами
        пароли расшифровываются и сразу забываются: на экран они не попадают,
        а поломка ключа шифрования должна быть видна сразу, а не после
        первой неудачной попытки подключения.
        """
        from cashcontrol.core.security.encryption import EncryptionManager

        stored = [t for t in encrypted if t]
        if not stored:
            note.setText(f"Пароли {what} не заданы — введите их, по одному на строку.")
            note.setStyleSheet(
                f"color: {_tc('text_secondary')}; font-size: {font_size('hint')}px;"
            )
            return True

        broken = False
        for token in stored:
            try:
                EncryptionManager().decrypt(token)
            except Exception:
                broken = True

        if broken:
            note.setText(
                f"Сохранённые пароли {what} не расшифровываются — ключ повреждён. "
                "Введите их заново."
            )
            note.setStyleSheet(
                f"color: {_tc('error')}; font-size: {font_size('hint')}px;"
            )
            return False

        plural = "пароль" if len(stored) == 1 else "пароля"
        note.setText(
            f"Сохранено паролей {what}: {len(stored)} {plural}. "
            "Поле пустое — останутся прежние."
        )
        note.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: {font_size('hint')}px;"
        )
        return True

    # ── проверка подключения ─────────────────────────────────────

    def _run_test(self) -> None:
        ip = self.ip_edit.text().strip()
        if not ip:
            self._set_result("Введите IP-адрес кассы")
            return

        self.test_btn.setEnabled(False)
        self.test_btn.setText("Проверка")
        self._set_result("Подключение...")
        self._test_task = asyncio.ensure_future(self._do_test_async(ip))

    def _set_result(self, text: str) -> None:
        self._result_label.setText(text)

    async def _do_test_async(self, ip: str) -> None:
        ssh_login = self.ssh_login.text().strip() or "tc"
        ssh_port = int(self.ssh_port.text().strip() or 22)
        db_login = self.db_login.text().strip() or "postgres"
        db_port = int(self.db_port.text().strip() or 5432)
        ssh_passwords = self.ssh_passwords.toPlainText().strip().splitlines()
        db_passwords = self.db_passwords.toPlainText().strip().splitlines()

        # Применяем пароли к общему (singleton) конфигу только в памяти и
        # восстанавливаем прежние значения после проверки. Писать их на диск
        # здесь нельзя: «Проверить» не должен молча сохранять настройки
        # (пользователь может потом нажать «Выход»).
        from cashcontrol.infrastructure.config_manager import ConfigManager

        _cfg = ConfigManager()
        conn = _cfg.settings.connection
        prev = (
            conn.ssh_login,
            conn.ssh_port,
            conn.ssh_passwords_encrypted[:],
            conn.db_login,
            conn.db_port,
            conn.db_passwords_encrypted[:],
        )
        conn.ssh_login = ssh_login
        conn.ssh_port = ssh_port
        conn.ssh_passwords_encrypted = encrypt_passwords(ssh_passwords)
        conn.db_login = db_login
        conn.db_port = db_port
        conn.db_passwords_encrypted = encrypt_passwords(db_passwords)

        from cashcontrol.core.session import CashSession

        session = CashSession(ip)
        try:
            ok = await asyncio.wait_for(session.connect(), timeout=10.0)
            if ok:
                session.setup_db(database="postgres")
                await session.connect_db()
                text = f"SSH: подключение успешно ({ip}:{ssh_port})\n"
                if session.db_connected:
                    text += f"DB:  подключение успешно ({ip}:{db_port})"
                else:
                    text += "DB:  не подключена (проверьте пароли БД)"
                self._set_result(text)
                logger.info(f"Connection test OK for {ip} (ssh={ssh_port} db={db_port})")
            else:
                self._set_result(f"SSH: ошибка подключения к {ip}:{ssh_port}")
                logger.info(f"Connection test failed (ssh) for {ip}:{ssh_port}")
        except Exception as e:
            self._set_result(f"Ошибка: {e}")
            logger.exception(f"Connection test failed for {ip}")
        finally:
            conn.ssh_login, conn.ssh_port = prev[0], prev[1]
            conn.ssh_passwords_encrypted = prev[2]
            conn.db_login, conn.db_port = prev[3], prev[4]
            conn.db_passwords_encrypted = prev[5]
            from cashcontrol.core.security.password_manager import PasswordManager

            PasswordManager().clear_cache(ip)
            # ожидаемо: disconnect может упасть, если соединения уже нет
            with contextlib.suppress(Exception):
                await session.disconnect()
            self.test_btn.setEnabled(True)
            self.test_btn.setText("Проверить")

    # ── сохранение ───────────────────────────────────────────────

    def _on_save(self) -> None:
        if not self.ssh_login.text().strip():
            self._show_error("Укажите SSH-логин")
            self.ssh_login.setFocus()
            return
        for port, name in ((self.ssh_port, "SSH"), (self.db_port, "БД")):
            text = port.text().strip()
            if text and not text.isdigit():
                self._show_error(f"Порт {name} должен быть числом")
                port.setFocus()
                return
        self._show_error("")
        self.accept()

    def _show_error(self, text: str) -> None:
        self._error_label.setText(text)
        self._error_label.setVisible(bool(text.strip()))

    def _on_finished(self) -> None:
        if self._test_task and not self._test_task.done():
            self._test_task.cancel()

        if self.result() != QDialog.DialogCode.Accepted:
            logger.info("Setup wizard cancelled, no config changes")
            return
        try:
            # Пустое поле паролей означает «оставить прежние»: подставлять их
            # в поле нельзя, а молча затирать нельзя тем более. Непустое поле
            # заменяет список целиком.
            ssh_pwds = _typed_passwords(self.ssh_passwords)
            db_pwds = _typed_passwords(self.db_passwords)

            conn_kwargs = {
                "ssh_login": self.ssh_login.text().strip() or "tc",
                "ssh_port": int(self.ssh_port.text().strip() or 22),
                "db_login": self.db_login.text().strip() or "postgres",
                "db_port": int(self.db_port.text().strip() or 5432),
            }

            warnings: list[str] = []
            # Сохранённые пароли, которые не расшифровываются, и о которых
            # оператор не знает, — молчаливая поломка: программа не сможет
            # подключиться. Сохранённые значения при этом не трогаем.
            if ssh_pwds is None and self._ssh_decrypt_failed:
                warnings.append(
                    "SSH-пароли не расшифровываются и оставлены без изменений — "
                    "подключение к кассе не заработает"
                )
            if db_pwds is None and self._db_decrypt_failed:
                warnings.append(
                    "Пароли БД не расшифровываются и оставлены без изменений — "
                    "сбор информации о кассе не заработает"
                )
            if ssh_pwds is not None:
                conn_kwargs["ssh_passwords_encrypted"] = encrypt_passwords(ssh_pwds)
            if db_pwds is not None:
                conn_kwargs["db_passwords_encrypted"] = encrypt_passwords(db_pwds)

            self._config.update("connection", **conn_kwargs)
            self._config.update("general", setup_completed=True)
            self._programs.save(self._config)
            self._config.save()
            logger.info("Setup wizard completed and config saved")

            # Присваивание безусловно, а не под ``if warnings:``.
            # Сейчас окно запускается один раз, и путь без
            # предупреждений недостижим, но состояние не должно зависеть
            # от того, попал ли список в ветку: повторный _on_finished без
            # новых предупреждений оставил бы старый список, и
            # take_warnings отдал бы то, чего уже нет.
            self._pending_warnings = list(warnings)
        except Exception as e:
            logger.exception(f"Failed to save config: {e}")

    def take_warnings(self) -> str:
        """Забрать накопленные при сохранении предупреждения.

        Отдельный метод, а не результат ``exec()``: результат у вызывающего
        кода занят флагом отмены, и текст в нём смешался бы с этим флагом.
        Возвращается один готовый текст, а не список строк: собирать его на
        стороне вызывающего кода нельзя, там нет знания о том, что именно
        сломалось.

        Список очищается: повторный вызов вернёт пустую строку, иначе одно
        и то же предупреждение показалось бы дважды.
        """
        if not self._pending_warnings:
            return ""
        text = (
            "Сохранённые пароли не удалось расшифровать (возможно, ключ "
            "шифрования повреждён). Чтобы не потерять данные, пароли "
            "сохранены в прежнем виде.\n\n" + "\n".join(self._pending_warnings)
        )
        self._pending_warnings = []
        return text
