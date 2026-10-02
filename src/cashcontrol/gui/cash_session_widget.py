from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, override

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ToolButton,
)

from cashcontrol.builtin.vnc.vnc_preview import VncPreviewWidget
from cashcontrol.core.cash_types import get_cash_type_registry, has_feature
from cashcontrol.core.info import check as check_problems
from cashcontrol.core.info import get_info_collector
from cashcontrol.core.info.info_manager import (
    SECTION_GROUPS,
    CollectionStatus,
    InfoField,
    InfoSection,
)
from cashcontrol.core.info.sections import renderer_for
from cashcontrol.core.session import CashSession
from cashcontrol.gui import feedback
from cashcontrol.gui.ip_input import install_comma_to_dot
from cashcontrol.gui.notification_manager import Level
from cashcontrol.gui.theme_helper import font_size
from cashcontrol.gui.widgets.info_section_widget import (
    InfoGroupWidget,
    ProblemListWidget,
)
from cashcontrol.infrastructure.audit_logger import audit_log, get_logger
from cashcontrol.infrastructure.task_runner import spawn

if TYPE_CHECKING:
    from cashcontrol.core.info.info_manager import CashInfoSnapshot

logger = get_logger()

# Паузы между попытками подключения для отправки файлов. TinyCore не
# принимает серию подключений подряд, поэтому одна попытка часто мало.
TRANSFER_CONNECT_DELAYS = (0.0, 2.5, 5.0)

def _group_of(section: str) -> str | None:
    """Группа секции по данным реестра.

    Раньше здесь стоял свой словарь, повторявший SECTION_GROUPS, и он
    разошёлся с ним при появлении новой секции: секция попадала в сбор, но
    не находила свою группу и молча не рисовалась.
    """
    for group, names in SECTION_GROUPS.items():
        if section in names:
            return group
    return None


_GROUP_TITLES: dict[str, str] = {
    "system": "Касса",
    "equipment": "Оборудование",
    "other": "Прочее",
    "problems": "Проблемы",
}

_GROUP_KEYS = ["system", "equipment", "other"]
_SKELETON_KEYS = ["system", "equipment", "other"]  # groups with loading skeletons


class CashSessionWidget(QWidget):
    """
    Content widget for a single cash register session tab.

    Manages SSH connection, info panel (OS, equipment, peripherals),
    embedded VNC viewer, and reconnection logic.
    """

    info_loaded = Signal(str)
    connection_state_changed = Signal(str, str)  # ip, status
    _section_ready = Signal(object)  # InfoSection

    def __init__(self, ip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ip = ip
        self._session: CashSession | None = None
        self._info_loaded = False
        self._last_info_ok = 0.0
        self._loading = False
        # Состояние пишущей дорожки: между нажатием «Исправить» и концом
        # записи второе нажатие игнорируется, иначе два диалога подтверждения
        # на одну и ту же кассу.
        self._fix_busy = False
        self._fix_plan = None
        self._fix_id = ""
        self._connect_task: asyncio.Task | None = None
        self._info_task: asyncio.Task | None = None
        self._group_widgets: dict[str, InfoGroupWidget] = {}
        self._extra_widgets: list[QWidget] = []
        self._os_type: str = "tinycore"
        self._cash_type: str = "unknown"
        self._ip_edit_widget: QWidget | None = None
        self._reconnect_btn_shown: bool = False
        # VNC был открыт до обрыва: после восстановления SSH его нужно поднять
        # заново. Явное отключение пользователем сбрасывает флаг.
        self._vnc_was_open: bool = False
        self._ssh_was_down: bool = False
        self._init_ui()
        self._section_ready.connect(self._render_section)
        from cashcontrol.gui.theme_engine import ThemeEngine

        self._theme_conn_signal = ThemeEngine.instance().theme_changed
        self._theme_conn_signal.connect(self._refresh_theme)
        self._connect_task = None

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def session(self) -> CashSession | None:
        return self._session

    @property
    def keyboard_model(self) -> str | None:
        return getattr(self, "_keyboard_model", None)

    @property
    def os_type(self) -> str:
        return self._os_type

    @property
    def cash_type(self) -> str:
        return self._cash_type

    # ── UI ──────────────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(0)

        # Перетаскивание файла с рабочего стола на вкладку кассы:
        # файл уезжает на кассу в фоне, окно CashSCP не открывается.
        self.setAcceptDrops(True)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        self._vnc_widget = VncPreviewWidget(self._ip, parent=self)
        self._vnc_widget.setMinimumWidth(300)
        self._vnc_widget.state_changed.connect(self._on_vnc_state_changed)
        splitter.addWidget(self._vnc_widget)

        right_panel = self._build_info_panel()
        right_panel.setMinimumWidth(400)
        splitter.addWidget(right_panel)

        splitter.setSizes([400, 600])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter, stretch=1)

        vnc_bar = QWidget(self)
        vnc_bar.setFixedHeight(40)
        vnc_bar.setStyleSheet("background: transparent;")
        bar_layout = QHBoxLayout(vnc_bar)
        bar_layout.setContentsMargins(6, 4, 6, 4)
        bar_layout.setSpacing(6)

        self._btn_vnc_connect = PushButton("Подключить", vnc_bar)
        self._btn_vnc_connect.clicked.connect(self._vnc_widget.connect_vnc)
        bar_layout.addWidget(self._btn_vnc_connect)

        self._btn_vnc_disconnect = PushButton("Отключить", vnc_bar)
        self._btn_vnc_disconnect.clicked.connect(self.disconnect_vnc)
        self._btn_vnc_disconnect.hide()
        bar_layout.addWidget(self._btn_vnc_disconnect)

        self._btn_vnc_fullscreen = PushButton("Полный экран", vnc_bar, FluentIcon.FULL_SCREEN)
        self._btn_vnc_fullscreen.clicked.connect(self._vnc_widget.open_fullscreen)
        bar_layout.addWidget(self._btn_vnc_fullscreen)

        self._vnc_status_label = QLabel("", vnc_bar)
        from cashcontrol.gui.theme_helper import color as _tc

        self._vnc_status_label.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: {font_size('hint')}px;"
        )
        bar_layout.addWidget(self._vnc_status_label)

        bar_layout.addStretch()
        root.addWidget(vnc_bar)

    def _on_vnc_state_changed(self, state: str, message: str) -> None:
        from cashcontrol.gui.theme_helper import color as _tc

        if state == "idle":
            self._vnc_was_open = False
            self._btn_vnc_connect.setVisible(True)
            self._btn_vnc_connect.setEnabled(True)
            self._btn_vnc_disconnect.setVisible(False)
            self._btn_vnc_fullscreen.setEnabled(True)
            self._vnc_status_label.setText("")
        elif state == "connecting":
            self._btn_vnc_connect.setVisible(True)
            self._btn_vnc_connect.setEnabled(False)
            self._btn_vnc_disconnect.setVisible(False)
            self._btn_vnc_fullscreen.setEnabled(False)
            self._vnc_status_label.setText(message)
        elif state == "connected":
            self._vnc_was_open = True
            self._btn_vnc_connect.setVisible(False)
            self._btn_vnc_disconnect.setVisible(True)
            self._btn_vnc_fullscreen.setEnabled(True)
            self._vnc_status_label.setText("подключено")
            self._vnc_status_label.setStyleSheet(
                f"color: {_tc('success')}; font-size: {font_size('hint')}px;"
            )
        elif state == "error":
            self._btn_vnc_connect.setVisible(True)
            self._btn_vnc_connect.setEnabled(True)
            self._btn_vnc_disconnect.setVisible(False)
            self._btn_vnc_fullscreen.setEnabled(True)
            self._vnc_status_label.setText("ошибка")
            self._vnc_status_label.setStyleSheet(
                f"color: {_tc('error')}; font-size: {font_size('hint')}px;"
            )

    # ── Info panel ──────────────────────────────────────────────────────────

    def _build_info_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setFrameShape(QFrame.Shape.StyledPanel)

        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._info_content = QWidget()
        # Минимальная ширина контейнера снята намеренно. QLabel с переносом
        # считает minimumSizeHint по самой длинной неразрывной части, а на
        # кассе это путь к профилю вроде
        # /home/tc/storage/crystal-cash/... — слово без пробелов на 130+
        # символов. Такое значение раздувало содержимое до 1344 px, панель
        # переставала сжиматься вместе с окном, а кнопка «Исправить» уезжала
        # целиком за правый край. setWidgetResizable этот минимум не снимает.
        self._info_content.setMinimumWidth(0)
        self.info_layout = QVBoxLayout(self._info_content)
        self.info_layout.setContentsMargins(8, 8, 8, 8)
        self.info_layout.setSpacing(12)

        self.loading_label = QLabel("Подключение...")
        from cashcontrol.gui.theme_helper import color as _tc

        self.loading_label.setStyleSheet(
            f"font-size: {font_size('value')}px; color: {_tc('text_secondary')};"
        )
        self.info_layout.addWidget(self.loading_label)
        self.info_layout.addStretch()

        scroll.setWidget(self._info_content)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Ход сбора логов показывается прямо в зоне коллекторов:
        # строка появляется на время работы и сама скрывается через 15 секунд
        from cashcontrol.gui.collect_progress import CollectStatusBar

        self.collect_status = CollectStatusBar(panel)
        layout.addWidget(self.collect_status)
        layout.addWidget(scroll)

        return panel

    # ── Connection ──────────────────────────────────────────────────────────

    def start_connecting(self) -> asyncio.Task | None:
        """Start SSH connection in background. Returns task for awaiting.

        Sync method — schedules the async connect and returns immediately.
        Callers can await the returned task in async context or fire-and-forget.
        """
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()

        self._connect_task = asyncio.ensure_future(self.connect_coro())
        return self._connect_task

    async def connect_coro(self) -> None:
        """Full connect + info-load sequence. Awaitable — supports wave limiting."""
        try:
            self._session = CashSession(self._ip)
            success = await self._session.connect(connect_db=False)

            task = asyncio.current_task()
            if task and task.cancelled():
                return

            if not success:
                self.connection_state_changed.emit(self._ip, "timeout")
                msg = self._session.error_message or "Не удалось подключиться"
                self.loading_label.setText(msg)
                self._show_reconnect_button(msg)
                return

            self.loading_label.setText("SSH подключено")
            self._reconnect_btn_shown = False
            self.connection_state_changed.emit(self._ip, "ok")
            from datetime import datetime as _dt

            from cashcontrol.gui.history_manager import HistoryEntry, get_history_manager
            with contextlib.suppress(Exception):
                get_history_manager().add(self._ip, HistoryEntry(
                    timestamp=_dt.now(), action_name="Подключение",
                    result="success", details=f"SSH {self._ip}", ip=self._ip))
            self._vnc_widget.set_session(self._session)

            if getattr(self, "_vnc_resume", False):
                self._vnc_resume = False
                self._vnc_was_open = True
                self.connect_vnc()

            from cashcontrol.core.info.collectors.cash_type import (
                CashTypeCollector,
            )

            type_data = await CashTypeCollector().collect(self._session)
            cash_type = type_data.get("cash_type", "unknown")

            ctype_def = get_cash_type_registry().get(cash_type)
            if ctype_def and ctype_def.connection.db.enabled:
                database = ctype_def.connection.db.database or "sco_v3"
                self._session.setup_db(database=database)
                # БД подключается фоном параллельно с волной коллекторов;
                # коллекторы с *_from_db дождутся db_connect_task.
                self._session.db_connect_task = asyncio.ensure_future(
                    self._connect_db_notified(database)
                )

            await self.load_info()

        except asyncio.CancelledError:
            logger.debug(f"Connect task cancelled for {self._ip}")
        except Exception as e:
            self.connection_state_changed.emit(self._ip, "timeout")
            msg = f"Ошибка: {e}"
            self.loading_label.setText(msg)
            logger.error(f"Tab connection error for {self._ip}: {e}")
            with contextlib.suppress(RuntimeError):
                feedback.notify(
                    f"Ошибка подключения к {self._ip}: {str(e)[:120]}",
                    Level.ERROR,
                    parent=self,
                )
            self._show_reconnect_button(msg)

    # ── Info loading ────────────────────────────────────────────────────────

    def _show_reconnect_button(self, message: str = "Соединение потеряно") -> None:
        if getattr(self, "_reconnect_btn_shown", False):
            return
        self._reconnect_btn_shown = True
        self._clear_sections()
        self.loading_label.show()
        self.loading_label.setText(message)

        btn = PrimaryPushButton("Переподключить", self._info_content)
        btn.setFixedHeight(34)
        btn.clicked.connect(self._do_reconnect)
        self.info_layout.insertWidget(1, btn)
        self._extra_widgets.append(btn)

    def _do_reconnect(self) -> None:
        self._reconnect_btn_shown = False
        self._info_loaded = False
        self._loading = False
        self._clear_sections()
        self.loading_label.setText("Подключение...")
        self.loading_label.show()
        self.start_connecting()

    def _clear_sections(self) -> None:
        for widget in self._group_widgets.values():
            widget.hide()
            self.info_layout.removeWidget(widget)
            widget.deleteLater()
        self._group_widgets.clear()
        for widget in self._extra_widgets:
            widget.hide()
            self.info_layout.removeWidget(widget)
            widget.deleteLater()
        self._extra_widgets.clear()

    async def _connect_db_notified(self, database: str) -> bool:
        ok = await self._session.connect_db()
        if ok:
            logger.info(f"DB connected to {self._ip} (db={database})")
            with contextlib.suppress(RuntimeError):
                feedback.notify(
                    f"БД: {self._ip}: Подключено к {database}",
                    Level.SUCCESS,
                    parent=self,
                )
        else:
            err_short = (self._session.error_message or "").split("\n")[0][:100]
            logger.warning(f"DB connection failed for {self._ip}: {err_short}")
            with contextlib.suppress(RuntimeError):
                feedback.notify(
                    f"БД: {self._ip}: {err_short or 'Ошибка подключения'}",
                    Level.WARNING,
                    parent=self,
                )
        return ok

    def maybe_refresh_in_background(self) -> None:
        """Stale-while-revalidate: панель остаётся со старыми данными,
        пока фоновая пересборка обновляет секции по одной."""
        import time

        from cashcontrol.infrastructure.config_manager import ConfigManager

        if self._loading or not self._info_loaded:
            return
        if not (self._session and self._session.is_connected):
            return
        ttl = ConfigManager().settings.general.info_cache_ttl
        if time.monotonic() - self._last_info_ok < ttl * 0.8:
            return
        logger.debug(f"Background info refresh for {self._ip}")
        self._loading = True
        self._info_loaded = False
        if self._info_task and not self._info_task.done():
            self._info_task.cancel()
        self._info_task = asyncio.create_task(self._collect_info(True))

    async def load_info(self, force: bool = False) -> None:
        if self._loading:
            if not force:
                # Раньше этот выход был молчаливым: ни строки в лог, ни
                # следа в интерфейсе. Из-за этого сбор на кассе просто не
                # начинался, и по журналу было нельзя отличить «сбор идёт»
                # от «сбор не запустился».
                logger.debug(
                    f"load_info({self._ip}): сбор уже идёт, "
                    f"задача={'жива' if self._info_task and not self._info_task.done() else 'нет'} "
                    f"— запуск пропущен"
                )
                return
            # force: перезапуск идущего сбора, а не тихий no-op
            if self._info_task and not self._info_task.done():
                self._info_task.cancel()
            self._loading = False
        if self._info_loaded and not force:
            logger.debug(
                f"load_info({self._ip}): данные уже собраны, запуск пропущен"
            )
            return
        if not self._session or not self._session.is_connected:
            logger.debug(
                f"load_info({self._ip}): нет подключённой сессии, запуск пропущен"
            )
            self._show_reconnect_button()
            return

        self._loading = True
        self.loading_label.show()
        self.loading_label.setText("Сбор информации...")

        if self._info_task and not self._info_task.done():
            self._info_task.cancel()

        logger.debug(
            f"load_info({self._ip}): запуск сбора, force={force}"
        )
        self._info_task = asyncio.create_task(self._collect_info(force))

    async def _collect_info(self, force: bool) -> None:
        import time as _time
        from dataclasses import fields as _dc_fields

        started = _time.monotonic()
        logger.debug(f"Сбор начат для {self._ip}, force={force}")
        try:
            self._show_skeletons()
            self.loading_label.hide()

            collector = get_info_collector()
            snapshot = await collector.collect_all(
                self._session,
                force=force,
                on_section_ready=lambda s: self._section_ready.emit(s),
            )

            filled = sum(
                1
                for f in _dc_fields(snapshot)
                if isinstance(getattr(snapshot, f.name, None), InfoSection)
                and getattr(snapshot, f.name).status
                is CollectionStatus.COMPLETE
            )
            logger.info(
                f"Сбор завершён для {self._ip} за "
                f"{_time.monotonic() - started:.1f} с: заполнено {filled} секций"
            )

            self._os_type = (
                snapshot.os.data.get("os_type", "tinycore") or "tinycore"
            )
            self._keyboard_model = (
                snapshot.keyboard.data.get("keyboard_model") or ""
            )
            self._info_loaded = True
            self._loading = False
            import time

            self._last_info_ok = time.monotonic()
            cash_type = snapshot.cash_type.data.get("cash_type") or ""
            self._cash_type = cash_type
            self.info_loaded.emit(cash_type)

            # Check for known problems after all sections are collected
            try:
                self._check_problems(snapshot)
            except Exception:
                logger.exception(f"Problem check failed for {self._ip}")

        except asyncio.CancelledError:
            logger.debug(f"Info collection cancelled for {self._ip}")
            current = asyncio.current_task()
            if current is None or current is self._info_task:
                self._loading = False
        except Exception as e:
            self.loading_label.show()
            self.loading_label.setText(f"Ошибка: {e}")
            logger.error(f"Failed to load info for {self._ip}: {e}")
            self._loading = False

    def _show_skeletons(self) -> None:
        self._clear_sections()
        for key in _SKELETON_KEYS:
            widget = InfoGroupWidget(_GROUP_TITLES[key], parent=self._info_content)
            widget.show_loading()
            self._group_widgets[key] = widget
            stretch_index = self.info_layout.count() - 1
            self.info_layout.insertWidget(stretch_index, widget)

    def _feature_gate(
        self, section: InfoSection, widget: InfoGroupWidget
    ) -> bool:
        """Показать ли секцию и оставить след в любом случае.

        Раньше на трёх секциях стоял молчаливый ``return``: секция исчезала,
        ничего не сообщая оператору. Хуже всего, что если в группе больше
        ничего не пришло, группа навсегда оставалась со скелетоном — то есть
        на экране висело «идёт сбор», который давно закончен.

        Два случая, и они разные:

        - тип кассы известен и нужной возможности у него нет — это честное
          «не применимо», оно и рисуется;
        - тип кассы не определён (``cash_type`` не собрался, пришёл как
          ``unknown`` или пусто). Тогда утверждать «не применимо» нельзя:
          это фраза о типе, которого у нас нет. Данные показываются — они
          собраны и правдивы, а отсутствие строки ничем не лучше вранья.
        """
        cash_type = self._cash_type
        if not cash_type or cash_type == "unknown":
            return True
        if has_feature(cash_type, section.name):
            return True
        widget.add_note(section.name, f"не поддерживается типом кассы {cash_type}")
        return False

    def _render_section(self, section: InfoSection) -> None:
        group_key = _group_of(section.name)
        if group_key is None:
            return
        widget = self._group_widgets.get(group_key)
        if widget is None:
            return

        if section.status == CollectionStatus.LOADING:
            return
        if section.status == CollectionStatus.TIMEOUT:
            # Причина приходит из секции: сборщик записал в неё, сколько
            # секунд касса не отвечала. Раньше здесь стояло одно «Таймаут» без
            # подсказки, и оператор не знал, что делать дальше.
            widget.add_error(section.name, widget.timeout_note(section.error))
            return
        if section.status == CollectionStatus.ERROR:
            widget.add_error(section.name, section.error or "Ошибка")
            return
        if section.status == CollectionStatus.SKIPPED:
            # Коллектор решил, что секция к этой кассе не относится. Молчание
            # здесь было хуже пустоты: группа оставалась со скелетоном, и
            # отсутствие оборудования выглядело как обрыв связи с кассой —
            # два разных случая с разными действиями оператора.
            widget.add_note(section.name, "К этой кассе не применимо")
            return

        if section.name == "cash_type":
            self._cash_type = section.data.get("cash_type", "unknown")
            items = self._build_cash_type_items(section)
        elif section.name == "os":
            items = self._build_os_items(section)
        elif section.name == "cpu":
            items = self._build_cpu_items(section)
        elif section.name == "customer_display":
            if not self._feature_gate(section, widget):
                return
            items = self._build_display_items(section)
        elif section.name == "scanners":
            items = self._build_scanner_items(section)
        elif section.name == "scales":
            items = self._build_scales_items(section)
        elif section.name == "keyboard":
            if not self._feature_gate(section, widget):
                return
            items = self._build_keyboard_items(section)
        else:
            # Секции со своими подписями строк приходят из реестра: публичные
            # подписаны в core, внутренние — в cashcontrol.internal. В публичной
            # сборке таких секций нет, и они уходят вместе с данными.
            renderer = renderer_for(section.name)
            if renderer is None:
                items = self._build_generic_items(section)
            else:
                if renderer.needs_feature_gate and not self._feature_gate(
                    section, widget
                ):
                    return
                items = renderer.build(section)

        # Пустой список тоже передаём: секция перестала что-либо сообщать,
        # и её прежние строки должны исчезнуть.
        widget.add_items(section.name, items)

    # ── Item builders ───────────────────────────────────────────────────────

    def _build_cash_type_items(self, section: InfoSection) -> list[InfoField]:
        d = section.data
        items: list[InfoField] = []
        ct = d.get("cash_type") or "—"
        sw = d.get("sw_version") or "—"
        items.append(InfoField("cash_type", "Тип кассы", str(ct)))
        items.append(InfoField("sw_version", "Версия ПО", str(sw)))
        return items

    def _build_os_items(self, section: InfoSection) -> list[InfoField]:
        d = section.data
        items: list[InfoField] = []
        os_label = f"{d.get('os_type', '—')} {d.get('os_version', '')}".strip()
        items.append(InfoField("os", "ОС", os_label))
        return items

    def _build_cpu_items(self, section: InfoSection) -> list[InfoField]:
        return [
            InfoField("cpu_model", "Процессор", section.data.get("cpu_model") or "—")
        ]

    def _build_display_items(self, section: InfoSection) -> list[InfoField]:
        d = section.data
        port = d.get("display_port")
        err = d.get("display_error")
        if port:
            return [InfoField("display_port", "Дисплей покупателя", str(port))]
        elif err:
            return [
                InfoField("display_error", "Дисплей покупателя", err)
            ]
        return []

    def _build_scanner_items(self, section: InfoSection) -> list[InfoField]:
        return self._build_device_list_items(
            section, "scanners", "scanner", "scanner_error", "Сканер"
        )

    def _build_scales_items(self, section: InfoSection) -> list[InfoField]:
        return self._build_device_list_items(
            section, "scales", "scale", "scales_error", "Весы"
        )

    def _build_device_list_items(
        self,
        section: InfoSection,
        list_key: str,
        field_prefix: str,
        error_key: str,
        label: str,
    ) -> list[InfoField]:
        devices: list[dict] = section.data.get(list_key, [])
        error = section.data.get(error_key)
        # Поле ищется по порту, а не по индексу. Коллектор добавляет поле
        # только для порта, сопоставленного со справочником USB, тогда как в
        # список устройств попадает каждый порт. Если один порт не сопоставлен,
        # список длиннее полей, и прежний `fields[i]` отдавал устройству
        # чужой alias_key: клик по первому переименовывал второе.
        by_key = {f.key: f for f in section.fields}

        if devices:
            items: list[InfoField] = []
            for i, dev in enumerate(devices):
                name = dev.get("name", "—")
                connected = dev.get("connected")
                state = (" — подключено" if connected
                         else (" — отключено" if connected is False else ""))
                field_label = label if len(devices) == 1 else f"{label} N{i+1}"
                field = by_key.get(f"{field_prefix}_{dev.get('port')}")
                items.append(
                    InfoField(
                        f"{list_key}_{i}",
                        field_label,
                        f"{name}{state}",
                        alias_key=field.alias_key if field is not None else None,
                    )
                )
            return items
        elif error:
            return [InfoField(f"{list_key}_error", label, error)]
        # Пустой список при COMPLETE — это «устройство не настроено», а не
        # «сбор не удался»: разные причины, и разные действия оператора. Раньше
        # обе выглядели одинаково — секция просто не появлялась.
        return []

    def _build_keyboard_items(self, section: InfoSection) -> list[InfoField]:
        d = section.data
        kbd = d.get("keyboard_model")
        err = d.get("keyboard_error")
        if kbd:
            return [InfoField("keyboard_model", "Клавиатура", str(kbd))]
        elif err:
            return [InfoField("keyboard_error", "Клавиатура", err)]
        return []

    def _build_generic_items(self, section: InfoSection) -> list[InfoField]:
        return section.fields if section.fields else []

    def _check_problems(self, snapshot: CashInfoSnapshot) -> None:
        """Перерисовать панель «Проблемы» под текущий снимок."""

        issues = check_problems(snapshot, self._cash_type)

        # Прежняя панель снимается до раннего выхода. Раньше `if not issues:
        # return` стоял выше, и при исчезновении всех проблем старая панель
        # оставалась на экране с прошлым текстом. Сейчас это спасает
        # `_clear_sections()` в начале сбора, но код был написан неверно и
        # полагался на то, что его вызовут именно оттуда.
        old = self._group_widgets.pop("problems", None)
        if old is not None:
            self.info_layout.removeWidget(old)
            old.deleteLater()

        if not issues:
            return

        widget = ProblemListWidget("Проблемы", parent=self._info_content)
        for issue in issues:
            widget.add_problem(
                issue.section, issue.message, issue.severity, issue.check_id
            )
        widget.fix_requested.connect(self._on_fix_requested)
        self._group_widgets["problems"] = widget
        stretch_index = self.info_layout.count() - 1
        self.info_layout.insertWidget(stretch_index, widget)

    # ── Theme refresh ────────────────────────────────────────────────────────

    def _refresh_theme(self) -> None:
        from cashcontrol.gui.theme_helper import color as _tc

        if hasattr(self, "loading_label"):
            self.loading_label.setStyleSheet(
                f"font-size: {font_size('value')}px; color: {_tc('text_secondary')};"
            )
        if hasattr(self, "_vnc_status_label"):
            state = getattr(self._vnc_widget, "state", "idle")
            color_key = {
                "connected": "success",
                "error": "error",
            }.get(state, "text_secondary")
            self._vnc_status_label.setStyleSheet(
                f"color: {_tc(color_key)}; font-size: {font_size('hint')}px;"
            )

    # ── Исправления ──────────────────────────────────────────────────────

    def _on_fix_requested(self, check_id: str) -> None:
        """Оператор нажал «Исправить»: сначала план, потом подтверждение.

        Слот Qt, поэтому модальный диалог здесь и только здесь: ``confirm``
        внутри asyncio-колбэка роняет вложенный Qt-цикл. Сам план считается
        в задаче, а показ диалога возвращается в Qt через ``singleShot``.
        """
        if self._fix_busy:
            feedback.notify(
                "Исправление уже выполняется, дождитесь окончания",
                level=Level.WARNING,
                title=self._ip,
                parent=self,
            )
            return
        self._fix_busy = True
        spawn(self._prepare_fix(check_id))

    async def _prepare_fix(self, check_id: str) -> None:
        from cashcontrol.core.info.fixes import FixPlan, get_fix

        fix = get_fix(check_id)
        if fix is None:
            self._fix_busy = False
            return
        if self._session is None or not self._session.is_connected:
            self._fix_busy = False
            feedback.notify(
                "Нет подключения к кассе: значение не изменено",
                level=Level.ERROR,
                title=fix.title,
                parent=self,
            )
            return

        plan: FixPlan | None = await fix.plan(self._session)
        if plan is None:
            self._fix_busy = False
            feedback.notify(
                f"{fix.title}: исправлять нечего, значение уже корректно "
                "или его не удалось прочитать",
                level=Level.INFO,
                title=self._ip,
                parent=self,
            )
            return

        self._fix_plan = plan
        self._fix_id = check_id
        # Диалог — уже на Qt-стороне, из задачи не показываем.
        QTimer.singleShot(0, self._confirm_fix)

    def _confirm_fix(self) -> None:
        plan = self._fix_plan
        if plan is None:
            self._fix_busy = False
            return
        text = (
            f"Касса {self._ip}\n\n"
            f"будет: {plan.after}\n"
            f"сейчас: {plan.before}\n\n"
            "Значение записывается в базу кассы. Отменить это можно только "
            "повторной записью прежнего значения."
        )
        if plan.effect:
            text += f"\n\n{plan.effect}"
        yes = feedback.confirm(
            plan.title,
            text,
            parent=self,
            destructive=True,
            yes_text="Записать",
        )
        if not yes:
            self._fix_busy = False
            self._fix_plan = None
            return
        spawn(self._apply_fix(self._fix_id, plan.before))

    async def _apply_fix(self, check_id: str, previous: str) -> None:
        from cashcontrol.core.info.fixes import get_fix

        fix = get_fix(check_id)
        try:
            if fix is None or self._session is None:
                return
            result = await fix.apply(self._session)
            if result.applied:
                # Записано — не значит вступило в силу. У DNS значения
                # подхватываются кассой только при загрузке, и без оговорки
                # оператор перезагрузит кассу ночью, а не сейчас.
                message = result.message
                if fix.effect_note:
                    message = f"{message}\n{fix.effect_note}"
                feedback.notify(
                    message,
                    level=Level.SUCCESS,
                    title=fix.title,
                    parent=self,
                )
                # Панели перечитываются принудительно: после записи прежний
                # снимок показывал бы и проблему, и старое значение рядом.
                await self.load_info(force=True)
            else:
                feedback.notify(
                    result.message,
                    level=Level.ERROR,
                    title=fix.title,
                    parent=self,
                )
        except Exception as exc:
            logger.error(f"Исправление {check_id} на {self._ip} сорвалось: {exc}")
            feedback.notify(
                f"исправление не выполнено: {exc}",
                level=Level.ERROR,
                title=self._ip,
                parent=self,
            )
        finally:
            self._fix_busy = False
            self._fix_plan = None

    # ── Public VNC API ───────────────────────────────────────────────────

    def connect_vnc(self) -> None:
        """Connect embedded VNC (called from keyboard shortcut)."""
        self._vnc_widget.connect_vnc()

    def set_vnc_process_sink(self, sink) -> None:
        """Передать внешнему VNC-клиенту приёмник процесса (см. SessionManager)."""
        self._vnc_widget.set_process_sink(sink)

    # ── Drag & drop: отправка файла на кассу ─────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if self._can_accept_drop(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._can_accept_drop(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if not self._can_accept_drop(event):
            return
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return
        paths = [
            url.toLocalFile()
            for url in mime.urls()
            if url.isLocalFile() and url.toLocalFile()
        ]
        if not paths:
            return
        event.acceptProposedAction()
        self.upload_dropped_files(paths)

    @staticmethod
    def _can_accept_drop(event) -> bool:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return False
        return any(url.isLocalFile() for url in mime.urls())

    def _drop_upload_dir(self) -> str:
        """Каталог назначения из настроек, по умолчанию /home/tc/storage."""
        from cashcontrol.infrastructure.config_manager import ConfigManager

        return (
            ConfigManager().settings.builtin.file_manager_start_dir
            or "/home/tc/storage"
        )

    def upload_dropped_files(self, local_paths: list[str]) -> None:
        """Отправить файлы с рабочего стола на кассу, не открывая CashSCP.

        Работа идёт в фоне: окно программы не блокируется, виден прогресс,
        по завершении приходит уведомление.
        """
        session = self._session
        if session is None or not session.is_connected:
            feedback.notify(
                f"{self._ip}: нет подключения, файл не отправлен",
                Level.WARNING,
                parent=self,
            )
            return

        existing = [p for p in local_paths if Path(p).exists()]
        if not existing:
            feedback.notify(
                f"{self._ip}: файлы не найдены", Level.WARNING, parent=self
            )
            return

        dest = self._drop_upload_dir()
        spawn(
            self._upload_to_cash(session, existing, dest),
            label=f"upload:{self._ip}",
        )

    async def _connect_for_transfer(self, ssh) -> object:
        """Отдельное соединение для отправки, с терпимостью к отказам TinyCore.

        SSH-сервер TinyCore не принимает серию новых подключений: следующее
        после успешного может не ответить вовсе. Поэтому ограниченное число
        попыток с паузой. Отказ в пароле не повторяем — пароль здесь уже
        проверен сессией.
        """
        import asyncssh

        from cashcontrol.builtin.file_manager.backends import (
            connect_with_tofu,
            default_known_hosts_path,
        )
        from cashcontrol.core.ssh import SSHConnectionError

        last: Exception | None = None
        for delay in TRANSFER_CONNECT_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                return await connect_with_tofu(
                    host=self._ip,
                    port=ssh.port,
                    username=ssh.login,
                    password=ssh.successful_password,
                    known_hosts=default_known_hosts_path(),
                    timeout=ssh.timeout,
                )
            except (TimeoutError, OSError, asyncssh.Error) as exc:
                last = exc
                logger.warning(
                    "Касса %s не приняла соединение для отправки (%s), повтор",
                    self._ip,
                    type(exc).__name__,
                )
        raise SSHConnectionError(
            f"не удалось подключиться к {self._ip} для отправки: {last}"
        )

    async def _upload_to_cash(self, session, paths: list[str], dest: str) -> None:
        """Отправить файлы на кассу через файловый сервис.

        Соединение здесь отдельное, а не сессионное. На «Тиникоре»
        (TinyCore/dropbear) соединение сессии к этому моменту уже
        исчерпано: сборщики данных открыли под тридцать каналов, после
        чего новые перестают подтверждаться и команда висит до таймаута.
        Плюс встроенный сервис держит постоянный shell-канал и SCP, что на
        таких серверах нельзя смешивать с чужими каналами.

        Транспорт выбирается, потому что SFTP-подсистемы на этих кассах нет.
        """
        import contextlib

        from cashcontrol.builtin.file_manager.backends import build_remote_backend
        from cashcontrol.builtin.file_manager.models import (
            OverwritePolicy,
            TransferOptions,
            TransferResult,
        )
        from cashcontrol.builtin.file_manager.service import RemoteFileService
        ssh = session.ssh
        if getattr(ssh, "_conn", None) is None:
            # Внутри suppress — по той же причине, что и в трёх местах выше:
            # корутина живёт в GUI-потоке (spawn это ensure_future, а не
            # рабочий поток), поэтому полоса доставляется синхронно, и
            # parent=self бросает RuntimeError, если вкладку закрыли через
            # deleteLater() во время выгрузки.
            with contextlib.suppress(RuntimeError):
                feedback.notify(
                    f"{self._ip}: нет подключения к кассе", Level.ERROR, parent=self
                )
            return

        total = len(paths)
        with contextlib.suppress(RuntimeError):
            feedback.notify(
                f"{self._ip}: копирование на кассу — {total} файл(ов) в {dest}",
                Level.INFO,
                parent=self,
            )

        conn = None
        service = None
        try:
            conn = await self._connect_for_transfer(ssh)
            choice = await build_remote_backend(conn, own_connection=True)
            service = RemoteFileService(
                choice.backend, close_backend=choice.close_backend
            )
            result: TransferResult = await service.upload(
                [Path(p) for p in paths],
                dest,
                # Фоновая отправка не может спросить пользователя о конфликте,
                # поэтому переименование вместо перезаписи.
                TransferOptions(overwrite_policy=OverwritePolicy.RENAME),
                on_conflict=None,
            )
        except Exception as exc:
            logger.error("Ошибка отправки на кассу %s: %s", self._ip, exc)
            with contextlib.suppress(RuntimeError):
                feedback.notify(
                    f"{self._ip}: отправка не удалась — {exc}"[:120],
                    Level.ERROR,
                    parent=self,
                )
            return
        finally:
            if service is not None:
                with contextlib.suppress(Exception):
                    await service.close()
            if conn is not None and not conn.is_closed():
                with contextlib.suppress(Exception):
                    conn.close()
                    await conn.wait_closed()

        if result.success:
            audit_log(
                action_type="tool",
                action_name="drop_upload",
                target=self._ip,
                result="success",
                details=f"{result.transferred_files} файл(ов) в {dest}",
            )
            with contextlib.suppress(RuntimeError):
                feedback.notify(
                    f"{self._ip}: отправлено файлов: {result.transferred_files}",
                    Level.SUCCESS,
                    parent=self,
                )
        else:
            with contextlib.suppress(RuntimeError):
                feedback.notify(
                    f"{self._ip}: отправка завершилась с ошибкой",
                    Level.ERROR,
                    parent=self,
                )

    def watch_ping(self, on_ping) -> None:
        """Подписаться на статус пинга, чтобы поднимать VNC после обрыва.

        SessionManager шлёт ping_status_changed для всех хостов, поэтому
        отфильтровываем по своему адресу.
        """

        def _handler(ip: str, status: str) -> None:
            if ip == self._ip:
                self._on_ping_status(status)

        on_ping.connect(_handler)

    def _on_ping_status(self, status: str) -> None:
        """Обрыв и восстановление связи с кассой.

        Раньше автопереподключения не было вовсе: SessionManager только
        обновлял точку на вкладке. Если в момент обрыва был открыт VNC, он
        оставался с мёртвой картинкой, а поднять его заново можно было
        только закрытием вкладки или сменой IP.
        """
        reachable = status in ("ok", "slow")

        if not reachable:
            if not self._ssh_was_down and self._vnc_was_open:
                logger.info("[VNC] SSH недоступен, VNC будет восстановлен")
            self._ssh_was_down = True
            return

        if not self._ssh_was_down:
            return
        self._ssh_was_down = False

        if not self._vnc_was_open:
            return
        if self._session is not None and self._session.is_connected:
            logger.info("[VNC] SSH восстановлен, переподключаю VNC")
            self._vnc_resume = True
            self._vnc_widget.connect_vnc()
            return

        logger.info("[VNC] SSH восстановлен, переподключаю сессию и VNC")
        self._vnc_resume = True
        self.start_connecting()

    def disconnect_vnc(self) -> None:
        """Явное отключение: сбрасывает намерение, автовосстановления не будет."""
        self._vnc_was_open = False
        self._vnc_resume = False
        self._vnc_widget.disconnect_vnc()

    def open_vnc_client(self, fullscreen: bool) -> None:
        """Open VNC via the available client (external exe or built-in viewer)."""
        logger.info("[VNC] open client for %s", self._ip)
        self._vnc_widget.open_client(fullscreen)

    def open_vnc_external(self) -> None:
        logger.info(f"[VNC] open_vnc_external called for {self._ip}")
        from cashcontrol.infrastructure.config_manager import ConfigManager
        builtin = ConfigManager().settings.builtin
        self._vnc_widget.open_client(
            fullscreen=builtin.vnc_start_mode == "fullscreen"
        )

    # ── IP editing ──────────────────────────────────────────────────────────

    def start_ip_edit(self) -> None:
        if getattr(self, "_ip_edit_widget", None):
            return

        container = QWidget(self)
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(8, 6, 8, 6)
        c_layout.setSpacing(6)

        lbl = BodyLabel("Новый IP:", container)
        c_layout.addWidget(lbl)

        edit = LineEdit(container)
        edit.setText(self._ip)
        install_comma_to_dot(edit)
        edit.selectAll()
        edit.setFixedHeight(32)
        c_layout.addWidget(edit, stretch=1)

        btn_ok = PrimaryPushButton("Подключить", container)
        btn_ok.setFixedHeight(32)
        c_layout.addWidget(btn_ok)

        btn_cancel = ToolButton(FluentIcon.CLOSE, container)
        btn_cancel.setFixedSize(32, 32)
        btn_cancel.setToolTip("Отмена")
        c_layout.addWidget(btn_cancel)

        self.info_layout.insertWidget(0, container)
        self._ip_edit_widget = container
        edit.setFocus()

        def _apply():
            new_ip = edit.text().strip()
            _close()
            if new_ip and new_ip != self._ip:
                p = self.parent()
                while p:
                    if hasattr(p, "change_tab_ip"):
                        p.change_tab_ip(self._ip, new_ip)
                        break
                    p = p.parent()

        def _close():
            if getattr(self, "_ip_edit_widget", None):
                self.info_layout.removeWidget(self._ip_edit_widget)
                self._ip_edit_widget.deleteLater()
                self._ip_edit_widget = None

        btn_ok.clicked.connect(_apply)
        btn_cancel.clicked.connect(_close)
        edit.returnPressed.connect(_apply)

    async def reconnect_to(self, new_ip: str) -> None:
        # Кэш снимка сбрасывается ДО переподключения. Раньше «Обновить»
        # переподключался по-настоящему, а затем звал load_info() без force и
        # получал из кэша тот же снимок, что и секунду назад: в логе —
        # «Сбор завершён за 0.0 с», ни одной команды на кассе. Оператор видел
        # успешное переподключение и заключал, что данные перечитаны, а они
        # не перечитывались. Из-за этого же расходились панели: значение на
        # кассе меняли, а приложение продолжало показывать прежнее, и
        # проверка problems молчала.
        #
        # Сам кэш не лишний: он по-прежнему отдаёт снимок повторным
        # load_info без переподключения (переключение вкладок, перерисовка).
        # Сбрасывается только явное переподключение — это и есть заявка
        # оператора «прочитай заново».
        with contextlib.suppress(Exception):
            get_info_collector().clear_cache(new_ip)

        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._connect_task
            self._connect_task = None
        if self._info_task and not self._info_task.done():
            self._info_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._info_task
            self._info_task = None

        # VNC отключаем ДО разрыва SSH, иначе воркер зависает на мёртвом сокете
        vnc_resume = False
        with contextlib.suppress(Exception):
            if getattr(self._vnc_widget, "state", "idle") == "connected":
                vnc_resume = True
                self._vnc_widget.disconnect_vnc()

        if self._session:
            # ожидаемо: abort() может упасть, если соединения уже нет
            with contextlib.suppress(Exception):
                await self._session.abort()
            self._session = None

        self._ip = new_ip
        self._vnc_widget._ip = new_ip
        self._vnc_resume = vnc_resume
        # Намерение сохраняется: если после смены IP связь снова оборвётся,
        # автовосстановление должно знать, что VNC был открыт.
        self._vnc_was_open = vnc_resume or self._vnc_was_open
        self._ssh_was_down = False
        self._info_loaded = False
        self._loading = False
        self._clear_sections()
        self.loading_label.setText("Подключение...")
        self.loading_label.show()
        self.start_connecting()

    def cleanup(self) -> None:
        if getattr(self, "_theme_conn_signal", None) is not None:
            with contextlib.suppress(Exception):
                self._theme_conn_signal.disconnect(self._refresh_theme)
            self._theme_conn_signal = None
        self._vnc_widget.cleanup()

        # Поднимается и при закрытии вкладки (deleteLater не эмитит closeEvent),
        # поэтому останавливаем фоновую работу и рвём SSH/БД, иначе закрытые
        # вкладки держат соединение с кассой и следующее подключение падает.
        for attr in ("_connect_task", "_info_task"):
            task = getattr(self, attr, None)
            if task and not task.done():
                task.cancel()
        if self._session is not None:
            db_task = getattr(self._session, "db_connect_task", None)
            if db_task and not db_task.done():
                db_task.cancel()
            with contextlib.suppress(Exception):
                self._session.ssh.abort()
            self._session = None

    @override
    def closeEvent(self, event) -> None:
        if self._info_task and not self._info_task.done():
            self._info_task.cancel()
        self.cleanup()
        super().closeEvent(event)
