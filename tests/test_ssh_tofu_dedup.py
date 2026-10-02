"""TOFU в core/ssh.py: ключ хоста не должен дублироваться в known_hosts.

Регрессия: ``SSHSession._record_host_key`` дописывала строку безусловно.
Блок first-contact выполняется на каждой итерации перебора паролей, поэтому
любая вторая попытка (неверный пароль на первом шаге, сетевая ошибка на
втором подключении) дописывала в ``data/known_hosts`` ещё одну
идентичную строку. Вендоренный терминал от такого защищён тестом
(tests/test_builtin_tofu.py), а этот путь был нет.
"""

from __future__ import annotations

import pytest

from cashcontrol.core.ssh import SSHSession


class _FakeKey:
    def __init__(self, data: str) -> None:
        self._data = data

    def export_public_key(self, fmt: str = "openssh") -> bytes:
        return self._data.encode("ascii")


class _FakeConn:
    def __init__(self, key: _FakeKey) -> None:
        self._key = key

    def get_server_host_key(self):
        return self._key


@pytest.fixture
def session(tmp_path, monkeypatch):
    """SSHSession с known_hosts во временном каталоге."""
    from cashcontrol.infrastructure import path_resolver

    kh = tmp_path / "known_hosts"
    monkeypatch.setattr(path_resolver, "get_known_hosts_file", lambda: kh, raising=False)
    s = SSHSession("10.0.0.1")
    s._known_hosts_override = kh
    return s, kh


def _record(session, kh, key_data: str) -> None:
    session._conn = _FakeConn(_FakeKey(key_data))
    original = session._known_hosts_entry
    session._known_hosts_entry = lambda: (kh, "[10.0.0.1]:22")
    try:
        session._record_host_key()
    finally:
        session._known_hosts_entry = original
        session._conn = None


def test_new_host_key_is_stored(session):
    s, kh = session
    _record(s, kh, "ssh-ed25519 AAAANEWKEY")

    data = kh.read_text(encoding="utf-8")
    assert "[10.0.0.1]:22 ssh-ed25519 AAAANEWKEY" in data


def test_repeat_same_key_does_not_duplicate(session):
    """Главный сценарий: вторая попытка не дописывает строку."""
    s, kh = session
    _record(s, kh, "ssh-ed25519 AAAANEWKEY")
    _record(s, kh, "ssh-ed25519 AAAANEWKEY")
    _record(s, kh, "ssh-ed25519 AAAANEWKEY")

    data = kh.read_text(encoding="utf-8")
    assert data.count("AAAANEWKEY") == 1, (
        f"в known_hosts {data.count('AAAANEWKEY')} одинаковых строк"
    )


def test_many_password_attempts_do_not_grow_file(session):
    """Много попыток подбора пароля — файл не растёт."""
    s, kh = session
    for _ in range(10):
        _record(s, kh, "ssh-ed25519 AAAASAME")

    assert len([ln for ln in kh.read_text(encoding="utf-8").splitlines() if ln.strip()]) == 1


def test_different_host_appends_its_own_line(session):
    s, kh = session
    _record(s, kh, "ssh-ed25519 AAAANEWKEY")

    original = s._known_hosts_entry
    s._conn = _FakeConn(_FakeKey("ssh-ed25519 AAAANEWKEY"))
    s._known_hosts_entry = lambda: (kh, "[10.0.0.2]:22")
    try:
        s._record_host_key()
    finally:
        s._known_hosts_entry = original
        s._conn = None

    data = kh.read_text(encoding="utf-8")
    assert "[10.0.0.1]:22 ssh-ed25519 AAAANEWKEY" in data
    assert "[10.0.0.2]:22 ssh-ed25519 AAAANEWKEY" in data


def test_changed_key_for_same_host_is_appended_for_review(session):
    """Смена ключа на том же хосте дописывается, чтобы пользователь увидел.

    Проверку при следующем подключении делает TOFU-сверка; важно, что новая
    строка не потерялась молча.
    """
    s, kh = session
    _record(s, kh, "ssh-ed25519 AAAAGOOD")
    _record(s, kh, "ssh-ed25519 AAAANEW")

    data = kh.read_text(encoding="utf-8")
    assert "AAAAGOOD" in data
    assert "AAAANEW" in data


def test_missing_key_raises(session):
    from cashcontrol.core.ssh import SSHConnectionError

    s, kh = session
    original = s._known_hosts_entry
    s._conn = type("C", (), {"get_server_host_key": lambda self: None})()
    s._known_hosts_entry = lambda: (kh, "[10.0.0.1]:22")
    try:
        with pytest.raises(SSHConnectionError):
            s._record_host_key()
    finally:
        s._known_hosts_entry = original
        s._conn = None


def test_unreadable_known_hosts_still_records(session, monkeypatch):
    """Ошибка чтения не должна блокировать запись ключа.

    Без возможности прочитать файл дедупликация невозможна, поэтому строка
    дописывается повторно. Это осознанный размен: лучше лишняя строка в
    known_hosts, чем потерянный ключ хоста.
    """
    s, kh = session
    _record(s, kh, "ssh-ed25519 AAAANEWKEY")

    import pathlib

    real_read = pathlib.Path.read_text

    def _boom(self, *a, **kw):
        if self == kh:
            raise OSError("файл заблокирован")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", _boom)
    _record(s, kh, "ssh-ed25519 AAAANEWKEY")
    monkeypatch.undo()  # вернуть настоящий read_text до проверки

    data = kh.read_text(encoding="utf-8")
    assert "[10.0.0.1]:22 ssh-ed25519 AAAANEWKEY" in data, (
        "при недоступном файле ключ хоста всё равно должен быть записан"
    )
