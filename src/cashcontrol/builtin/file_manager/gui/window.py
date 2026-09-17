"""CashSCP main window: tab bar hosting one connection session per tab."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from PySide6.QtCore import QEvent, QKeyCombination, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QLineEdit,
    QMainWindow,
    QSizePolicy,
    QTabWidget,
    QToolButton,
)

from cashcontrol.builtin.file_manager.gui.dialogs import ConnectDialog
from cashcontrol.builtin.file_manager.gui.session import RemoteSession
from cashcontrol.builtin.file_manager.gui.widgets import LogConsole, LogPanel

logger = logging.getLogger("cashcontrol.builtin.file_manager.gui")


class _PlusTabWidget(QTabWidget):
    """QTabWidget with a "+" button docked right after the last tab."""

    add_requested = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._button = QToolButton(self)
        self._button.setText("+")
        self._button.setToolTip("Подключиться к серверу (новая вкладка)")
        self._button.setAutoRaise(True)
        self._button.setFixedSize(32, 21)
        self._button.setStyleSheet(
            "QToolButton { padding: 0 6px; border: none; border-radius: 5px; font-weight: 600; }"
            " QToolButton:hover { background: rgba(120, 120, 120, 0.25); }"
        )
        self._button.clicked.connect(self.add_requested)
        self.tabBar().installEventFilter(self)
        QTimer.singleShot(0, self._place_button)

    def _place_button(self) -> None:
        bar = self.tabBar()
        last = bar.count() - 1
        x = (bar.tabRect(last).right() + 18) if last >= 0 else 6
        self._button.move(x, (bar.height() - self._button.height()) // 2)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._place_button()

    def eventFilter(self, watched: Any, event: Any) -> bool:
        if watched is self.tabBar() and event.type() in (
            QEvent.Type.LayoutRequest,
            QEvent.Type.Resize,
        ):
            self._place_button()
        return super().eventFilter(watched, event)


class RemoteFilesWindow(QMainWindow):
    """Multi-tab window; each tab is an independent RemoteSession (one host)."""

    def __init__(
        self,
        parent: Any = None,
        host: str = "",
        port: int = 22,
        username: str = "",
        password: str | None = None,
        start_dir: str = "/",
        protocol: str = "auto",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CashSCP")
        self.resize(1100, 680)

        self._console = LogConsole(self)
        self._log_panel = LogPanel(self)
        self._console.new_record.connect(self._log_panel.append)

        self._tabs = _PlusTabWidget(self)
        self._tabs.setDocumentMode(True)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.add_requested.connect(self._ask_connect)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(lambda _index: self._update_host_label())
        self.setCentralWidget(self._tabs)

        self._build_menu_bar()
        self._build_shortcuts()
        self._add_session(
            host=host,
            port=port if port else 22,
            username=username,
            password=password or "",
            start_dir=start_dir,
            protocol=protocol,
        )

        self._log_dock = QDockWidget("Журнал", self)
        self._log_dock.setObjectName("log_dock")
        self._log_dock.setWidget(self._log_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)
        self._log_dock.hide()

        self._status("Готово")
        logger.info("Окно CashSCP запущено")

    # ── sessions / tabs ─────────────────────────────────────
    def _add_session(
        self,
        host: str = "",
        port: int = 22,
        username: str = "",
        password: str = "",
        start_dir: str = "/",
        protocol: str = "auto",
    ) -> RemoteSession:
        session = RemoteSession(self)
        index = self._tabs.addTab(session, host or "—")
        session.label_changed.connect(
            lambda text, s=session: self._tabs.setTabText(self._tabs.indexOf(s), text or "—")
        )
        self._tabs.setTabToolTip(index, host or "нет подключения")
        self._tabs.setCurrentIndex(index)
        if host and username:
            session.open_connection(host, port, username, password, start_dir=start_dir, protocol=protocol)
        return session

    def _current_session(self) -> RemoteSession | None:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, RemoteSession) else None

    def _close_tab(self, index: int) -> None:
        session = self._tabs.widget(index)
        if session is None:
            return
        self._tabs.removeTab(index)
        session.shutdown()
        if self._tabs.count() == 0:
            self._add_session()

    def _update_host_label(self) -> None:
        session = self._current_session()
        text = session.host_display() if session else ""
        self._host_label.setText(text)
        self._host_label.setMinimumWidth(max(0, self._host_label.fontMetrics().horizontalAdvance(text)) + 24)

    def log_tail(self, limit: int = 120) -> list[str]:
        return self._console.tail(limit)

    def request_log(self) -> None:
        self._log_dock.show()
        self._log_dock.raise_()
        self._log_dock.widget().scroll_to_bottom()

    def _toggle_log(self) -> None:
        self._log_dock.setVisible(not self._log_dock.isVisible())
        if self._log_dock.isVisible():
            self._log_dock.widget().scroll_to_bottom()

    # ── menu bar ────────────────────────────────────────────
    def _build_menu_bar(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&Файл")
        connect_action = QAction("Подключение", self)
        connect_action.setShortcut(QKeySequence(QKeyCombination(Qt.ControlModifier, Qt.Key_O)))
        connect_action.triggered.connect(self._ask_connect)
        file_menu.addAction(connect_action)
        file_menu.addSeparator()
        close_tab_action = QAction("Закрыть вкладку", self)
        close_tab_action.setShortcut(QKeySequence(QKeyCombination(Qt.ControlModifier, Qt.Key_W)))
        close_tab_action.triggered.connect(lambda: self._tabs.count() and self._close_tab(self._tabs.currentIndex()))
        file_menu.addAction(close_tab_action)
        file_menu.addSeparator()
        file_menu.addAction("Выход", self.close)
        self.addAction(connect_action)

        actions_menu = menubar.addMenu("&Действия")
        for text, key, handler in [
            ("Новая папка", "F7", lambda s: s.new_folder()),
            ("Переименовать", "F2", lambda s: s.rename()),
            ("Копировать", "F5", lambda s: s.copy(move=False)),
            ("Переместить", "F6", lambda s: s.copy(move=True)),
            ("Удалить", "F8", lambda s: s.delete()),
            ("Свойства", "Alt+Enter", lambda s: s.properties()),
        ]:
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(lambda _checked=False, h=handler: self._delegate(h))
            actions_menu.addAction(action)
            self.addAction(action)

        view_menu = menubar.addMenu("&Вид")
        refresh_action = QAction("Обновить", self)
        refresh_action.setShortcut(QKeySequence(QKeyCombination(Qt.ControlModifier, Qt.Key_R)))
        refresh_action.triggered.connect(self._refresh_active)
        view_menu.addAction(refresh_action)
        self.addAction(refresh_action)
        self._debug_action = QAction("Технический режим (отладка)", self, checkable=True)
        self._debug_action.triggered.connect(self._set_debug_mode)
        view_menu.addAction(self._debug_action)
        view_menu.addAction("Открыть журнал", self.request_log)
        view_menu.addAction("Показать/скрыть журнал (переключение)", self._toggle_log)

        self._host_label = QLabel("", self)
        self._host_label.setObjectName("host_label")
        self._host_label.setStyleSheet("padding: 0 10px; color: #1a6fd1; font-weight: 600;")
        self._host_label.setToolTip("Активная вкладка (текущее подключение)")
        self._host_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        menubar.setCornerWidget(self._host_label, Qt.Corner.TopRightCorner)

    def _delegate(self, handler: Any) -> None:
        session = self._current_session()
        if session is not None:
            handler(session)

    def _refresh_active(self) -> None:
        session = self._current_session()
        if session is None:
            return
        panel = session._active_panel
        if panel is not None:
            session._refresh_panel(panel.kind)

    def _set_debug_mode(self, enabled: bool) -> None:
        self._console.set_debug(enabled)
        logger.info("Технический режим (DEBUG) %s", "включён" if enabled else "выключен")

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence(Qt.Key_F4), self, activated=self._edit_file)
        QShortcut(QKeySequence(QKeyCombination(Qt.ControlModifier, Qt.Key_L)), self, activated=self._focus_address)
        QShortcut(QKeySequence(Qt.Key_Backspace), self, activated=self._backspace_up)
        QShortcut(QKeySequence(QKeyCombination(Qt.ControlModifier, Qt.Key_A)), self, activated=self._select_all)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._delete_key)

    def _edit_file(self) -> None:
        session = self._current_session()
        if session is not None:
            session.edit_file()

    def _focus_address(self) -> None:
        session = self._current_session()
        if session is not None:
            session.focus_address()

    def _backspace_up(self) -> None:
        if isinstance(self.focusWidget(), QLineEdit):
            return
        session = self._current_session()
        if session is not None:
            session.backspace_up()

    def _select_all(self) -> None:
        session = self._current_session()
        if session is not None:
            session.select_all()

    def _delete_key(self) -> None:
        if isinstance(self.focusWidget(), QLineEdit):
            return
        session = self._current_session()
        if session is not None:
            session.delete()

    # ── connect (new tab) ───────────────────────────────────
    def _ask_connect(self) -> None:
        dialog = ConnectDialog(self, host="", user="", port=22)
        if not dialog.exec():
            return
        data = dialog.result_data()
        if not data["host"]:
            return
        self._add_session(
            host=str(data["host"]),
            port=int(data["port"]),
            username=str(data["username"]) or "root",
            password=str(data["password"]),
            start_dir="/",
            protocol=str(data["protocol"]),
        )

    # ── status / shutdown ───────────────────────────────────
    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def closeEvent(self, event: Any) -> None:
        for index in range(self._tabs.count()):
            session = self._tabs.widget(index)
            if session is not None:
                session.shutdown()
        super().closeEvent(event)


__all__ = ["RemoteFilesWindow"]


# --- merged from __main__.py ---


"""Entry point for running the standalone Remote Files GUI."""


def main() -> int:
    parser = argparse.ArgumentParser(prog="rfiles-gui", description="Standalone-менеджер удалённых файлов")
    parser.add_argument("--host", default="", help="хост для подключения при старте (необязательно)")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default="", help="имя пользователя SSH")
    parser.add_argument("--password", default="", help="пароль SSH (лучше переменная окружения/ключи)")
    parser.add_argument(
        "--protocol",
        choices=("auto", "sftp", "scp"),
        default="auto",
        help="протокол: auto, sftp или scp (по умолчанию auto)",
    )
    parser.add_argument("--start-dir", default="/", help="начальный удалённый каталог")
    args = parser.parse_args()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    from cashcontrol.builtin.file_manager.gui.window import RemoteFilesWindow

    app = QApplication(sys.argv)
    window = RemoteFilesWindow(
        host=args.host,
        port=args.port,
        username=args.user,
        password=args.password or None,
        start_dir=args.start_dir,
        protocol=args.protocol,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
