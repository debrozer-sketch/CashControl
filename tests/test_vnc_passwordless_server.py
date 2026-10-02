"""Общий старт VNC: команда запуска выполняется всегда, потом клиент.

Требование: у всех кнопок VNC один и тот же начальный сценарий — запуск
сервера на кассе. И только потом открывается клиент, встроенный или
внешний.

Команда запуска (``_X11VNC_CMD``) начинается с ``killall x11vnc``, то есть
это перезапуск, и несёт ``-nopw`` — сервер без пароля. Проверять «может,
уже запущен» было нельзя: если x11vnc на кассе поднят кем-то с паролем,
порт слушает, и внешний клиент подключался именно к нему и спрашивал
пароль. Встроенный просмотр пароль не спрашивает, из-за чего выглядело
так, будто сервер не запустился.

Поэтому проверок «свой чужой» здесь нет: команда выполняется безусловно,
а ожидание порта — это лишь ожидание готовности, а не решение о запуске.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("PySide6")

from cashcontrol.builtin.vnc import vnc_preview as vp
from cashcontrol.builtin.vnc.vnc_preview import VncPreviewWidget


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
    def __init__(self, ok: bool, stderr: str = "") -> None:
        self.exit_code = 0 if ok else 1
        self.stdout = ""
        self.stderr = stderr
        self.success = ok


class _Ssh:
    """После успешного запуска порт начинает слушаться, как на живой кассе.

    ``opens_after_start=False`` — случай «команда прошла, а сервер так и
    не поднялся».
    """

    def __init__(
        self,
        *,
        start_ok: bool = True,
        listening: bool = False,
        opens_after_start: bool = True,
    ) -> None:
        self.start_ok = start_ok
        self.listening = listening
        self.opens_after_start = opens_after_start
        self.commands: list[str] = []

    async def execute(self, command, **_kw):
        self.commands.append(command)
        if "netstat" in command:
            return _Result(self.listening)
        if vp._X11VNC_CMD[:40] in command:
            if self.start_ok and self.opens_after_start:
                self.listening = True
            return _Result(self.start_ok, stderr="x11vnc: not found")
        return _Result(True)


class _Session:
    def __init__(self, ssh: _Ssh | None = None, connected: bool = True) -> None:
        self.is_connected = connected
        self.ssh = ssh or _Ssh()


@pytest.fixture
def widget(qapp):
    w = VncPreviewWidget("10.0.0.1")
    states: list[tuple[str, str]] = []
    w.state_changed.connect(lambda st, msg: states.append((st, msg)))
    w._states = states
    yield w
    w.close()


def _started(ssh: _Ssh) -> bool:
    return any(vp._X11VNC_CMD[:40] in c for c in ssh.commands)


# ── команда выполняется всегда ─────────────────────────────────────


@pytest.mark.asyncio
async def test_command_runs_even_when_port_already_listening(widget):
    """Именно этот случай ломался: чужой сервер с паролем наслеживался."""
    ssh = _Ssh(listening=True)
    widget._session = _Session(ssh)

    await widget._ensure_x11vnc()

    assert _started(ssh), (
        "проверять «уже запущен» нельзя: порт слушает и парольный сервер, "
        "клиент подключится к нему и спросит пароль"
    )


@pytest.mark.asyncio
async def test_command_runs_when_nothing_is_listening(widget):
    ssh = _Ssh(listening=False)
    widget._session = _Session(ssh)
    await widget._ensure_x11vnc()
    assert _started(ssh)


@pytest.mark.asyncio
async def test_command_runs_twice_in_a_row(widget):
    """Каждое нажатие — новая гарантия, а не надежда на прошлый запуск."""
    ssh = _Ssh(listening=True)
    widget._session = _Session(ssh)

    await widget._ensure_x11vnc()
    await widget._ensure_x11vnc()

    assert sum(1 for c in ssh.commands if vp._X11VNC_CMD[:40] in c) == 2


@pytest.mark.asyncio
async def test_start_command_failure_is_reported(widget):
    """Неуспех запуска больше не проглатывается."""
    ssh = _Ssh(start_ok=False)
    widget._session = _Session(ssh)

    ready, reason = await widget._ensure_x11vnc()

    assert ready is False
    assert reason, "причина не должна быть пустой"


@pytest.mark.asyncio
async def test_port_never_opens_is_reported(widget):
    """Команда прошла, но сервер не поднялся — клиент не открываем."""
    ssh = _Ssh(start_ok=True, listening=False, opens_after_start=False)
    widget._session = _Session(ssh)

    ready, reason = await widget._ensure_x11vnc()

    assert ready is False
    assert "порт" in reason.lower()


@pytest.mark.asyncio
async def test_fullscreen_button_also_starts_server(widget, monkeypatch, tmp_path):
    """Общий старт один и на полноэкранной кнопке."""
    launched: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **_kw):
            launched.append(list(args))

    monkeypatch.setattr("subprocess.Popen", _FakePopen)
    monkeypatch.setattr(vp, "_VNC_START_DELAY", 0.0)
    monkeypatch.setattr(vp, "_SERVER_READY_TIMEOUT", 2.0)
    ssh = _Ssh(listening=True)
    widget._session = _Session(ssh)
    widget._config.settings.programs.vnc_client_path = str(tmp_path / "v.exe")
    (tmp_path / "v.exe").write_bytes(b"x")

    widget.open_fullscreen()
    for _ in range(60):
        await asyncio.sleep(0.02)

    assert _started(ssh), "команда запуска обязана выполняться и здесь"
    assert launched


@pytest.mark.asyncio
async def test_builtin_viewer_button_also_starts_server(widget, monkeypatch):
    monkeypatch.setattr(vp, "_VNC_START_DELAY", 0.0)
    monkeypatch.setattr(vp, "_SERVER_READY_TIMEOUT", 2.0)
    ssh = _Ssh(listening=True)
    widget._session = _Session(ssh)

    widget.connect_vnc()
    for _ in range(60):
        await asyncio.sleep(0.02)

    assert _started(ssh), "встроенный просмотр тоже начинается с запуска сервера"


@pytest.mark.asyncio
async def test_missing_session_is_reported(widget):
    widget._session = None
    ready, reason = await widget._ensure_x11vnc()
    assert ready is False
    assert "подключ" in reason.lower()


@pytest.mark.asyncio
async def test_session_not_ready_is_reported(widget):
    widget._session = _Session(_Ssh(), connected=False)
    ready, reason = await widget._ensure_x11vnc()
    assert ready is False
    assert "подключ" in reason.lower()


def test_command_starts_without_password(widget):
    """Без -nopw внешний клиент спросит пароль."""
    assert "-nopw" in vp._X11VNC_CMD


# ── клиент не открывается, пока сервер не готов ───────────────────


@pytest.mark.asyncio
async def test_external_client_not_opened_when_start_fails(widget, monkeypatch, tmp_path):
    launched: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **_kw):
            launched.append(list(args))

    monkeypatch.setattr("subprocess.Popen", _FakePopen)
    monkeypatch.setattr(vp, "_VNC_START_DELAY", 0.0)
    monkeypatch.setattr(vp, "_SERVER_READY_TIMEOUT", 0.1)
    ssh = _Ssh(start_ok=False)
    widget._session = _Session(ssh)
    widget._config.settings.programs.vnc_client_path = str(tmp_path / "v.exe")
    (tmp_path / "v.exe").write_bytes(b"x")

    widget.open_client(fullscreen=False)
    for _ in range(30):
        await asyncio.sleep(0.02)

    assert _started(ssh), "команда запуска должна выполняться всегда"
    assert not launched, "клиент не открывается без работающего сервера"
    assert [m for st, m in widget._states if st == "error"]


@pytest.mark.asyncio
async def test_external_client_opened_after_start(widget, monkeypatch, tmp_path):
    launched: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **_kw):
            launched.append(list(args))

    monkeypatch.setattr("subprocess.Popen", _FakePopen)
    monkeypatch.setattr(vp, "_VNC_START_DELAY", 0.0)
    monkeypatch.setattr(vp, "_SERVER_READY_TIMEOUT", 2.0)
    ssh = _Ssh(listening=True)
    widget._session = _Session(ssh)
    widget._config.settings.programs.vnc_client_path = str(tmp_path / "v.exe")
    (tmp_path / "v.exe").write_bytes(b"x")

    widget.open_client(fullscreen=False)
    for _ in range(60):
        await asyncio.sleep(0.02)

    assert _started(ssh), "сервер поднимается до клиента"
    assert launched, "после поднятия сервера клиент открывается"
    assert not [m for st, m in widget._states if st == "error"]
