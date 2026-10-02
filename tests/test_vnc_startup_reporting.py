"""Запуск VNC с кнопки тулбара.

Симптом: на кассе подключились, нажали VNC в тулбаре — ничего не
происходит. Ни встроенный просмотр не подключается, ни внешняя программа
не открывается.

Причина: результат запуска x11vnc использовался только для выбора паузы,
а сам факт неудачи никогда не показывался. Внешний просмотрщик
запускался в любом случае и молча не мог подключиться.

На кассах TinyCore это воспроизводится само собой: запуск x11vnc идёт
через сессионное соединение, которое к этому моменту уже исчерпано
сборщиками данных, и команда не проходит.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from cashcontrol.builtin.vnc.vnc_preview import VncPreviewWidget, _ConnState


@pytest.fixture(autouse=True)
def _no_real_waits(monkeypatch):
    """Убрать стенные ожидания из каждого теста файла.

    ``_VNC_START_DELAY`` — пауза перед подключением клиента, ``
    _SERVER_READY_TIMEOUT`` — сколько ждать готовности порта. В исходных
    значениях это 5 и 10 секунд реального сна. Часть тестов подменяла их
    вручную, а часть платила полную цену: восемь тестов съедали четверть
    всего прогона набора, ожидая того, что фейковый сокет «не откроется».

    Значения малы, но не нулевые: нулевой таймаут означал бы, что цикл
    готовности не выполняется ни разу и тест проходил бы, не проверив ничего.
    """
    from cashcontrol.builtin.vnc import vnc_preview as vp

    monkeypatch.setattr(vp, "_VNC_START_DELAY", 0.0)
    monkeypatch.setattr(vp, "_SERVER_READY_TIMEOUT", 0.05)


class _Result:
    def __init__(self, ok: bool) -> None:
        self.exit_code = 0 if ok else 1
        self.stdout = ""
        self.stderr = ""
        self.success = ok


class _Ssh:
    def __init__(self, *, fail: Exception | None = None, result: bool = True) -> None:
        self.fail = fail
        self.result = result
        self.commands: list[str] = []

    async def execute(self, command, **_kw):
        self.commands.append(command)
        if self.fail is not None:
            raise self.fail
        return _Result(self.result)


class _Session:
    def __init__(self, *, connected: bool = True, **kw) -> None:
        self.is_connected = connected
        self.ssh = _Ssh(**kw)


@pytest.fixture
def widget(qapp):
    w = VncPreviewWidget("10.0.0.1")
    states: list[tuple[str, str]] = []
    w.state_changed.connect(lambda st, msg: states.append((st, msg)))
    w._states = states
    yield w
    w.close()


def _set_session(widget, session) -> None:
    widget._session = session


def _drain(widget, cycles: int = 30) -> None:
    loop = asyncio.new_event_loop()
    try:
        for _ in range(cycles):
            loop.run_until_complete(asyncio.sleep(0))
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_ensure_reports_missing_session(widget):
    _set_session(widget, None)
    started, reason = await widget._ensure_x11vnc()
    assert started is False
    assert "подключ" in reason.lower()


@pytest.mark.asyncio
async def test_ensure_reports_ssh_failure(widget):
    _set_session(widget, _Session(fail=TimeoutError("command timeout")))
    started, reason = await widget._ensure_x11vnc()
    assert started is False
    assert reason, "причина сбоя не должна быть пустой"


@pytest.mark.asyncio
async def test_ensure_succeeds(widget):
    _set_session(widget, _Session())
    started, reason = await widget._ensure_x11vnc()
    assert started is True
    assert reason == ""


@pytest.mark.asyncio
async def test_external_client_not_launched_when_x11vnc_failed(widget, monkeypatch, tmp_path):
    """Запуск просмотрщика без работающего x11vnc — бессмысленно молчание."""
    launched: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **_kw):
            launched.append(list(args))

    monkeypatch.setattr("subprocess.Popen", _FakePopen)
    _set_session(widget, _Session(fail=TimeoutError("command timeout")))

    exe = tmp_path / "vncviewer.exe"
    exe.write_bytes(b"x")

    await widget._open_fullscreen_async(exe)

    assert not launched, "просмотрщик не должен запускаться, если x11vnc не поднялся"
    errors = [s for s, _ in widget._states if s == "error"]
    assert errors, "пользователю нужно сказать, что не удалось запустить x11vnc"


@pytest.mark.asyncio
async def test_external_client_launched_when_x11vnc_ok(widget, monkeypatch, tmp_path):
    launched: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **_kw):
            launched.append(list(args))

    monkeypatch.setattr("subprocess.Popen", _FakePopen)
    _set_session(widget, _Session())
    widget._vnc._state = _ConnState.CONNECTED

    exe = tmp_path / "vncviewer.exe"
    exe.write_bytes(b"x")

    await widget._open_fullscreen_async(exe)

    assert launched, "при работающем x11vnc просмотрщик должен запускаться"
    assert Path(launched[0][0]) == exe
    assert any(arg.startswith("10.0.0.1:") for arg in launched[0])


@pytest.mark.asyncio
async def test_ensure_reports_session_not_yet_connected(widget):
    """Сценарий пользователя: нажали VNC сразу после подключения.

    На кассе «Тиникор» первый контакт занимает несколько секунд (ключ
    хоста пишется, затем соединение переоткрывается). Если нажать VNC в
    этот момент, раньше происходило ровно ничего.
    """
    _set_session(widget, _Session(connected=False))
    started, reason = await widget._ensure_x11vnc()
    assert started is False
    assert "подключ" in reason.lower()


@pytest.mark.asyncio
async def test_open_client_reports_when_session_not_ready(widget, monkeypatch, tmp_path):
    """Ни одна ветка open_client не должна завершаться молча."""
    launched: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **_kw):
            launched.append(list(args))

    monkeypatch.setattr("subprocess.Popen", _FakePopen)
    _set_session(widget, _Session(connected=False))
    widget._config.settings.programs.vnc_client_path = str(
        tmp_path / "vncviewer.exe"
    )
    (tmp_path / "vncviewer.exe").write_bytes(b"x")

    widget.open_client(fullscreen=False)
    for _ in range(20):
        await asyncio.sleep(0.05)

    assert not launched, "просмотрщик не запускается без работающего x11vnc"
    errors = [msg for st, msg in widget._states if st == "error"]
    assert errors, "пользователь должен увидеть причину, а не пустоту"


@pytest.mark.asyncio
async def test_builtin_window_reports_reason(widget):
    _set_session(widget, _Session(fail=TimeoutError("command timeout")))

    win = widget._open_client_window()
    await widget._connect_client_window(win, fullscreen=False)

    errors = [msg for st, msg in widget._states if st == "error"]
    assert errors, "встроенный просмотр должен сообщить о сбое"
    assert errors[0].strip(), "сообщение не должно быть пустым"
