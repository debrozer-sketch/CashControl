from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, override

from PySide6.QtCore import Qt, Signal
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

from cashcontrol.core.info import InfoCollector, ProblemChecker
from cashcontrol.core.info.info_manager import CollectionStatus, InfoField
from cashcontrol.core.session import CashSession
from cashcontrol.gui.notification_manager import get_notification_manager
from cashcontrol.gui.vnc_preview import VncPreviewWidget
from cashcontrol.gui.widgets.info_section_widget import InfoGroupWidget
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.info.info_manager import CashInfoSnapshot, InfoSection

logger = get_logger()

# Mapping: section name → group key
_SECTION_TO_GROUP: dict[str, str] = {
    "cash_type": "system",
    "os": "system",
    "cpu": "system",
    "software": "system",
    "fiscal_printer": "equipment",
    "customer_display": "equipment",
    "scanners": "equipment",
    "scales": "equipment",
    "keyboard": "equipment",
    "bank_terminal": "equipment",
    "dns": "other",
    "loymax": "other",
    "qrid": "other",
}

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
        self._loading = False
        self._connect_task: asyncio.Task | None = None
        self._info_task: asyncio.Task | None = None
        self._group_widgets: dict[str, InfoGroupWidget] = {}
        self._extra_widgets: list[QWidget] = []
        self._os_type: str = "tinycore"
        self._cash_type: str = "unknown"
        self._ip_edit_widget: QWidget | None = None
        self._reconnect_btn_shown: bool = False
        self._init_ui()
        self._section_ready.connect(self._render_section)
        from cashcontrol.gui.theme_engine import ThemeEngine

        ThemeEngine.instance().theme_changed.connect(self._refresh_theme)
        self._connect_task = None

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def session(self) -> CashSession | None:
        return self._session

    @property
    def os_type(self) -> str:
        return self._os_type

    # ── UI ──────────────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(0)

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
        self._btn_vnc_disconnect.clicked.connect(self._vnc_widget.disconnect_vnc)
        self._btn_vnc_disconnect.hide()
        bar_layout.addWidget(self._btn_vnc_disconnect)

        self._btn_vnc_fullscreen = PushButton("Полный экран", vnc_bar, FluentIcon.FULL_SCREEN)
        self._btn_vnc_fullscreen.clicked.connect(self._vnc_widget.open_fullscreen)
        bar_layout.addWidget(self._btn_vnc_fullscreen)

        self._vnc_status_label = QLabel("", vnc_bar)
        from cashcontrol.gui.theme_helper import color as _tc

        self._vnc_status_label.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: 11px;"
        )
        bar_layout.addWidget(self._vnc_status_label)

        bar_layout.addStretch()
        root.addWidget(vnc_bar)

    def _on_vnc_state_changed(self, state: str, message: str) -> None:
        from cashcontrol.gui.theme_helper import color as _tc

        if state == "idle":
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
            self._btn_vnc_connect.setVisible(False)
            self._btn_vnc_disconnect.setVisible(True)
            self._btn_vnc_fullscreen.setEnabled(True)
            self._vnc_status_label.setText("подключено")
            self._vnc_status_label.setStyleSheet(
                f"color: {_tc('success')}; font-size: 11px;"
            )
        elif state == "error":
            self._btn_vnc_connect.setVisible(True)
            self._btn_vnc_connect.setEnabled(True)
            self._btn_vnc_disconnect.setVisible(False)
            self._btn_vnc_fullscreen.setEnabled(True)
            self._vnc_status_label.setText("ошибка")
            self._vnc_status_label.setStyleSheet(
                f"color: {_tc('error')}; font-size: 11px;"
            )

    # ── Info panel ──────────────────────────────────────────────────────────

    def _build_info_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setFrameShape(QFrame.Shape.StyledPanel)

        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._info_content = QWidget()
        self.info_layout = QVBoxLayout(self._info_content)
        self.info_layout.setContentsMargins(8, 8, 8, 8)
        self.info_layout.setSpacing(12)

        self.loading_label = QLabel("Подключение...")
        from cashcontrol.gui.theme_helper import color as _tc

        self.loading_label.setStyleSheet(
            f"font-size: 14px; color: {_tc('text_secondary')};"
        )
        self.info_layout.addWidget(self.loading_label)
        self.info_layout.addStretch()

        scroll.setWidget(self._info_content)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
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
            try:
                get_history_manager().add(self._ip, HistoryEntry(
                    timestamp=_dt.now(), action_name="Подключение",
                    result="success", details=f"SSH {self._ip}", ip=self._ip))
            except Exception:
                pass
            self._vnc_widget.set_session(self._session)

            if getattr(self, "_vnc_resume", False):
                self._vnc_resume = False
                self.connect_vnc()

            from cashcontrol.core.info.collectors.cash_type import (
                CashTypeCollector,
            )

            type_data = await CashTypeCollector().collect(self._session)
            cash_type = type_data.get("cash_type", "unknown")

            if cash_type == "sco3":
                self._session.setup_db(database="sco_v3")
                try:
                    await self._session.db.connect()
                    self._session.db_connected = True
                    logger.info(f"DB connected to {self._ip} (db=sco_v3)")
                    try:
                        get_notification_manager().notify(
                            f"БД: {self._ip}: Подключено к sco_v3",
                            level="success",
                        )
                    except RuntimeError:
                        pass
                except Exception as db_err:
                    logger.warning(
                        f"DB connection failed for {self._ip}: {db_err}"
                    )
                    err_short = str(db_err).split("\n")[0][:100]
                    with contextlib.suppress(RuntimeError):
                        get_notification_manager().notify(
                            f"БД: {self._ip}: {err_short or 'Ошибка подключения'}",
                            level="warning",
                        )

            await self.load_info()

        except asyncio.CancelledError:
            logger.debug(f"Connect task cancelled for {self._ip}")
        except Exception as e:
            self.connection_state_changed.emit(self._ip, "timeout")
            msg = f"Ошибка: {e}"
            self.loading_label.setText(msg)
            logger.error(f"Tab connection error for {self._ip}: {e}")
            try:
                get_notification_manager().notify(
                    f"Ошибка подключения к {self._ip}: {str(e)[:120]}",
                    level="error",
                )
            except RuntimeError:
                pass
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

    async def load_info(self, force: bool = False) -> None:
        if self._loading:
            return
        if self._info_loaded and not force:
            return
        if not self._session or not self._session.is_connected:
            self._show_reconnect_button()
            return

        self._loading = True
        self.loading_label.show()
        self.loading_label.setText("Сбор информации...")

        if self._info_task and not self._info_task.done():
            self._info_task.cancel()

        self._info_task = asyncio.create_task(self._collect_info(force))

    async def _collect_info(self, force: bool) -> None:
        try:
            self._show_skeletons()
            self.loading_label.hide()

            collector = InfoCollector()
            snapshot = await collector.collect_all(
                self._session,
                force=force,
                on_section_ready=lambda s: self._section_ready.emit(s),
            )

            self._os_type = (
                snapshot.os.data.get("os_type", "tinycore") or "tinycore"
            )
            self._keyboard_model = (
                snapshot.keyboard.data.get("keyboard_model") or ""
            )
            self._info_loaded = True
            self._loading = False
            cash_type = snapshot.cash_type.data.get("cash_type") or ""
            self.info_loaded.emit(cash_type)

            # Check for known problems after all sections are collected
            try:
                self._check_problems(snapshot)
            except Exception:
                logger.exception(f"Problem check failed for {self._ip}")

        except asyncio.CancelledError:
            logger.debug(f"Info collection cancelled for {self._ip}")
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

    def _render_section(self, section: InfoSection) -> None:
        group_key = _SECTION_TO_GROUP.get(section.name)
        if group_key is None:
            return
        widget = self._group_widgets.get(group_key)
        if widget is None:
            return

        if section.status == CollectionStatus.LOADING:
            return
        if section.status == CollectionStatus.TIMEOUT:
            widget.show_timeout()
            return
        if section.status == CollectionStatus.ERROR:
            widget.show_error(section.error)
            return
        if section.status == CollectionStatus.SKIPPED:
            return

        if section.name == "cash_type":
            self._cash_type = section.data.get("cash_type", "unknown")
            items = self._build_cash_type_items(section)
        elif section.name == "os":
            items = self._build_os_items(section)
        elif section.name == "cpu":
            items = self._build_cpu_items(section)
        elif section.name == "software":
            items = self._build_software_items(section)
        elif section.name == "fiscal_printer":
            items = self._build_fr_items(section)
        elif section.name == "customer_display":
            if self._cash_type != "pos":
                return
            items = self._build_display_items(section)
        elif section.name == "scanners":
            items = self._build_scanner_items(section)
        elif section.name == "scales":
            items = self._build_scales_items(section)
        elif section.name == "keyboard":
            if self._cash_type != "pos":
                return
            items = self._build_keyboard_items(section)
        elif section.name == "bank_terminal":
            items = self._build_bank_items(section)
        elif section.name == "dns":
            items = self._build_dns_items(section)
        elif section.name == "loymax":
            items = self._build_loymax_items(section)
        elif section.name == "qrid":
            if self._cash_type != "pos":
                return
            items = self._build_qrid_items(section)
        else:
            items = self._build_generic_items(section)

        if items:
            widget.add_items(items)

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

    def _build_software_items(self, section: InfoSection) -> list[InfoField]:
        return []

    def _build_fr_items(self, section: InfoSection) -> list[InfoField]:
        d = section.data
        port = d.get("fr_port")
        err = d.get("fr_error")
        if port:
            return [InfoField("fr_port", "ФР подключён", str(port))]
        elif err:
            return [InfoField("fr_error", "ФР", err)]
        return []

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
            section, "scanners", "scanner_error", "Сканер"
        )

    def _build_scales_items(self, section: InfoSection) -> list[InfoField]:
        return self._build_device_list_items(
            section, "scales", "scales_error", "Весы"
        )

    def _build_device_list_items(
        self,
        section: InfoSection,
        list_key: str,
        error_key: str,
        label: str,
    ) -> list[InfoField]:
        devices: list[dict] = section.data.get(list_key, [])
        error = section.data.get(error_key)
        fields = section.fields

        if devices:
            items: list[InfoField] = []
            for i, dev in enumerate(devices):
                name = dev.get("name", "—")
                connected = dev.get("connected")
                state = (" — подключено" if connected
                         else (" — отключено" if connected is False else ""))
                field_label = label if len(devices) == 1 else f"{label} N{i+1}"
                alias_key = fields[i].alias_key if i < len(fields) else None
                items.append(
                    InfoField(
                        f"{list_key}_{i}",
                        field_label,
                        f"{name}{state}",
                        alias_key=alias_key,
                    )
                )
            return items
        elif error:
            return [InfoField(f"{list_key}_error", label, error)]
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

    def _build_bank_items(self, section: InfoSection) -> list[InfoField]:
        d = section.data
        port = d.get("bank_port")
        err = d.get("bank_error")
        if port:
            usb_note = " (EnableUSB)" if d.get("bank_usb_mode") == "1" else ""
            return [InfoField("bank_port", "Банк", f"{port}{usb_note}")]
        elif err:
            return [InfoField("bank_error", "Банк", err)]
        return []

    def _build_dns_items(self, section: InfoSection) -> list[InfoField]:
        servers: list = section.data.get("dns_servers") or []
        if servers:
            return [
                InfoField("dns_servers", "DNS", ", ".join(str(s) for s in servers))
            ]
        return []

    def _build_loymax_items(self, section: InfoSection) -> list[InfoField]:
        d = section.data
        login = d.get("loymax_login")
        err = d.get("loymax_error")
        if login:
            return [InfoField("loymax_login", "Loymax", str(login))]
        elif err:
            return [InfoField("loymax_error", "Loymax", err)]
        return []

    def _build_qrid_items(self, section: InfoSection) -> list[InfoField]:
        d = section.data
        qrid = d.get("qrid")
        err = d.get("qrid_error")
        if qrid:
            return [InfoField("qrid", "QRID", str(qrid))]
        elif err:
            return [InfoField("qrid_error", "QRID", err)]
        return []

    def _build_generic_items(self, section: InfoSection) -> list[InfoField]:
        return section.fields if section.fields else []

    def _check_problems(self, snapshot: CashInfoSnapshot) -> None:
        """Run problem checker and show «Проблемы» group if issues found."""

        checker = ProblemChecker()
        issues = checker.check(snapshot, self._cash_type)
        if not issues:
            return

        # Remove existing problems widget if any
        old = self._group_widgets.pop("problems", None)
        if old:
            self.info_layout.removeWidget(old)
            old.deleteLater()

        widget = InfoGroupWidget("Проблемы", parent=self._info_content)
        fields: list[InfoField] = []
        for issue in issues:
            fields.append(
                InfoField(
                    f"problem_{issue.section}",
                    issue.section,
                    issue.message,
                )
            )
        widget.add_items(fields)
        self._group_widgets["problems"] = widget
        stretch_index = self.info_layout.count() - 1
        self.info_layout.insertWidget(stretch_index, widget)

    # ── Theme refresh ────────────────────────────────────────────────────────

    def _refresh_theme(self) -> None:
        from cashcontrol.gui.theme_helper import color as _tc

        if hasattr(self, "loading_label"):
            self.loading_label.setStyleSheet(
                f"font-size: 14px; color: {_tc('text_secondary')};"
            )
        if hasattr(self, "_vnc_status_label"):
            self._vnc_status_label.setStyleSheet(
                f"color: {_tc('text_secondary')}; font-size: 11px;"
            )

    # ── Public VNC API ───────────────────────────────────────────────────

    def connect_vnc(self) -> None:
        """Connect embedded VNC (called from keyboard shortcut)."""
        self._vnc_widget.connect_vnc()

    def open_vnc_external(self) -> None:
        logger.info(f"[VNC] open_vnc_external called for {self._ip}")
        self._vnc_widget.open_fullscreen()

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
        try:
            if self._vnc_widget.state() == "connected":
                vnc_resume = True
                self._vnc_widget.disconnect_vnc()
        except Exception:
            pass

        if self._session:
            try:
                conn = getattr(self._session.ssh, "_conn", None)
                if conn and not conn.is_closed():
                    conn.abort()
                self._session.ssh._conn = None
                self._session._is_connected = False
            except Exception:
                # ожидаемо: abort() может упасть, если соединения уже нет
                pass
            self._session = None

        self._ip = new_ip
        self._vnc_widget._ip = new_ip
        self._vnc_resume = vnc_resume
        self._info_loaded = False
        self._loading = False
        self._clear_sections()
        self.loading_label.setText("Подключение...")
        self.loading_label.show()
        self.start_connecting()

    def cleanup(self) -> None:
        self._vnc_widget.cleanup()

    @override
    def closeEvent(self, event) -> None:
        if self._info_task and not self._info_task.done():
            self._info_task.cancel()
        self.cleanup()
        super().closeEvent(event)
