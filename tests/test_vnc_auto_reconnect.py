"""Встроенный VNC поднимается заново после обрыва и восстановления SSH.

Регрессия, о которой сообщали коллеги: касса уходит в перезагрузку, SSH и
VNC отваливаются. После восстановления связи VNC на той же вкладке сам не
поднимался, приходилось закрывать и открывать вкладку либо менять IP.

Причина была не в «иногда», а в отсутствии логики: флаг ``_vnc_resume``
выставлялся только в ``reconnect_to()``, то есть исключительно при смене IP.
Автопереподключения SSH по восстановлению связи не было вовсе, SessionManager
только обновлял точку на вкладке.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from PySide6.QtCore import QObject, Signal

from cashcontrol.gui.cash_session_widget import CashSessionWidget
from cashcontrol.gui.session_manager import SessionManager


class _Ping(QObject):
    """Имитация сигнала SessionManager.ping_status_changed."""

    ping_status_changed = Signal(str, str)


class _FakeVnc:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.process_sink = None

    def connect_vnc(self) -> None:
        self.connect_calls += 1

    def disconnect_vnc(self) -> None:
        self.disconnect_calls += 1

    def set_process_sink(self, sink) -> None:
        self.process_sink = sink

    def set_session(self, session) -> None:
        pass


class _FakeSession:
    def __init__(self, connected: bool = True) -> None:
        self.is_connected = connected


@pytest.fixture
def widget(qtbot):
    w = CashSessionWidget.__new__(CashSessionWidget)  # без тяжёлого _init_ui
    w._ip = "10.0.0.1"
    w._vnc_widget = _FakeVnc()
    w._session = _FakeSession(connected=True)
    w._vnc_was_open = True
    w._ssh_was_down = False
    w._vnc_resume = False
    w.started = 0
    # Кнопки и метки, к которым обращается _on_vnc_state_changed
    w._btn_vnc_connect = _DummyWidget()
    w._btn_vnc_disconnect = _DummyWidget()
    w._btn_vnc_fullscreen = _DummyWidget()
    w._vnc_status_label = _DummyWidget()

    def _start_connecting():
        w.started += 1
        return None

    w.start_connecting = _start_connecting
    yield w


class _DummyWidget:
    """Заглушка виджета Qt: нужны только вызовы set*."""

    def setVisible(self, *_a):
        pass

    def setEnabled(self, *_a):
        pass

    def setText(self, *_a):
        pass

    def setStyleSheet(self, *_a):
        pass


def _fire(signal_owner: QObject, ip: str, status: str) -> None:
    signal_owner.ping_status_changed.emit(ip, status)


# ── главный сценарий ───────────────────────────────────────────────────

def test_vnc_reconnects_when_ssh_comes_back(qtbot, widget):
    """Обрыв, затем восстановление — VNC поднимается сам."""
    ping = _Ping()
    widget.watch_ping(ping.ping_status_changed)

    before = widget._vnc_widget.connect_calls

    _fire(ping, "10.0.0.1", "timeout")      # касса ушла в перезагрузку
    _fire(ping, "10.0.0.1", "ok")           # связь вернулась

    assert widget._vnc_widget.connect_calls == before + 1, (
        "VNC не переподключился после восстановления SSH"
    )


def test_down_up_cycle_repeats(qtbot, widget):
    """Несколько перезагрузок подряд — VNC поднимается каждый раз."""
    ping = _Ping()
    widget.watch_ping(ping.ping_status_changed)
    before = widget._vnc_widget.connect_calls

    for _ in range(3):
        _fire(ping, "10.0.0.1", "timeout")
        _fire(ping, "10.0.0.1", "ok")

    assert widget._vnc_widget.connect_calls == before + 3


def test_slow_ping_counts_as_reachable(qtbot, widget):
    """"slow" — это связь есть, VNC трогать не надо."""
    ping = _Ping()
    widget.watch_ping(ping.ping_status_changed)
    before = widget._vnc_widget.connect_calls

    _fire(ping, "10.0.0.1", "slow")

    assert widget._vnc_widget.connect_calls == before


def test_full_session_reconnect_when_ssh_dead(qtbot, widget):
    """Если SSH сам не восстановился, нужен полный переподключающий сеанс."""
    widget._session = _FakeSession(connected=False)
    ping = _Ping()
    widget.watch_ping(ping.ping_status_changed)

    _fire(ping, "10.0.0.1", "timeout")
    _fire(ping, "10.0.0.1", "ok")

    assert widget.started == 1, "сессия SSH не переподключена"
    assert widget._vnc_resume is True, "VNC не помечен для возобновления"


# ── что автопереподключение НЕ должно делать ───────────────────────────

def test_no_reconnect_if_vnc_was_closed(qtbot, widget):
    """Пользователь отключил VNC сам — поднимать её нельзя."""
    widget._vnc_was_open = False
    ping = _Ping()
    widget.watch_ping(ping.ping_status_changed)
    before = widget._vnc_widget.connect_calls

    _fire(ping, "10.0.0.1", "timeout")
    _fire(ping, "10.0.0.1", "ok")

    assert widget._vnc_widget.connect_calls == before
    assert widget.started == 0


def test_no_reconnect_without_a_drop(qtbot, widget):
    """Пинг стабильно «ok» — никаких действий."""
    ping = _Ping()
    widget.watch_ping(ping.ping_status_changed)
    before = widget._vnc_widget.connect_calls

    for _ in range(5):
        _fire(ping, "10.0.0.1", "ok")

    assert widget._vnc_widget.connect_calls == before
    assert widget.started == 0


def test_single_ok_after_ok_is_noop(qtbot, widget):
    """Второй разрыв и восстановление обрабатываются, лишних нет."""
    ping = _Ping()
    widget.watch_ping(ping.ping_status_changed)
    before = widget._vnc_widget.connect_calls

    _fire(ping, "10.0.0.1", "timeout")
    _fire(ping, "10.0.0.1", "ok")
    _fire(ping, "10.0.0.1", "ok")  # тот же "ok" повторно
    _fire(ping, "10.0.0.1", "ok")

    assert widget._vnc_widget.connect_calls == before + 1


def test_other_host_status_ignored(qtbot, widget):
    """Сигнал общий для всех хостов, чужой статус не должен трогать вкладку."""
    ping = _Ping()
    widget.watch_ping(ping.ping_status_changed)
    before = widget._vnc_widget.connect_calls

    _fire(ping, "10.0.0.99", "timeout")
    _fire(ping, "10.0.0.99", "ok")

    assert widget._vnc_widget.connect_calls == before


# ── явное отключение сбрасывает намерение ──────────────────────────────

def test_explicit_disconnect_clears_intent(qtbot, widget):
    widget.disconnect_vnc()

    assert widget._vnc_was_open is False
    assert widget._vnc_resume is False
    assert widget._vnc_widget.disconnect_calls == 1


def test_state_connected_marks_intent(qtbot, widget):
    """Успешное подключение VNC запоминает намерение."""
    widget._vnc_was_open = False
    widget._on_vnc_state_changed("connected", "")
    assert widget._vnc_was_open is True


def test_state_idle_clears_intent(qtbot, widget):
    widget._vnc_was_open = True
    widget._on_vnc_state_changed("idle", "")
    assert widget._vnc_was_open is False


def test_disconnect_button_uses_widget_method(qtbot):
    """Кнопка «Отключить» должна звать сброс намерения, а не напрямую виджет."""
    src = textwrap.dedent(inspect.getsource(CashSessionWidget._init_ui))
    assert "self._btn_vnc_disconnect.clicked.connect(self.disconnect_vnc)" in src, (
        "кнопка отключения VNC должна сбрасывать намерение автовосстановления"
    )
    assert "clicked.connect(self._vnc_widget.disconnect_vnc)" not in src


# ── регистрация в менеджере ────────────────────────────────────────────

def test_add_session_subscribes_to_ping(qtbot):
    manager = SessionManager()
    seen: list[object] = []

    class _FakeWidget:
        def set_vnc_process_sink(self, sink) -> None:
            pass

        def watch_ping(self, signal) -> None:
            seen.append(signal)

    manager.add_session("10.0.0.1", _FakeWidget())

    assert seen and seen[0] is manager.ping_status_changed, (
        "вкладка не подписана на статус пинга: автопереподключение VNC не сработает"
    )


# ── структурная защита от возврата регрессии ──────────────────────────

def test_vnc_resume_still_used_for_ip_change():
    """Смена IP по-прежнему возобновляет VNC тем же флагом."""
    src = textwrap.dedent(inspect.getsource(CashSessionWidget.reconnect_to))
    assert "vnc_resume = True" in src
    assert "_vnc_was_open" in src, (
        "reconnect_to должен обновлять и намерение, иначе после смены IP "
        "автовосстановление не сработает"
    )


def test_ping_handler_exists():
    assert callable(CashSessionWidget._on_ping_status)
    tree = ast.parse(textwrap.dedent(inspect.getsource(CashSessionWidget._on_ping_status)))
    awaits = [n for n in ast.walk(tree) if isinstance(n, ast.Await)]
    assert not awaits, "обработчик статуса пинга не должен быть async"
