"""Учёт внешнего VNC-клиента: запуск, регистрация, закрытие вместе с вкладкой.

Регрессия: ``SessionManager._vnc_procs`` был объявлен, но не наполнялся нигде
в проекте. Из-за этого ``kill_vnc`` и ``kill_all_vnc`` работали с пустым
словарём, а процессы внешнего просмотрщика переживали закрытие вкладки и
выход из программы.
"""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cashcontrol.gui.session_manager import SessionManager


def _fake_proc() -> subprocess.Popen:
    """Живой процесс-заглушка: можно дождаться его завершения."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def mgr(qtbot):
    manager = SessionManager()
    yield manager
    manager.kill_all_vnc()


def test_register_then_kill_terminates_process(mgr):
    proc = _fake_proc()
    assert proc.poll() is None

    mgr.register_vnc("10.0.0.1", proc)
    assert mgr._vnc_procs.get("10.0.0.1") is proc

    mgr.kill_vnc("10.0.0.1")

    assert "10.0.0.1" not in mgr._vnc_procs
    deadline = time.monotonic() + 5
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert proc.poll() is not None, "процесс не завершён после kill_vnc"


def test_kill_all_vnc_terminates_every_registered_process(mgr):
    procs = {ip: _fake_proc() for ip in ("10.0.0.1", "10.0.0.2", "10.0.0.3")}
    for ip, proc in procs.items():
        mgr.register_vnc(ip, proc)

    mgr.kill_all_vnc()

    assert mgr._vnc_procs == {}
    deadline = time.monotonic() + 5
    while any(p.poll() is None for p in procs.values()) and time.monotonic() < deadline:
        time.sleep(0.05)
    for ip, proc in procs.items():
        assert proc.poll() is not None, f"{ip}: процесс пережил kill_all_vnc"


def test_kill_vnc_on_unknown_ip_is_noop(mgr):
    mgr.kill_vnc("10.0.0.99")
    assert mgr._vnc_procs == {}


def test_register_same_ip_replaces_previous_process(mgr):
    first = _fake_proc()
    second = _fake_proc()
    try:
        mgr.register_vnc("10.0.0.1", first)
        mgr.register_vnc("10.0.0.1", second)

        assert mgr._vnc_procs["10.0.0.1"] is second
        deadline = time.monotonic() + 5
        while first.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert first.poll() is not None, "старый клиент не закрыт при повторном запуске"
    finally:
        for p in (first, second):
            if p.poll() is None:
                p.kill()


def test_move_vnc_follows_ip_change(mgr):
    proc = _fake_proc()
    try:
        mgr.register_vnc("10.0.0.1", proc)
        mgr.move_vnc("10.0.0.1", "10.0.0.9")

        assert "10.0.0.1" not in mgr._vnc_procs
        assert mgr._vnc_procs.get("10.0.0.9") is proc

        # после смены IP закрытие вкладки по-прежнему находит процесс
        mgr.kill_vnc("10.0.0.9")
        assert "10.0.0.9" not in mgr._vnc_procs
    finally:
        if proc.poll() is None:
            proc.kill()


def test_vnc_widget_reports_launched_process_to_sink(qtbot, monkeypatch):
    """Виджет обязан отдать процесс приёмнику при РЕАЛЬНОМ запуске клиента."""
    from pathlib import Path

    from cashcontrol.builtin.vnc import vnc_preview
    from cashcontrol.builtin.vnc.vnc_preview import VncPreviewWidget

    widget = VncPreviewWidget("192.0.2.1")
    qtbot.addWidget(widget)

    # Клиент запускается только после проверки сервера на кассе, поэтому
    # сессия нужна настоящая: порт слушает, значит x11vnc не перезапускается.
    class _OkResult:
        exit_code = 0
        stdout = ""
        stderr = ""
        success = True

    class _Ssh:
        async def execute(self, command, **_kw):
            return _OkResult()

    class _Session:
        is_connected = True
        ssh = _Ssh()

    widget._session = _Session()
    monkeypatch.setattr(vnc_preview, "_VNC_START_DELAY", 0.0)

    class _ConnectedVnc:
        is_connected = True

    widget._vnc = _ConnectedVnc()

    launched: list[list[str]] = []
    fake = _fake_proc()
    monkeypatch.setattr(
        vnc_preview.subprocess,
        "Popen",
        lambda args, *a, **kw: (launched.append(list(args)), fake)[1],
    )
    monkeypatch.setattr(widget, "_audit", lambda *a, **kw: None)

    received: list[tuple[str, subprocess.Popen]] = []
    widget.set_process_sink(lambda ip, proc: received.append((ip, proc)))

    try:
        asyncio.run(widget._open_fullscreen_async(Path("fake_viewer.exe")))

        assert launched, "внешний клиент не запускался"
        assert received == [("192.0.2.1", fake)], (
            "процесс внешнего VNC-клиента не дошёл до SessionManager: "
            "он снова будет переживать закрытие вкладки"
        )
    finally:
        fake.kill()


def test_add_session_wires_the_sink(qtbot):
    """SessionManager обязан подключить приёмник при регистрации вкладки."""
    manager = SessionManager()
    wired: list[object] = []

    class _FakeWidget:
        def set_vnc_process_sink(self, sink) -> None:
            wired.append(sink)

        def watch_ping(self, signal) -> None:
            pass

    manager.add_session("10.0.0.1", _FakeWidget())

    assert wired == [manager.register_vnc], (
        "add_session не пробрасывает приёмник: внешний VNC-клиент снова "
        "станет неучтённым и переживёт закрытие вкладки"
    )


def test_tab_manager_closes_vnc_on_tab_close_and_exit():
    """Путь пользователя: закрытие вкладки и выход из программы."""
    from cashcontrol.gui import tab_manager as tm

    tree = ast.parse(Path(tm.__file__).read_text(encoding="utf-8"))

    has_kill_vnc = any(
        isinstance(n, ast.Attribute) and n.attr == "kill_vnc" for n in ast.walk(tree)
    )
    has_cleanup = any(
        isinstance(n, ast.Attribute) and n.attr == "cleanup" for n in ast.walk(tree)
    )
    assert has_kill_vnc, "close_tab перестал вызывать kill_vnc"
    assert has_cleanup, "TabManager.cleanup перестал вызываться при выходе"
