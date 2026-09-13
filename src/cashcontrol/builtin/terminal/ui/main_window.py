"""Главное окно прототипа: только вкладки + терминалы (PuTTY-аскетизм).

Всё остальное — контекстные меню, хоткеи и системное меню окна (значок
в заголовке, как в PuTTY). Никаких тулбаров/статус-баров.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Optional

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTabWidget,
    QWidget,
)

import qasync

from core.session import TerminalSession
from data.profiles import HostProfile, ProfileStore
from data.snippets import SnippetStore
from ui.connect_dialog import ConnectDialog
from ui.settings_dialog import SettingsDialog
from ui.snippet_manager import SnippetManagerDialog
from ui.terminal_widget import TerminalWidget

_LOG = logging.getLogger("ssh_term.ui.main_window")

_SYS_MENU_MARKER = 0x0F00  # диапазон id для пунктов системного меню окна


class _TabBarWithMenu(QTabWidget):
    """Вкладки с контекстным меню (переименовать/дублировать/закрыть)."""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__()
        self._main = main
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self._main.close_tab)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos) -> None:
        index = self.tabBar().tabAt(pos)
        if index < 0:
            return
        menu = QMenu(self)
        act_rename = menu.addAction("Переименовать")
        act_copy = menu.addAction("Дублировать подключение")
        menu.addSeparator()
        act_close = menu.addAction("Закрыть")
        chosen = menu.exec(self.tabBar().mapToGlobal(pos))
        if chosen == act_rename:
            self._main.rename_tab(index)
        elif chosen == act_copy:
            self._main.duplicate_tab(index)
        elif chosen == act_close:
            self._main.close_tab(index)


class MainWindow(QMainWindow):
    """Минимальное окно: заголовок + вкладки. Статус — в заголовке окна."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SSH Terminal")
        self.resize(900, 600)

        self.store = ProfileStore()
        self.snippets = SnippetStore()
        self._sessions: dict[QWidget, TerminalSession] = {}

        self.tabs = _TabBarWithMenu(self)

        # центральный виджет: вкладки + тонкая полоса подсказок внизу
        from PySide6.QtWidgets import QVBoxLayout, QWidget as _QW

        from ui.keyhint_bar import KeyHintBar

        central = _QW()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tabs, 1)
        self.hint_bar = KeyHintBar()
        layout.addWidget(self.hint_bar)
        self.setCentralWidget(central)
        self.tabs.setDocumentMode(True)  # компактные вкладки в стиле PuTTY
        self._setup_hints()

        # хоткеи (всё управление)
        self._add_shortcut("Ctrl+N", self.new_connection)
        self._add_shortcut("Ctrl+T", self.new_connection)
        self._add_shortcut("Ctrl+W", self._close_current)
        self._add_shortcut("Ctrl+Tab", self._next_tab)
        self._add_shortcut("Ctrl+Shift+Tab", self._prev_tab)
        self._add_shortcut("Ctrl++", self._font_up)
        self._add_shortcut("Ctrl+=", self._font_up)
        self._add_shortcut("Ctrl+-", self._font_down)
        self._add_shortcut("Ctrl+0", self._font_reset)
        self._add_shortcut("Ctrl+Alt+M", self.show_main_menu)
        self._add_shortcut("Ctrl+Alt+D", self.toggle_stream_dump)

        self._setup_system_menu()

        self._apply_settings(silent=True)

        QTimer.singleShot(100, self._maybe_show_connect)

    def toggle_stream_dump(self) -> None:
        """Ctrl+Alt+D — дамп сырого вывода активной сессии в session_dump.log."""
        widget = self.tabs.currentWidget()
        session = self._sessions.get(widget)
        if session is None:
            self._set_status("Нет активной сессии")
            return
        if session.stream_dump is not None:
            path = session.stop_stream_dump()
            self._set_status(f"Дамп остановлен: {path}")
        else:
            from datetime import datetime
            from pathlib import Path

            path = Path(__file__).resolve().parent.parent / "session_dump.log"
            session.start_stream_dump(path)
            self._set_status(f"Дамп пишется: {path}")

    # ==================== СИСТЕМНОЕ МЕНЮ ОКНА (PuTTY-style) ====================

    def show_main_menu(self) -> None:
        """Главное меню программы (Ctrl+Alt+M): все действия в одном месте."""
        menu = QMenu(self)
        act_new = menu.addAction("Новое подключение…\tCtrl+N")
        act_dup = menu.addAction("Дублировать подключение")
        menu.addSeparator()
        act_settings = menu.addAction("Настройки…")
        act_snippets = menu.addAction("Сниппеты…")
        menu.addSeparator()
        act_fup = menu.addAction("Шрифт крупнее\tCtrl++")
        act_fdown = menu.addAction("Шрифт мельче\tCtrl+-")
        act_clear = menu.addAction("Очистить буфер")
        menu.addSeparator()
        act_quit = menu.addAction("Выход")

        chosen = menu.exec(self.mapToGlobal(self.rect().center() - QPoint(100, 160)))
        if chosen == act_new:
            self.new_connection()
        elif chosen == act_dup:
            self.duplicate_tab(self.tabs.currentIndex())
        elif chosen == act_settings:
            self._open_settings()
        elif chosen == act_snippets:
            self._open_snippet_manager()
        elif chosen == act_fup:
            self._font_up()
        elif chosen == act_fdown:
            self._font_down()
        elif chosen == act_clear:
            self._clear_scrollback()
        elif chosen == act_quit:
            self.close()

    def _setup_hints(self) -> None:
        """Тонкая строка подсказок внизу — терминальный ^N-стиль."""
        items = [
            ("Ctrl+N", "Подкл."),
            ("Ctrl+W", "Закрыть"),
            ("Ctrl+Shift+C/V", "Копир./Вставить"),
            ("Ctrl+Alt+M", "Меню"),
            ("Ctrl++/-", "Шрифт"),
            ("Shift+ПКМ", "Меню терминала"),
        ]
        handlers = [
            self.new_connection,
            self._close_current,
            None,  # копипаста — в самом терминале
            None,  # сниппет — в активном терминале
            None,
            None,
            None,
        ]
        self.hint_bar.set_items(items)
        for i, h in enumerate(handlers):
            if h is not None:
                self.hint_bar.set_handler(i, h)

    def _setup_system_menu(self) -> None:
        """Добавить пункты в системное меню окна (значок в заголовке)."""
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = int(self.winId())
            hmenu = ctypes.windll.user32.GetSystemMenu(hwnd, False)
            if not hmenu:
                return
            AppendMenuW = ctypes.windll.user32.AppendMenuW
            AppendMenuW(hmenu, 0x0800, 0, None)  # MF_SEPARATOR
            AppendMenuW(hmenu, 0x0000, _SYS_MENU_MARKER + 1, "Новое подключение\tCtrl+N")
            AppendMenuW(hmenu, 0x0000, _SYS_MENU_MARKER + 2, "Дублировать подключение")
            AppendMenuW(hmenu, 0x0000, _SYS_MENU_MARKER + 3, "Настройки…")
            AppendMenuW(hmenu, 0x0000, _SYS_MENU_MARKER + 4, "Сниппеты…")
            AppendMenuW(hmenu, 0x0800, 0, None)
            AppendMenuW(hmenu, 0x0000, _SYS_MENU_MARKER + 5, "Шрифт крупнее\tCtrl++")
            AppendMenuW(hmenu, 0x0000, _SYS_MENU_MARKER + 6, "Шрифт мельче\tCtrl+-")
            AppendMenuW(hmenu, 0x0000, _SYS_MENU_MARKER + 7, "Очистить буфер")
            self._sys_menu_hwnd = hwnd
            self._native = ctypes.windll.user32  # держим ссылку
        except Exception as exc:  # noqa: BLE001 - Windows-only фича
            _LOG.debug("system menu unavailable: %s", exc)

    def nativeEvent(self, event_type, message):
        """Ловим WM_SYSCOMMAND для своих пунктов системного меню."""
        if event_type == "windows_generic_MSG":
            import ctypes

            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x0112:  # WM_SYSCOMMAND
                cmd = int(msg.wParam) & 0xFFF0
                if cmd > _SYS_MENU_MARKER:
                    choice = cmd - _SYS_MENU_MARKER
                    dispatch = {
                        1: self.new_connection,
                        2: lambda: self.duplicate_tab(self.tabs.currentIndex()),
                        3: self._open_settings,
                        4: self._open_snippet_manager,
                        5: self._font_up,
                        6: self._font_down,
                        7: self._clear_scrollback,
                    }
                    if choice in dispatch:
                        QTimer.singleShot(0, dispatch[choice])
                        return True, 0
        return super().nativeEvent(event_type, message)

    # ==================== ПОДКЛЮЧЕНИЕ / ВКЛАДКИ ====================

    def new_connection(self, profile: Optional[HostProfile] = None) -> None:
        if profile is None:
            dlg = ConnectDialog(self.store, self)
            if dlg.exec() != ConnectDialog.DialogCode.Accepted or dlg.profile is None:
                return
            profile = dlg.profile

        session = TerminalSession(profile, self.store, parent=self)
        widget = TerminalWidget(emulator=session.emulator)

        # режим стрелок из настроек (global; mc на некоторых кассах требует "app")
        mode = self.store.settings.cursor_keys_mode
        widget.forced_cursor_mode = None if mode == "auto" else mode

        # сниппеты: ПКМ-меню, Ctrl+Space и inline-автодополнение
        widget.snippet_provider = self.snippets.search
        widget.snippet_inserter = self.insert_snippet
        widget.snippet_search_requested = self._show_snippet_search
        self._add_widget_shortcut(widget, "Ctrl+Space", lambda w=widget: self._show_snippet_search(w))

        # связи: терминал -> сессия
        widget.dataToWrite.connect(session.write)
        widget.sizeChanged.connect(
            lambda rows, cols, w=widget: self._on_terminal_resize(w, rows, cols)
        )
        widget.titleChanged.connect(lambda t, s=session: self._on_title(s, t))
        widget.cursorModeChanged.connect(self._save_cursor_mode)

        # связи: сессия -> окно
        session.statusChanged.connect(self._set_status)
        session.connected.connect(lambda s=session, w=widget: self._mark_connected(s, w))
        session.disconnected.connect(lambda r, s=session: self._on_disconnected(s, r))
        session.connectionFailed.connect(lambda e, s=session: self._on_conn_failed(s, e))
        session.outputReceived.connect(widget.note_data)

        self._sessions[widget] = session

        title = f"{profile.username}@{profile.host}"
        index = self.tabs.addTab(widget, title)
        self.tabs.setCurrentIndex(index)
        widget.setFocus()

        session.start()
        self._ensure_repaint_timer()

    def close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is None:
            return
        session = self._sessions.pop(widget, None)
        if session is not None:
            session.abort()
        self.tabs.removeTab(index)
        widget.deleteLater()
        self._refresh_title()

    def rename_tab(self, index: int) -> None:
        current = self.tabs.tabText(index)
        text, ok = QInputDialog.getText(self, "Переименовать", "Название вкладки:", text=current)
        if ok and text:
            self.tabs.setTabText(index, text)
            self._refresh_title()

    def duplicate_tab(self, index: int) -> None:
        session = self._sessions.get(self.tabs.widget(index))
        if session is not None:
            self.new_connection(session.profile)

    def _close_current(self) -> None:
        self.close_tab(self.tabs.currentIndex())

    def _next_tab(self) -> None:
        if (n := self.tabs.count()) > 0:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % n)

    def _prev_tab(self) -> None:
        if (n := self.tabs.count()) > 0:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % n)

    # ==================== СЕССИЯ ====================

    def _mark_connected(self, session: TerminalSession, widget: TerminalWidget) -> None:
        self._refresh_title()

    def _on_disconnected(self, session: TerminalSession, reason: str) -> None:
        for widget, s in list(self._sessions.items()):
            if s is session:
                idx = self.tabs.indexOf(widget)
                if idx >= 0:
                    self.tabs.setTabText(idx, f"{self.tabs.tabText(idx)} [отключено]")
        self._set_status(f"Отключено: {reason}")

    def _on_conn_failed(self, session: TerminalSession, error: str) -> None:
        # emit приходит коркой ИЗ asyncio-задачи _connect_and_open_pty:
        # модальный QMessageBox.exec() блокировал бы вложенным Qt-loop'ом
        # qasync-цикл ("Cannot enter into task ... while another task ...").
        QTimer.singleShot(0, lambda: self._show_conn_failed(session, error))

    def _show_conn_failed(self, session: TerminalSession, error: str) -> None:
        try:
            QMessageBox.warning(self, "Ошибка подключения", error)
        except RuntimeError:
            return  # окно уже закрыто до отложенного показа
        for widget, s in list(self._sessions.items()):
            if s is session:
                idx = self.tabs.indexOf(widget)
                if idx >= 0:
                    self.close_tab(idx)
        self._set_status(f"Ошибка: {error}")

    def _on_terminal_resize(self, widget: QWidget, rows: int, cols: int) -> None:
        session = self._sessions.get(widget)
        if session is not None:
            asyncio.ensure_future(session.resize_pty(rows, cols))

    def _on_title(self, session: TerminalSession, title: str) -> None:
        """OSC-заголовок хоста -> имя вкладки (как в PuTTY)."""
        if not title:
            return
        for widget, s in self._sessions.items():
            if s is session:
                idx = self.tabs.indexOf(widget)
                if idx >= 0:
                    self.tabs.setTabText(idx, title)
                    self.setWindowTitle(title)
                break

    def _disconnect_current(self) -> None:
        widget = self.tabs.currentWidget()
        session = self._sessions.get(widget)
        if session is not None:
            asyncio.ensure_future(session.close())

    # ==================== СТАТУС (в заголовке окна) ====================

    def _set_status(self, text: str) -> None:
        if text:
            self.setWindowTitle(text)

    def _refresh_title(self) -> None:
        w = self.tabs.currentWidget()
        if w is None:
            self.setWindowTitle("SSH Terminal")
            return
        session = self._sessions.get(w)
        if session is not None and session.is_connected:
            p = session.profile
            self.setWindowTitle(f"{p.username}@{p.host}:{p.port}")
        else:
            self.setWindowTitle(self.tabs.tabText(self.tabs.currentIndex()) or "SSH Terminal")

    # ==================== ШРИФТ / НАСТРОЙКИ ====================

    def _save_cursor_mode(self, mode: str) -> None:
        """Пользователь сменил режим стрелок в контекст-меню — запоминаем."""
        self.store.settings.cursor_keys_mode = mode
        self.store.save_settings()
        # применяем ко всем открытым терминалам
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, TerminalWidget):
                w.forced_cursor_mode = None if mode == "auto" else mode
        self._set_status(f"Режим стрелок: {mode}")

    def _font_up(self) -> None:
        self._set_font_size(self.store.settings.font_size + 1)

    def _font_down(self) -> None:
        self._set_font_size(self.store.settings.font_size - 1)

    def _font_reset(self) -> None:
        self._set_font_size(10.0)

    def _set_font_size(self, size: float) -> None:
        size = max(6.0, min(28.0, size))
        self.store.settings.font_size = size
        self.store.save_settings()
        self._apply_settings(silent=True)

    def _apply_settings(self, silent: bool = False) -> None:
        """Применить настройки (шрифт, scrollback) ко всем терминалам."""
        s = self.store.settings
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if not isinstance(w, TerminalWidget):
                continue
            font = QFont()
            font.setFamily(s.font_family or w._font.family())  # noqa: SLF001
            font.setPointSizeF(s.font_size)
            w.set_font(font)
            w.copy_on_select = s.copy_on_select
            if w.emulator.scrollback.maxlen != s.scrollback_lines:
                w.emulator.scrollback = deque(w.emulator.scrollback, maxlen=s.scrollback_lines)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.store, self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._apply_settings(silent=True)

    # ==================== СНИППЕТЫ ====================

    def _open_snippet_manager(self) -> None:
        SnippetManagerDialog(self.snippets, self).exec()

    def insert_snippet(self, snippet) -> None:
        """Вставить сниппет в активный терминал (меню/хоткей)."""
        w = self._current_terminal()
        if w is None:
            return
        text = snippet.command
        if snippet.send_with_enter:
            text += "\r"
        w.paste_text(text)

    def _show_snippet_search(self, widget: Optional[TerminalWidget] = None) -> None:
        """Быстрый выбор сниппета: список с фильтром (Ctrl+Space / ПКМ)."""
        items = self.snippets.all()
        if not items:
            QMessageBox.information(self, "Сниппеты", "Сниппетов пока нет — добавь в управлении")
            return
        names = [
            f"{s.name}   {('[' + ', '.join(s.tags) + ']') if s.tags else ''}" for s in items
        ]
        target = widget or self._current_terminal()
        choice, ok = QInputDialog.getItem(
            self, "Сниппет", "Команда:", names, 0, editable=True
        )
        if ok and target is not None:
            idx = names.index(choice) if choice in names else None
            if idx is not None:
                self.insert_snippet(items[idx])

    def _add_widget_shortcut(self, widget: TerminalWidget, key: str, handler) -> None:
        sc = QShortcut(QKeySequence(key), widget)
        sc.activated.connect(handler)

    def _current_terminal(self) -> Optional[TerminalWidget]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, TerminalWidget) else None

    # ==================== СЕРВИС ====================

    def _clear_scrollback(self) -> None:
        if (w := self._current_terminal()) is not None:
            w.clear_scrollback()

    def _maybe_show_connect(self) -> None:
        if not self.tabs.count():
            self.new_connection()

    def _add_shortcut(self, key: str, handler) -> None:
        sc = QShortcut(QKeySequence(key), self)
        sc.activated.connect(handler)

    # ==================== REPAINT-МОСТ ====================

    def _ensure_repaint_timer(self) -> None:
        if not hasattr(self, "_repaint_timer"):
            self._repaint_timer = QTimer(self)
            self._repaint_timer.setInterval(33)
            self._repaint_timer.timeout.connect(self._poll_sessions)
            self._repaint_timer.start()

    def _poll_sessions(self) -> None:
        """Repaint-мост: перерисовываем только виджеты, куда пришли данные."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, TerminalWidget) and w._dirty:
                QWidget.update(w)
                w._dirty = False  # новый repaint — только после новых данных

    # ==================== ЗАКРЫТИЕ ====================

    def closeEvent(self, event) -> None:
        for widget, session in list(self._sessions.items()):
            session.abort()
        self.store.save_settings()
        super().closeEvent(event)
