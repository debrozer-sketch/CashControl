"""Tests for the SessionInterface facade and cash_types detection strategies."""

import asyncio
from pathlib import Path

import pytest

from cashcontrol.core.session import CashSession
from cashcontrol.core.session_interface import SessionInterface
from cashcontrol.infrastructure.config_manager import ConfigManager


class FakeSSH:
    """Minimal SSHSession stub."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.uploads: list[tuple[str, str]] = []
        self.downloads: list[tuple[str, str]] = []

    async def execute(self, command, timeout=30, check=False):
        from cashcontrol.core.ssh import CommandResult

        self.commands.append(command)
        return CommandResult(stdout="ok", stderr="", exit_code=0, success=True)

    async def upload_file(self, local, remote, preserve=True):
        self.uploads.append((str(local), remote))

    async def download_file(self, remote, local, preserve=True):
        self.downloads.append((remote, str(local)))


@pytest.fixture()
def session(monkeypatch) -> CashSession:
    s = CashSession("10.0.0.1", config=ConfigManager())
    monkeypatch.setattr(s, "_ssh", FakeSSH())
    monkeypatch.setattr(s, "_is_connected", True)
    return s


class TestFacade:
    def test_is_session_interface(self, session):
        assert isinstance(session, SessionInterface)

    async def test_exec_returns_exec_result(self, session):
        result = await session.exec("uptime")
        assert result.ok and result.stdout == "ok"
        assert session._ssh.commands == ["uptime"]

    def test_exec_when_disconnected(self, monkeypatch):
        s = CashSession("10.0.0.2", config=ConfigManager())
        result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            s.exec("ls")
        )
        assert not result.ok and "Not connected" in result.stderr

    async def test_run_tuple_compat(self, session):
        code, out, err = await session.run("date")
        assert (code, out, err) == (0, "ok", "")

    async def test_upload_download_delegate(self, session):
        assert await session.upload(Path("a.txt"), "/tmp/a.txt") is True
        assert await session.download("/tmp/b.txt", Path("b.txt")) is True
        assert session._ssh.uploads == [("a.txt", "/tmp/a.txt")]
        assert session._ssh.downloads == [("/tmp/b.txt", "b.txt")]

    async def test_ping_true_on_open_port(self, session, monkeypatch):
        class FakeWriter:
            def close(self):
                pass

        async def fake_open_connection(host, port):
            return None, FakeWriter()

        async def fake_wait_for(coro, timeout):
            return await coro

        monkeypatch.setattr(
            "cashcontrol.core.session.asyncio.open_connection", fake_open_connection
        )
        monkeypatch.setattr(
            "cashcontrol.core.session.asyncio.wait_for", fake_wait_for
        )
        assert await session.ping() is True

    async def test_ping_false_on_refused(self, session, monkeypatch):
        async def fake_open_connection(host, port):
            raise OSError("refused")

        monkeypatch.setattr(
            "cashcontrol.core.session.asyncio.open_connection", fake_open_connection
        )
        assert await session.ping() is False


class TestDetectorStrategies:
    def _fake_session(self, files: dict[str, str], outputs: dict[str, str] | None = None):
        from types import SimpleNamespace

        from cashcontrol.core.ssh import CommandResult

        inst = SimpleNamespace(ssh_connected=True)

        async def execute(command, timeout=30, check=False):
            for path, content in files.items():
                if command.startswith("cat ") and path in command:
                    return CommandResult(content, "", 0, True)
            out = (outputs or {}).get(command.strip(), "")
            return CommandResult(out, "" if out else "no such", 0 if out else 1, bool(out))

        inst.ssh = SimpleNamespace(execute=execute)
        return inst

    XML = '<register moduleType="sco_v3" productVersion="4.0"><x a="pos"/></register>'

    async def test_xml_keywords_resolves_alias(self):
        from cashcontrol.core.cash_types.strategies import xml_keywords

        session = self._fake_session({"p.xml": self.XML})
        cache = {}
        rule = {"path": "p.xml", "strategy": "xml_keywords"}
        assert await xml_keywords(rule, session, cache) == "sco3"

    async def test_regex_file_with_map(self):
        from cashcontrol.core.cash_types.strategies import regex_file

        session = self._fake_session({"/opt/kind": "KIND=KIOSK\n"})
        rule = {
            "path": "/opt/kind",
            "pattern": r"^KIND=(\w+)",
            "map": {"KIOSK": "sco3"},
        }
        assert await regex_file(rule, session, {}) == "sco3"

    async def test_shell_uses_map_and_first_line(self):
        from cashcontrol.core.cash_types.strategies import shell

        session = self._fake_session({}, {"hostnamectl | grep Type": "POS\nextra\n"})
        rule = {"command": "hostnamectl | grep Type", "map": {"POS": "pos"}}
        assert await shell(rule, session, {}) == "pos"

    async def test_detector_priority_ordering_stable_for_bad_priority(self):
        rules = [{"id": "a", "priority": "high"}, {"id": "b", "priority": 100}]
        rules.sort(key=_prio)
        assert rules[0]["id"] == "b"
        assert rules[-1]["id"] == "a"


def _prio(rule):
    from cashcontrol.core.cash_types.detector import _rule_priority

    return _rule_priority(rule)
