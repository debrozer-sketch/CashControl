"""
Main window — application main window.

Layout:
  - Left: narrow icon sidebar (settings, tools)
  - Right: tab bar + toolbar + content
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, QSize, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from cashcontrol import __app_name__, __version__
from cashcontrol.actions_registry import ActionsRegistry
from cashcontrol.gui.sidebar import SidebarPanel
from cashcontrol.gui.status_bar import CashStatusBar
from cashcontrol.gui.tab_manager import TabManager
from cashcontrol.infrastructure.audit_logger import audit_log, get_logger
from cashcontrol.infrastructure.hot_reload_manager import HotReloadManager
from cashcontrol.infrastructure.update_client import UpdateClient

logger = get_logger()


class MainWindow(QMainWindow):
    """Top-level application window with sidebar + tabbed content."""

    _SETTINGS_GROUP = "MainWindow"

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumSize(QSize(960, 640))

        # Window icon (taskbar + title bar)
        from cashcontrol.infrastructure.path_resolver import get_app_root
        _icon_candidates = [
            get_app_root() / "icon.ico",                                        # prod
            get_app_root() / "src" / "cashcontrol" / "gui" / "resources" / "icon.ico",  # dev
        ]
        for _icon_path in _icon_candidates:
            if _icon_path.exists():
                self.setWindowIcon(QIcon(str(_icon_path)))
                break
        self.setObjectName("CashControlMainWindow")

        self._registry = ActionsRegistry()
        self._hot_reload_mgr = HotReloadManager(
            registry=self._registry, parent=self)
        from cashcontrol.infrastructure.config_manager import ConfigManager as _CM
        _cfg = _CM()
        self._update_client = UpdateClient(
            network_path=_cfg.settings.update.network_path,
            hot_reload_manager=self._hot_reload_mgr,
            parent=self,
        )

        self._init_ui()
        self._connect_update_signals()
        self._restore_geometry()

        self.set_status("Готово")
        audit_log(action_type="system", action_name="app_start", result="success")

    @property
    def registry(self) -> ActionsRegistry:
        return self._registry

    @property
    def hot_reload_manager(self) -> HotReloadManager:
        return self._hot_reload_mgr

    def _init_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        self._sidebar = SidebarPanel(self)
        root_layout.addWidget(self._sidebar)

        separator = QFrame(central)
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setFixedWidth(1)
        from cashcontrol.gui.theme_helper import color as _tc
        separator.setStyleSheet(f"background-color: {_tc('separator')};")
        root_layout.addWidget(separator)

        # Right panel
        right_panel = QWidget(central)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(2)

        self._tab_manager = TabManager(self)
        self._tab_manager.active_tab_changed.connect(self._on_tab_changed)
        self._apply_tab_styles()
        right_layout.addWidget(self._tab_manager, stretch=1)

        # Ctrl+T — быстрое добавление новой кассы
        sc_new_tab = QShortcut(QKeySequence("Ctrl+T"), self)
        sc_new_tab.activated.connect(self._tab_manager.open_add_tab_dialog)

        # Горячие клавиши быстрого запуска инструментов тулбара
        hotkeys = {
            "Ctrl+R": "_on_restart_pos",
            "Ctrl+Shift+R": "_on_reboot_terminal",
            "F2": "_on_vnc",
            "F3": "_on_ssh",
            "F4": "_on_winscp",
            "F5": "_on_refresh_info",
            "F6": "_on_postgres",
            "F7": "_on_keyboard",
            "F8": "_on_commands_clicked",
            "F9": "_on_reinstall",
            "F10": "_on_mover",
        }
        for seq, handler in hotkeys.items():
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(getattr(self._tab_manager.cash_toolbar, handler))

        self._status_bar = CashStatusBar(self)
        right_layout.addWidget(self._status_bar)

        root_layout.addWidget(right_panel, stretch=1)

        # Connect status bar to session and notification signals
        from cashcontrol.gui.history_manager import get_history_manager
        from cashcontrol.gui.notification_manager import get_notification_manager
        self._tab_manager.active_tab_changed.connect(self._status_bar.set_active_ip)
        get_history_manager().entry_added.connect(self._status_bar.add_history_entry)
        get_notification_manager().notification_added.connect(
            self._status_bar.add_notification
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_post_show_done", False):
            self._post_show_done = True
            # Отложенная инициализация: окно уже показано, тяжёлое грузим в фоне
            QTimer.singleShot(0, self._post_show_init)
        QTimer.singleShot(0, self._tab_manager.restore_sessions)
        # Запускаем клиент обновлений после старта event loop
        QTimer.singleShot(500, self._update_client.start)

    def _post_show_init(self) -> None:
        """Deferred init after the window is visible (acceleration step 5)."""
        import time as _time

        t0 = _time.perf_counter()
        try:
            self._registry.ensure_loaded()
        except Exception:
            logger.exception("Post-show init: failed to load commands")
        dt_ms = (_time.perf_counter() - t0) * 1000
        logger.debug(f"Post-show init completed in {dt_ms:.1f} ms")

    def _on_tab_changed(self, ip: object) -> None:
        """Update status when active tab changes."""
        if ip:
            self.set_status(f"Активная касса: {ip}")
        else:
            self.set_status("Готово")

    def _restore_geometry(self) -> None:
        settings = QSettings(__app_name__, __app_name__)
        settings.beginGroup(self._SETTINGS_GROUP)
        geometry = settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        settings.endGroup()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._update_client.stop()
        self._tab_manager.cleanup()  # завершить VNC и прочие внешние процессы

        settings = QSettings(__app_name__, __app_name__)
        settings.beginGroup(self._SETTINGS_GROUP)
        settings.setValue("geometry", self.saveGeometry())
        settings.endGroup()

        self._tab_manager.save_sessions()

        audit_log(action_type="system", action_name="app_close", result="success")
        super().closeEvent(event)

    def set_status(self, text: str) -> None:
        self._status_bar.set_status_text(text)

    def _apply_tab_styles(self) -> None:
        """Apply custom styles to tab bar."""
        try:
            from cashcontrol.infrastructure.path_resolver import get_app_root

            root = get_app_root()
            # Ищем styles/ в порядке: prod (cashcontrol/gui/styles/), dev (src/cashcontrol/gui/styles/)
            candidates = [
                root / "cashcontrol" / "gui" / "styles",
                root / "gui" / "styles",
                root / "src" / "cashcontrol" / "gui" / "styles",
            ]
            styles_dir = next((d for d in candidates if d.exists()), None)
            if not styles_dir:
                logger.debug("Tab styles dir not found, skipping")
                return

            tab_style_file = styles_dir / "fluent_tabs.qss"
            if tab_style_file.exists():
                tab_style = tab_style_file.read_text(encoding="utf-8")
                self._tab_manager.setStyleSheet(tab_style)
                logger.debug(f"Applied tab styles from {styles_dir}")
        except Exception as e:
            logger.warning(f"Failed to apply tab styles: {e}")

    @property
    def tab_manager(self) -> TabManager:
        return self._tab_manager

    @property
    def update_client(self) -> UpdateClient:
        return self._update_client

    def check_updates_now(self) -> None:
        """Публичный метод для вызова из settings_general."""
        self._update_client.check_now()

    def _connect_update_signals(self) -> None:
        """Подключить сигналы UpdateClient к UI."""
        uc = self._update_client

        uc.check_started.connect(
            lambda: self.set_status("🔄 Проверка обновлений…"))

        uc.check_finished.connect(
            lambda: self.set_status("Готово"))

        uc.server_status_changed.connect(self._on_update_server_status)
        uc.update_available.connect(self._on_update_available)
        uc.update_failed.connect(self._on_update_failed)
        uc.restart_required.connect(self._on_restart_required)

        self._hot_reload_mgr.reload_done.connect(self._on_reload_done)

    def _on_reload_done(self, result) -> None:
        if any("toolbar" in p.replace("\\", "/") for p in result.reloaded):
            self._tab_manager.reload_toolbar()

    def _on_update_server_status(self, online: bool) -> None:
        if not online:
            from cashcontrol.gui.notification_manager import get_notification_manager
            get_notification_manager().notify("Сервер обновлений недоступен: Работаем с текущими файлами", level="warning")

    def _on_update_available(self, result) -> None:
        if not result.updated and not result.cold_files:
            return

        from cashcontrol.gui.notification_manager import get_notification_manager
        nm = get_notification_manager()

        if result.updated:
            detail = f"Обновлено файлов: {len(result.updated)}"
            if result.new_version:
                detail += f"  •  v{result.new_version}"
            nm.notify(detail, level="success")

        if result.cold_files:
            nm.notify(
                f"Доступно обновление v{result.new_version}. "
                f"Оно будет применено при следующем запуске.",
                level="info",
            )

    def _on_update_failed(self, error: str) -> None:
        from cashcontrol.gui.notification_manager import get_notification_manager
        get_notification_manager().notify(f"Ошибка обновления: {error}", level="warning")

    def _on_restart_required(self, files: list) -> None:
        import sys as _sys

        from PySide6.QtWidgets import QMessageBox
        names = "\n".join(f"  • {f}" for f in files[:5])
        if len(files) > 5:
            names += f"\n  … и ещё {len(files)-5}"
        reply = QMessageBox.question(
            self,
            "Требуется перезапуск",
            f"Следующие файлы требуют перезапуска программы:\n{names}\n\nПерезапустить сейчас?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._tab_manager.save_sessions()
            from cashcontrol.infrastructure.path_resolver import _is_production
            if _is_production():
                # Prod: перезапускаем через os.execv
                import os
                exe = _sys.executable
                os.execv(exe, [exe])
            else:
                # Dev: просто уведомляем — перезапустить вручную
                QMessageBox.information(
                    self,
                    "Перезапуск",
                    "Закройте и снова откройте программу вручную\n"
                    "(в dev-режиме автоперезапуск недоступен).",
                )