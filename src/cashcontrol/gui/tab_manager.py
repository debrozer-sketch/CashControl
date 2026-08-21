"""Tab manager — manages cash session tabs."""

from __future__ import annotations

import asyncio

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cashcontrol.gui.cash_session_widget import CashSessionWidget
from cashcontrol.gui.session_manager import SessionManager
from cashcontrol.gui.tab_bar import CashTabBar
from cashcontrol.infrastructure.audit_logger import audit_log, get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()




class TabManager(QWidget):
    active_tab_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = ConfigManager()
        # Theme is already applied by ThemeEngine in main.py before MainWindow
        self._session_mgr = SessionManager(self)
        self._session_mgr.ping_status_changed.connect(self._set_tab_dot)
        self._init_ui()
        self.apply_theme_styles()

    def apply_theme_styles(self) -> None:
        """
        Keep for backward compatibility.
        Global QSS is handled by ThemeEngine; here we only update
        widget-specific inline styles that ThemeEngine cannot know about.
        """
        try:
            # ThemeEngine handles the global QApplication stylesheet — just emit
            from cashcontrol.gui.theme_engine import ThemeEngine
            from cashcontrol.gui.theme_helper import color as _tc
            ThemeEngine.instance()._apply_stylesheet()

            # ── Widget-specific inline styles ──
            # Placeholder
            if hasattr(self, '_placeholder'):
                self._placeholder.setStyleSheet(
                    f"color: {_tc('text_secondary')}; font-size: 16px; padding: 40px;"
                )

            # Toolbar button labels
            for child in self.findChildren(QLabel):
                ss = child.styleSheet()
                if 'font-size: 9px' in ss and 'background: transparent' in ss:
                    child.setStyleSheet(
                        f"font-size: 9px; color: {_tc('text_secondary')}; background: transparent;"
                    )

            # Update separators in main_window
            mw = self.window()
            if mw:
                for frame in mw.findChildren(QFrame):
                    if frame.frameShape() == QFrame.Shape.VLine:
                        frame.setStyleSheet(f"background-color: {_tc('separator')};")

                # Update status label
                status_lbl = getattr(mw, '_status_label', None)
                if status_lbl:
                    status_lbl.setStyleSheet(
                        f"color: {_tc('text_secondary')}; font-size: 11px; padding: 2px 4px;"
                    )

            # Refresh all CashSessionWidgets
            for ip in self._session_mgr.get_all_ips():
                session_widget = self._session_mgr.get_session(ip)
                if hasattr(session_widget, '_refresh_theme'):
                    session_widget._refresh_theme()

        except Exception:
            pass

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tab_bar = CashTabBar(self)
        self._tab_bar.tab_add_requested.connect(self._on_add_tab_clicked)
        self._tab_bar.tab_close_requested.connect(self.close_tab)
        self._tab_bar.tab_selected.connect(self._on_tab_selected)
        self._tab_bar.tab_ip_changed.connect(self._on_tab_ip_changed)
        self._tab_bar.tab_refresh_requested.connect(self._on_tab_refresh_requested)
        layout.addWidget(self._tab_bar)

        self._init_toolbar()
        layout.addWidget(self._cash_toolbar)

        self._stack = QStackedWidget(self)

        self._placeholder = QLabel("Нажмите  +  или  Ctrl+T  чтобы добавить кассу", self._stack)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from cashcontrol.gui.theme_helper import color as _thc
        self._placeholder.setStyleSheet(f"color: {_thc('text_secondary')}; font-size: 16px; padding: 40px;")
        self._stack.addWidget(self._placeholder)

        layout.addWidget(self._stack, stretch=1)

        self._update_state()

    def _init_toolbar(self) -> None:
        from cashcontrol.infrastructure.module_loader import get_class
        _CashToolbar = get_class("cashcontrol.gui.toolbar", "CashToolbar")
        self._cash_toolbar = _CashToolbar(self._session_mgr, self)
        self._cash_toolbar.hide()

    @property
    def cash_toolbar(self):
        """Public accessor for the cash toolbar (used by main window hotkeys)."""
        return self._cash_toolbar

    def _on_session_info_loaded(self, ip: str, cash_type: str) -> None:
        if ip == self._session_mgr.active_ip:
            self._cash_toolbar.update_for_cash_type(cash_type)

    def _update_state(self) -> None:
        has_tabs = self._session_mgr.session_count() > 0
        self._cash_toolbar.setVisible(has_tabs)
        if not has_tabs:
            self._stack.setCurrentWidget(self._placeholder)

    def reload_toolbar(self) -> None:
        layout = self.layout()
        layout.removeWidget(self._cash_toolbar)
        self._cash_toolbar.deleteLater()

        was_visible = self._session_mgr.session_count() > 0
        current_cash_type = None
        active_ip = self._session_mgr.active_ip
        if active_ip:
            session = self._session_mgr.get_session(active_ip)
            if session:
                current_cash_type = getattr(session, "cash_type", None)

        self._init_toolbar()

        if current_cash_type:
            self._cash_toolbar.update_for_cash_type(current_cash_type)
        self._cash_toolbar.setVisible(was_visible)
        layout.insertWidget(1, self._cash_toolbar)

    # ── CashTabBar handlers ────────────────────────────────

    def _on_tab_selected(self, ip: str) -> None:
        if not ip:
            self._session_mgr.active_ip = None
            self.active_tab_changed.emit(None)
            return
        session = self._session_mgr.get_session(ip)
        if session:
            self._stack.setCurrentWidget(session)
        self._session_mgr.active_ip = ip
        self.active_tab_changed.emit(ip)
        self._start_ping(ip)
        cash_type = getattr(session, "cash_type", None) if session else None
        self._cash_toolbar.update_for_cash_type(cash_type)

    def _on_tab_ip_changed(self, old_ip: str, new_ip: str) -> None:
        if new_ip:
            self.change_tab_ip(old_ip, new_ip)
        else:
            sw = self._session_mgr.get_session(old_ip)
            if sw:
                sw.start_ip_edit()

    def _on_tab_refresh_requested(self, ip: str) -> None:
        sw = self._session_mgr.get_session(ip)
        if sw:
            import asyncio
            asyncio.ensure_future(sw.load_info(force=True))

    def _set_tab_dot(self, ip: str, status: str) -> None:
        self._tab_bar.set_ping_status(ip, status)

    # ── Ping loop ──────────────────────────────────────────

    def _start_ping(self, ip: str) -> None:
        self._session_mgr.start_ping(ip)

    def _stop_ping(self) -> None:
        self._session_mgr.stop_ping()

    # ── Tab management ─────────────────────────────────────

    def add_tab(self, ip: str, connect: bool = True) -> CashSessionWidget | None:
        ip = ip.strip()
        if not ip:
            return None

        if self._session_mgr.has_session(ip):
            self._tab_bar.set_active(ip)
            return self._session_mgr.get_session(ip)

        max_tabs = self._config.settings.general.max_tabs
        if self._session_mgr.session_count() >= max_tabs:
            QMessageBox.warning(self, "Лимит вкладок", f"Максимальное количество вкладок: {max_tabs}")
            return None

        session_widget = CashSessionWidget(ip, parent=self)
        self._session_mgr.add_session(ip, session_widget)
        self._stack.addWidget(session_widget)

        session_widget.info_loaded.connect(
            lambda cash_type, i=ip: self._on_session_info_loaded(i, cash_type)
        )

        self._tab_bar.add_tab(ip)
        self._tab_bar.set_active(ip)
        self._stack.setCurrentWidget(session_widget)

        # Автоподключение и сбор информации сразу при открытии вкладки.
        # При массовом восстановлении connect=False — волны задаёт
        # restore_sessions_async() (Semaphore(3)).
        if connect:
            session_widget.start_connecting()

        self._update_state()
        self._session_mgr.save_sessions()
        audit_log(action_type="connection", action_name="tab_open", target=ip, result="success")
        logger.info(f"Added tab for {ip}")
        self._start_ping(ip)
        return session_widget

    def close_tab(self, ip: str) -> None:
        if not self._session_mgr.has_session(ip):
            return

        if self._session_mgr.active_ip == ip:
            self._stop_ping()

        self._tab_bar.remove_tab(ip)
        self._session_mgr.kill_vnc(ip)
        widget = self._session_mgr.remove_session(ip)
        if widget:
            widget.cleanup()
            self._stack.removeWidget(widget)
            widget.deleteLater()
        self._update_state()
        self._session_mgr.save_sessions()
        logger.info(f"Closed tab for {ip}")

    def get_active_session(self) -> CashSessionWidget | None:
        current = self._stack.currentWidget()
        if isinstance(current, CashSessionWidget):
            return current
        return None

    # ── Tab events ─────────────────────────────────────────

    def _on_add_tab_clicked(self) -> None:
        from cashcontrol.gui.dialogs.add_cash_dialog import AddCashDialog
        dialog = AddCashDialog(self)
        if dialog.exec():
            ip = dialog.get_ip()
            if ip:
                self.add_tab(ip)

    def open_add_tab_dialog(self) -> None:
        self._on_add_tab_clicked()

    def change_tab_ip(self, old_ip: str, new_ip: str) -> None:
        new_ip = new_ip.strip()
        if not new_ip or new_ip == old_ip:
            return

        if self._session_mgr.has_session(new_ip):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Уже открыта",
                                f"Вкладка для {new_ip} уже существует.")
            return

        sw = self._session_mgr.remove_session(old_ip)
        if sw is None:
            return

        self._session_mgr.add_session(new_ip, sw)
        self._tab_bar.update_route_key(old_ip, new_ip)
        self._session_mgr.move_vnc(old_ip, new_ip)
        self._session_mgr.save_sessions()
        logger.info(f"Tab IP changed: {old_ip} → {new_ip}")
        asyncio.ensure_future(sw.reconnect_to(new_ip))

    # ── Sessions persistence ───────────────────────────────

    def cleanup(self) -> None:
        self._session_mgr.cleanup()

    def save_sessions(self) -> None:
        self._session_mgr.save_sessions()

    def restore_sessions(self) -> None:
        ips = self._session_mgr.restore_sessions()
        if not ips:
            return
        logger.info(f"Restoring {len(ips)} sessions: {ips}")
        widgets: list[CashSessionWidget] = []
        for ip in ips:
            w = self.add_tab(ip, connect=False)
            if w is not None:
                widgets.append(w)
        if ips and self._session_mgr.has_session(ips[-1]):
            last_ip = ips[-1]
            self._tab_bar.set_active(last_ip)
            self._stack.setCurrentWidget(self._session_mgr.get_session(last_ip))
            logger.debug(f"Activated last tab: {last_ip}")
        if widgets:
            asyncio.ensure_future(self._connect_in_waves(widgets))

    async def _connect_in_waves(self, widgets: list[CashSessionWidget]) -> None:
        """Connect restored tabs in waves of 3 so a dead host doesn't stall others."""
        sem = asyncio.Semaphore(3)

        async def _one(w: CashSessionWidget) -> None:
            async with sem:
                await w.connect_coro()

        await asyncio.gather(
            *(_one(w) for w in widgets), return_exceptions=True
        )