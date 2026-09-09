"""Unit tests for the vendored TOFU host-key storage (core/connection.py)."""

from __future__ import annotations

import sys

import pytest

from cashcontrol.gui.ssh_terminal_launcher import builtin_terminal_root

pytestmark = pytest.mark.skipif(
    not builtin_terminal_root().is_dir(),
    reason="vendored builtin_terminal/ is not present",
)


class _FakeKey:
    def __init__(self, data: str) -> None:
        self._data = data

    def export_public_key(self, fmt: str) -> str:
        return self._data


@pytest.fixture
def conn(tmp_path):
    root = builtin_terminal_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from core.connection import SSHConnection

    return SSHConnection(
        host="10.0.0.1",
        username="root",
        port=22,
        known_hosts_path=tmp_path / "known_hosts",
    )


def test_tofu_new_host_key_is_stored(conn):
    key = _FakeKey("ssh-ed25519 AAAANEWKEY")
    assert conn._trust_new_host_key("10.0.0.1", "10.0.0.1", 22, key) is True
    data = conn._known_hosts_path.read_text(encoding="utf-8")
    assert "[10.0.0.1]:22 ssh-ed25519 AAAANEWKEY" in data


def test_tofu_repeat_same_key_accepted_without_duplicate(conn):
    key = _FakeKey("ssh-ed25519 AAAANEWKEY")
    assert conn._trust_new_host_key("10.0.0.1", "10.0.0.1", 22, key) is True
    assert conn._trust_new_host_key("10.0.0.1", "10.0.0.1", 22, key) is True
    data = conn._known_hosts_path.read_text(encoding="utf-8")
    assert data.count("AAAANEWKEY") == 1


def test_tofu_changed_key_rejected(conn):
    good = _FakeKey("ssh-ed25519 AAAAGOOD")
    evil = _FakeKey("ssh-ed25519 AAAAEVIL")
    assert conn._trust_new_host_key("10.0.0.1", "10.0.0.1", 22, good) is True
    assert conn._trust_new_host_key("10.0.0.1", "10.0.0.1", 22, evil) is False
    data = conn._known_hosts_path.read_text(encoding="utf-8")
    assert "AAAAGOOD" in data
    assert "AAAAEVIL" not in data
