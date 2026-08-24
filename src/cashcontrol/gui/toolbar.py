"""
Toolbar — top toolbar with main actions and per-tab action buttons.

Contains:
- Toolbar (top): add cash, settings, refresh
- CashToolbar (per-tab): restart, reboot, VNC, SSH, WinSCP, DB, keyboard, commands
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PushButton,
    RoundMenu,
    ToolButton,
)

from cashcontrol.core.cash_types import get_cash_type_registry, has_feature
from cashcontrol.gui.prefetch import get_prefetcher
from cashcontrol.infrastructure.audit_logger import audit_log, get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager

if TYPE_CHECKING:
    from cashcontrol.gui.session_manager import SessionManager

logger = get_logger()

_TOOL_BTN_SIZE = 32
_TOOL_ICON_SIZE = 16


# ── Top toolbar ───────────────────────────────────────────────


class Toolbar(QWidget):
    """Top toolbar with main action buttons."""

    add_cash_requested = Signal()
    settings_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self.btn_add_cash = PushButton("Добавить кассу", self, FluentIcon.ADD)
        self.btn_add_cash.clicked.connect(self.add_cash_requested.emit)
        layout.addWidget(self.btn_add_cash)

        self.btn_refresh = PushButton("Обновить", self, FluentIcon.SYNC)
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        layout.addWidget(self.btn_refresh)

        layout.addStretch()

        self.btn_settings = PushButton("Настройки", self, FluentIcon.SETTING)
        self.btn_settings.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.btn_settings)


# ── Per-tab toolbar ───────────────────────────────────────────


def _make_labeled_btn(icon: FluentIcon, label: str, tooltip: str) -> QWidget:
    container = QWidget()
    container.setFixedWidth(_TOOL_BTN_SIZE + 8)
    lay = QVBoxLayout(container)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(1)
    lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

    btn = ToolButton(icon, container)
    btn.setFixedSize(_TOOL_BTN_SIZE, _TOOL_BTN_SIZE)
    btn.setIconSize(QSize(_TOOL_ICON_SIZE, _TOOL_ICON_SIZE))
    btn.setToolTip(tooltip)
    lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)

    lbl = QLabel(label, container)
    from cashcontrol.gui.theme_helper import color
    lbl.setStyleSheet(
        f"font-size: 9px; color: {color('text_secondary')}; background: transparent;"
    )
    lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    lay.addWidget(lbl, 0, Qt.AlignmentFlag.AlignHCenter)

    container.btn = btn
    return container


def _make_keyboard_btn(on_keyboard, on_keyboard_menu) -> QWidget:
    container = QWidget()
    lay = QHBoxLayout(container)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    main_c = QWidget(container)
    main_c.setFixedWidth(68)
    main_vbox = QVBoxLayout(main_c)
    main_vbox.setContentsMargins(0, 2, 0, 2)
    main_vbox.setSpacing(1)
    main_vbox.setAlignment(Qt.AlignmentFlag.AlignHCenter)

    kb_btn = ToolButton(FluentIcon.APPLICATION, main_c)
    kb_btn.setFixedSize(_TOOL_BTN_SIZE, _TOOL_BTN_SIZE)
    kb_btn.setIconSize(QSize(_TOOL_ICON_SIZE, _TOOL_ICON_SIZE))
    kb_btn.setToolTip("Виртуальная клавиатура")
    kb_btn.clicked.connect(on_keyboard)
    main_vbox.addWidget(kb_btn, 0, Qt.AlignmentFlag.AlignHCenter)

    kb_lbl = QLabel("Клавиатура", main_c)
    from cashcontrol.gui.theme_helper import color as _tc
    kb_lbl.setStyleSheet(
        f"font-size: 9px; color: {_tc('text_secondary')}; background: transparent;"
    )
    kb_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    kb_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    main_vbox.addWidget(kb_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
    lay.addWidget(main_c)

    kb_arrow_btn = ToolButton(FluentIcon.MORE, container)
    kb_arrow_btn.setFixedSize(18, _TOOL_BTN_SIZE + 22)
    kb_arrow_btn.setIconSize(QSize(12, 12))
    kb_arrow_btn.setToolTip("Дополнительно")
    kb_arrow_btn.clicked.connect(on_keyboard_menu)
    lay.addWidget(kb_arrow_btn)

    return container, kb_btn, kb_arrow_btn


class CashToolbar(QWidget):
    """
    Per-tab toolbar with action buttons (restart, reboot, VNC, SSH, etc.).

    Emits signals for each action — TabManager coordinates the response.
    """



    def __init__(self, session_mgr: SessionManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("actionToolbar")
        self._session_mgr = session_mgr
        self._config = ConfigManager()
        self._kb_container: QWidget | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFixedHeight(_TOOL_BTN_SIZE + 22)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # Cash control group
        c = _make_labeled_btn(FluentIcon.SYNC, "Рестарт", "Перезагрузить ПО (cash restart)")
        self._restart_btn = c.btn
        self._restart_btn.clicked.connect(self._on_restart_pos)
        layout.addWidget(c)

        c = _make_labeled_btn(FluentIcon.POWER_BUTTON, "Ребут", "Перезагрузить кассу (reboot)")
        self._reboot_btn = c.btn
        self._reboot_btn.clicked.connect(self._on_reboot_terminal)
        layout.addWidget(c)

        # External tools group
        c = _make_labeled_btn(FluentIcon.VIEW, "VNC", "VNC — удалённый просмотр экрана кассы")
        self._vnc_btn = c.btn
        self._vnc_btn.clicked.connect(self._on_vnc)
        layout.addWidget(c)

        c = _make_labeled_btn(FluentIcon.COMMAND_PROMPT, "SSH", "SSH — терминал (KiTTY)")
        self._ssh_btn = c.btn
        self._ssh_btn.clicked.connect(self._on_ssh)
        layout.addWidget(c)

        c = _make_labeled_btn(FluentIcon.FOLDER, "WinSCP", "WinSCP — файловый менеджер")
        self._winscp_btn = c.btn
        self._winscp_btn.clicked.connect(self._on_winscp)
        layout.addWidget(c)

        c = _make_labeled_btn(FluentIcon.LIBRARY, "БД", "PostgreSQL — редактор базы данных")
        self._pg_btn = c.btn
        self._pg_btn.clicked.connect(self._on_postgres)
        layout.addWidget(c)

        # Keyboard
        kb_container, self._kb_btn, self._kb_arrow_btn = _make_keyboard_btn(
            self._on_keyboard, self._on_keyboard_menu
        )
        self._kb_container = kb_container
        self._kb_container.hide()
        layout.addWidget(self._kb_container)

        # Data group
        c = _make_labeled_btn(FluentIcon.UPDATE, "Обновить", "Обновить данные кассы")
        self._refresh_btn = c.btn
        self._refresh_btn.clicked.connect(self._on_refresh_info)
        layout.addWidget(c)

        # Commands
        c = _make_labeled_btn(FluentIcon.SCROLL, "Команды", "Выбрать и выполнить команду на кассе")
        self._commands_btn = c.btn
        self._commands_btn.clicked.connect(self._on_commands_clicked)
        layout.addWidget(c)

        # Hover-prefetch: наведение греет TCP-маршрут до кассы (см. gui/prefetch.py)
        self._prefetch = get_prefetcher()
        for btn in (
            self._restart_btn, self._reboot_btn, self._vnc_btn,
            self._ssh_btn, self._winscp_btn, self._pg_btn,
            self._commands_btn, self._refresh_btn,
        ):
            btn.installEventFilter(self)
            btn.setMouseTracking(True)

        for _b in (self._restart_btn, self._reboot_btn, self._vnc_btn,
                 self._ssh_btn, self._winscp_btn, self._pg_btn,
                 self._refresh_btn, self._commands_btn):
            _b.setObjectName("actionBtn")
        self._reboot_btn.setProperty("danger", True)
        layout.addStretch()

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.Enter and obj in (
            self._restart_btn, self._reboot_btn, self._vnc_btn,
            self._ssh_btn, self._winscp_btn, self._pg_btn,
            self._refresh_btn,
        ):
            self._prefetch.schedule_tcp(
                self._session_mgr.active_ip,
                ConfigManager().settings.connection.ssh_port,
            )
        return super().eventFilter(obj, event)

    # ── Public API ──────────────────────────────────────────

    def update_for_cash_type(self, cash_type: str | None) -> None:
        if self._kb_container:
            self._kb_container.setVisible(has_feature(cash_type, "keyboard"))

    def set_busy(self, busy: bool, message: str = "") -> None:
        btns = [
            self._restart_btn, self._reboot_btn,
            self._vnc_btn, self._ssh_btn, self._winscp_btn,
            self._pg_btn, self._commands_btn, self._refresh_btn,
        ]
        for btn in btns:
            btn.setEnabled(not busy)

        from cashcontrol.gui.main_window import MainWindow

        mw = self.window()
        while mw is not None:
            if isinstance(mw, MainWindow):
                mw.set_status(message if busy else "\u0413\u043e\u0442\u043e\u0432\u043e")
                break
            mw = mw.parent() if hasattr(mw, "parent") else None

    # ── Keyboard menu ───────────────────────────────────────

    def _on_keyboard_menu(self) -> None:
        menu = RoundMenu(parent=self)
        action = QAction(FluentIcon.EDIT.icon(), "Конструктор клавиатуры", self)
        action.triggered.connect(self._on_keyboard_editor)
        menu.addAction(action)
        btn = self._kb_arrow_btn
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        menu.exec(pos)

    # ── Helpers ─────────────────────────────────────────────

    def _require_active_tab(self) -> str | None:
        mw = self.window()
        tm = getattr(mw, '_tab_manager', None) or getattr(mw, 'tab_manager', None)
        if tm is None:
            return None
        session = tm.get_active_session()
        if not session:
            InfoBar.warning(title="Нет активной вкладки", content="Откройте вкладку с кассой",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return None
        return session.ip

    def _get_main_window(self):
        from cashcontrol.gui.main_window import MainWindow
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, MainWindow):
                return parent
            parent = parent.parent()
        return None

    def _get_active_session_widget(self):
        mw = self.window()
        tm = getattr(mw, '_tab_manager', None) or getattr(mw, 'tab_manager', None)
        if tm is None:
            return None
        return tm.get_active_session()

    # ── Cash operations ─────────────────────────────────────

    def _on_restart_pos(self) -> None:
        ip = self._require_active_tab()
        if ip:
            asyncio.ensure_future(self._exec_action(ip, "restart_cash", title="Перезагрузка ПО"))

    def _on_reboot_terminal(self) -> None:
        ip = self._require_active_tab()
        if ip:
            dlg = MessageBox("Перезагрузка кассы",
                             f"Перезагрузить кассу {ip}?\nСистема будет перезагружена.", self.window())
            dlg.yesButton.setText("Перезагрузить")
            if dlg.exec():
                asyncio.ensure_future(self._exec_action(ip, "reboot_cash", title="Перезагрузка кассы"))

    # ── External program launchers ─────────────────────────

    def _launch_program(self, exe_path: str | None, args_template: str, program_name: str) -> None:
        from cashcontrol.gui.notification_manager import get_notification_manager
        session_widget = self._get_active_session_widget()
        if not session_widget:
            get_notification_manager().notify("Нет активной вкладки: Откройте вкладку с кассой", level="warning")
            return

        if not exe_path or not exe_path.strip():
            get_notification_manager().notify(
                f"{program_name}: путь не задан: Настройки → Программы",
                level="warning",
            )
            return

        exe = Path(exe_path)
        if not exe.exists():
            get_notification_manager().notify(
                f"{program_name}: файл не найден: {exe_path}",
                level="error",
            )
            return

        conn = self._config.settings.connection
        template_vars = {
            "host": session_widget.ip,
            "port": str(conn.ssh_port),
            "login": conn.ssh_login,
            "db_port": str(conn.db_port),
            "db_login": conn.db_login,
            "display": "0",
        }

        try:
            args_str = args_template.format(**template_vars)
        except KeyError as e:
            get_notification_manager().notify(
                f"{program_name}: ошибка шаблона: Неизвестная переменная: {e}",
                level="error",
            )
            return

        cmd_parts = [str(exe), *args_str.split()]
        try:
            subprocess.Popen(cmd_parts, close_fds=True)
            logger.info(f"Launched {program_name}: {' '.join(cmd_parts)}")
            get_notification_manager().notify(f"Запущен {program_name}: {session_widget.ip}", level="info")
        except Exception as e:
            logger.error(f"Failed to launch {program_name}: {e}")
            get_notification_manager().notify(f"Ошибка запуска {program_name}: {str(e)[:120]}", level="error")

    def _on_vnc(self) -> None:
        from cashcontrol.gui.notification_manager import get_notification_manager
        session_widget = self._get_active_session_widget()
        if not session_widget:
            get_notification_manager().notify("Нет активной вкладки: Откройте вкладку с кассой", level="warning")
            return

        p = self._config.settings.programs
        exe_path = p.get_vnc_client()
        if not exe_path or not exe_path.strip():
            get_notification_manager().notify("VNC: путь не задан: Настройки → Программы", level="warning")
            return

        exe = Path(exe_path)
        if not exe.exists():
            new_path, _ = QFileDialog.getOpenFileName(
                self,
                "Укажите путь к VNC-клиенту",
                str(exe.parent) if exe.parent.exists() else "",
                "Executable (*.exe);;All files (*)",
            )
            if not new_path:
                return
            p.vnc_client_path = new_path
            self._config.save()

        session_widget.open_vnc_external()

    def _on_ssh(self) -> None:
        asyncio.ensure_future(self._launch_kitty())

    async def _launch_kitty(self) -> None:
        import threading
        import time

        session = self._get_active_session_widget()
        if not session:
            InfoBar.warning(title="Нет активной вкладки", content="Откройте вкладку с кассой",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        p = self._config.settings.programs
        conn = self._config.settings.connection
        exe_path = p.get_ssh_client()
        exe = Path(exe_path)

        if not exe.exists():
            new_path, _ = QFileDialog.getOpenFileName(
                self,
                "Укажите SSH-клиент (KiTTY, PuTTY или другой)",
                str(exe.parent) if exe.parent.exists() else "",
                "Executable (*.exe);;All files (*)",
            )
            if not new_path:
                return
            p.ssh_client_path = new_path
            self._config.save()
            exe = Path(new_path)

        ip = session.ip
        password = None
        if session.session and session.session.ssh_connected:
            password = session.session.ssh.successful_password

        if password:
            cmd = [
                str(exe),
                f"{conn.ssh_login}@{ip}",
                "-pw", password,
                "-auto-store-sshkey",
            ]
            logger.info(f"Launching KiTTY with auto-login for {ip}")
        else:
            cmd = [str(exe), f"{conn.ssh_login}@{ip}"]
            logger.info(f"Launching KiTTY without password for {ip}")

        audit_log(action_type="tool", action_name="ssh_client", target=ip, result="success")

        def _run():
            time.sleep(0.2)
            try:
                subprocess.Popen(cmd, creationflags=0x08000000)
            except Exception as e:
                logger.error(f"KiTTY launch failed: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _on_winscp(self) -> None:
        asyncio.ensure_future(self._launch_winscp())

    async def _launch_winscp(self) -> None:
        import threading
        import time

        session = self._get_active_session_widget()
        if not session:
            InfoBar.warning(title="Нет активной вкладки", content="Откройте вкладку с кассой",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        p = self._config.settings.programs
        conn = self._config.settings.connection
        exe_path = p.get_winscp()
        exe = Path(exe_path)

        if not exe.exists():
            new_path, _ = QFileDialog.getOpenFileName(
                self,
                "Укажите путь к WinSCP",
                str(exe.parent) if exe.parent.exists() else "",
                "Executable (*.exe);;All files (*)",
            )
            if not new_path:
                return
            p.winscp_path = new_path
            self._config.save()
            exe = Path(new_path)

        ip = session.ip
        password = None
        os_type = "tinycore"

        if session.session and session.session.ssh_connected:
            password = session.session.ssh.successful_password
            os_type = session.os_type

        if not password:
            MessageBox("Нет пароля",
                       f"Не удалось получить пароль для {ip}.\nПроверьте настройки подключения.",
                       self.window()).exec()
            return

        protocol = "sftp" if os_type.lower() == "ubuntu" else "scp"
        uri = f"{protocol}://{conn.ssh_login}:{password}@{ip}/"

        cmd = [
            str(exe),
            uri,
            "/hostkey=*",
            "/rawsettings",
            "AuthKI=0",
            "AuthTIS=0",
            "AuthGSSAPI=0",
        ]

        audit_log(action_type="tool", action_name="winscp", target=ip, result="success")
        logger.info(f"Launching WinSCP for {ip} protocol={protocol}")

        def _run():
            time.sleep(0.2)
            try:
                subprocess.Popen(cmd, creationflags=0x08000000)
            except Exception as e:
                logger.error(f"WinSCP launch failed: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _on_postgres(self) -> None:
        from cashcontrol.gui.notification_manager import get_notification_manager
        p    = self._config.settings.programs
        conn = self._config.settings.connection

        if not p.db_client_path or not p.db_client_path.strip():
            session_widget = self._get_active_session_widget()
            if not session_widget:
                get_notification_manager().notify("Нет активной вкладки: Откройте вкладку с кассой", level="warning")
                return

            try:
                import psycopg2  # noqa: F401
            except ImportError:
                get_notification_manager().notify(
                    "Отсутствует модуль psycopg2: Выполните в терминале: pip install psycopg2-binary",
                    level="error",
                )
                logger.error("[DB] psycopg2 not installed")
                return

            try:
                from cashcontrol.core.security.password_manager import PasswordManager
                from cashcontrol.gui.db_viewer import PostgresToolWindow
            except ImportError as e:
                get_notification_manager().notify(f"Ошибка загрузки DB Viewer: {e!s}", level="error")
                logger.error(f"[DB] Import error: {e}")
                return

            pm = PasswordManager()
            passwords = list(pm.get_passwords_for_ip(session_widget.ip, "db"))

            if not passwords:
                get_notification_manager().notify(
                    f"Пароли для {session_widget.ip} не найдены: Добавьте пароль в Настройки -> Подключение",
                    level="warning",
                )

            win = PostgresToolWindow(
                host=session_widget.ip,
                port=conn.db_port,
                user=conn.db_login,
                passwords=passwords,
                database=None,
                parent=self,
            )
            win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            win.show()
            get_notification_manager().notify(f"DB Viewer: {session_widget.ip}: порт {conn.db_port}", level="info")
            logger.info(f"[DB] Opened built-in DB Viewer for {session_widget.ip}")
            return

        self._launch_program(p.db_client_path, p.db_args_template, "PostgreSQL Клиент")

    # ── Commands ────────────────────────────────────────────

    def commands_btn_center(self) -> QPoint:
        """Глобальная точка под центром кнопки «Команды» — для меню."""
        btn = self._commands_btn
        return btn.mapToGlobal(QPoint(btn.width() // 2, btn.height()))

    def _on_commands_clicked(self) -> None:
        session = self._get_active_session_widget()
        if not session:
            InfoBar.warning(title="Нет активной вкладки", content="Откройте вкладку с кассой",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        mw = self._get_main_window()
        if not mw:
            return

        mw.registry.reload_commands()

        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        actions = sorted(
            mw.registry.get_all_actions(),
            key=lambda a: a.description.lower()
        )

        if not actions:
            no_act = menu.addAction("Нет команд — создайте в редакторе команд")
            no_act.setEnabled(False)
        else:
            for action in actions:
                act = menu.addAction(action.name)
                act.setToolTip(action.description or action.name)
                act.setData(action.name)

        menu.addSeparator()
        act_manual = menu.addAction("Тип кассы: выбрать вручную…")
        act_manual.setData("__select_cash_type__")

        chosen = menu.exec(self.commands_btn_center())

        if chosen and chosen.data() == "__select_cash_type__":
            self._on_select_cash_type(session)
            return

        if chosen and chosen.data():
            action_name = chosen.data()
            action_obj = mw.registry.get_action(action_name)
            if action_obj and action_obj.requires_confirmation:
                dlg = MessageBox("Подтверждение",
                                 f"Выполнить {action_obj.description} на кассе {session.ip}?", self.window())
                dlg.yesButton.setText("Выполнить")
                if not dlg.exec():
                    return
            asyncio.ensure_future(
                self._exec_action(session.ip, action_name, title=action_obj.description if action_obj else action_name)
            )

    def _on_refresh_info(self) -> None:
        session_widget = self._get_active_session_widget()
        if not session_widget:
            return
        ip = session_widget.ip
        logger.info(f"Refresh requested for {ip}, doing full reconnect")
        asyncio.ensure_future(session_widget.reconnect_to(ip))

    def _on_select_cash_type(self, session_widget) -> None:
        """Ручной выбор типа кассы (когда автоопределение дало unknown)."""
        from PySide6.QtWidgets import QInputDialog

        registry = get_cash_type_registry()
        registry.reload()
        definitions = sorted(registry.all(), key=lambda d: d.id)
        items = [f"{d.id} — {d.name}" for d in definitions]
        choice, ok = QInputDialog.getItem(
            self, "Тип кассы", "Выберите тип (сохранится вручную):", items, 0, False
        )
        if not ok:
            return

        selected = next(
            (d for d in definitions if f"{d.id} — {d.name}" == choice), None
        )
        resolved = selected.id if selected else None
        if not resolved or session_widget.session is None:
            return

        session_widget.session.cash_type = resolved
        session_widget.session.cash_type_source = "manual"
        logger.info(f"Manual cash type for {session_widget.ip}: {resolved}")
        asyncio.ensure_future(session_widget.load_info(force=True))

    # ── Action execution ────────────────────────────────────

    def _add_history(self, ip: str, action_name: str, success: bool,
                     details: str = "") -> None:
        from datetime import datetime

        from cashcontrol.gui.history_manager import HistoryEntry, get_history_manager
        try:
            get_history_manager().add(ip, HistoryEntry(
                timestamp=datetime.now(), action_name=action_name,
                result="success" if success else "error",
                details=(details or "")[:200], ip=ip))
        except Exception:
            logger.exception("history add failed")

    def _set_toolbar_busy(self, busy: bool, message: str = "") -> None:
        self.set_busy(busy)
        mw = self._get_main_window()
        if mw:
            mw.set_status(message if busy else "Готово")

    async def _exec_action(self, ip: str, action_name: str, title: str = "Результат") -> None:
        from cashcontrol.gui.dialogs.command_result_dialog import CommandResultDialog

        session_widget = self._session_mgr.get_session(ip)
        if not session_widget or not session_widget.session:
            MessageBox("Ошибка", "Касса не подключена", self.window()).exec()
            return

        mw = self._get_main_window()
        if not mw:
            return

        action_obj = mw.registry.get_action(action_name)
        extra_kwargs: dict = {}
        if action_obj and action_obj.input_prompt:
            from PySide6.QtWidgets import QInputDialog
            value, ok = QInputDialog.getText(self, title, action_obj.input_prompt)
            if not ok:
                return
            extra_kwargs["user_input"] = value.strip()

        self._set_toolbar_busy(True, f"{title} — {ip}…")

        ping_was_active = self._session_mgr.active_ip == ip
        if ping_was_active:
            self._session_mgr.stop_ping()

        try:
            result = await mw.registry.execute_action(action_name, session_widget.session, **extra_kwargs)
            show_output = getattr(action_obj, "show_output", True)
            if show_output:
                dlg = CommandResultDialog(result, parent=self, title=title)
                dlg.exec()
            else:
                if not result.success:
                    MessageBox("Ошибка команды", result.message, self.window()).exec()
            self._add_history(ip, title, result.success, result.message)
        except Exception as e:
            logger.error(f"Action '{action_name}' exception: {e}")
            MessageBox("Ошибка", f"Неожиданная ошибка: {e}", self.window()).exec()
            self._add_history(ip, title, False, str(e))
        finally:
            self._set_toolbar_busy(False)
            if ping_was_active:
                self._session_mgr.start_ping(ip)

    # ── Keyboard handlers ───────────────────────────────────

    def _on_keyboard(self) -> None:
        if not self._session_mgr.active_ip:
            return
        session = self._session_mgr.get_session(self._session_mgr.active_ip)
        if not session:
            return

        keyboard_model = session.keyboard_model

        from cashcontrol.gui.widgets.virtual_keyboard import (
            LAYOUTS,
            VirtualKeyboardWindow,
            find_layout_for_keyboard,
        )

        layout_stem = find_layout_for_keyboard(keyboard_model or "")
        if not layout_stem:
            layout_stem = next(iter(LAYOUTS))
            logger.warning(
                f"[Keyboard] no layout for '{keyboard_model}', using {layout_stem}"
            )

        cash_session = session.session
        if not cash_session:
            return
        kb = VirtualKeyboardWindow(session=cash_session, layout_stem=layout_stem, parent=self)
        kb.show()
        kb.raise_()

    def _on_keyboard_editor(self) -> None:
        keyboard_model = None
        if self._session_mgr.active_ip:
            session = self._session_mgr.get_session(self._session_mgr.active_ip)
            if session:
                keyboard_model = session.keyboard_model

        from cashcontrol.gui.widgets.virtual_keyboard import (
            LAYOUTS,
            KeyboardEditorWindow,
            find_layout_for_keyboard,
        )

        layout_stem = find_layout_for_keyboard(keyboard_model or "")
        if not layout_stem:
            layout_stem = next(iter(LAYOUTS))

        editor = KeyboardEditorWindow(layout_stem=layout_stem, parent=self)
        editor.show()
        editor.raise_()
