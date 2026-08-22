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

        self._init_ui()
        self._restore_geometry()

        self.set_status("Готово")
        audit_log(action_type="system", action_name="app_start", result="success")

    @property
    def registry(self) -> ActionsRegistry:
        return self._registry

    def _init_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        self._sidebar = SidebarPanel(self)
        root_layout.addWidget(self._sidebar)

        sep_box = QWidget(central)
        sep_lay = QVBoxLayout(sep_box)
        sep_lay.setContentsMargins(0, 8, 0, 8)
        sep_lay.setSpacing(0)
        separator = QFrame(sep_box)
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setFixedWidth(1)
        from cashcontrol.gui.theme_helper import color as _tc
        separator.setStyleSheet(f"background-color: {_tc('separator')};")
        sep_lay.addWidget(separator)
        root_layout.addWidget(sep_box)

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

        # Горячие клавиши быстрого запуска инструментов.
        # QKeySequence привязывается по коду клавиши — работает на любой раскладке.
        toolbar_hotkeys = {
            "Ctrl+S": "_on_ssh",
            "Ctrl+W": "_on_winscp",
            "Ctrl+D": "_on_postgres",
            "Ctrl+R": "_on_restart_pos",
            "Ctrl+Shift+R": "_on_reboot_terminal",
            "F5": "_on_refresh_info",
            "F6": "_on_postgres",
            "F7": "_on_keyboard",
            "F8": "_on_commands_clicked",
        }
        for seq, handler in toolbar_hotkeys.items():
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(getattr(self._tab_manager.cash_toolbar, handler))

        sc_vnc = QShortcut(QKeySequence("Ctrl+V"), self)
        sc_vnc.activated.connect(self._hotkey_vnc_embedded)
        sc_vnc_ext = QShortcut(QKeySequence("Ctrl+Shift+V"), self)
        sc_vnc_ext.activated.connect(self._hotkey_vnc_external)

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

    # ── VNC hotkeys ──────────────────────────────────────────────────────

    def _active_session_widget(self):
        return self._tab_manager.get_active_session()

    def _hotkey_vnc_embedded(self) -> None:
        """Ctrl+V — подключить встроенный VNC-просмотр активной кассы."""
        sw = self._active_session_widget()
        if sw is None:
            self.set_status("Нет активной вкладки кассы")
            return
        sw.connect_vnc()

    def _hotkey_vnc_external(self) -> None:
        """Ctrl+Shift+V — открыть внешнее VNC-приложение для активной кассы."""
        sw = self._active_session_widget()
        if sw is None:
            self.set_status("Нет активной вкладки кассы")
            return
        sw.open_vnc_external()

    def _restore_geometry(self) -> None:
        settings = QSettings(__app_name__, __app_name__)
        settings.beginGroup(self._SETTINGS_GROUP)
        geometry = settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        settings.endGroup()

    def closeEvent(self, event: QCloseEvent) -> None:
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
