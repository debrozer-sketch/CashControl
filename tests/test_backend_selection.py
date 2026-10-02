"""Выбор транспорта для удалённой файловой системы.

SFTP-подсистемы нет у dropbear, TinyCore и вендорских сборок вроде касс
«Тиникор»: ``start_sftp_client()`` отклоняется или виснет. На таких хостах
работает только shell и SCP, поэтому выбор транспорта обязателен.

Проверено на тестовой кассе: TinyCore отвечает ``SFTPConnectionLost``.
"""

from __future__ import annotations

import asyncio

import asyncssh
import pytest

from cashcontrol.builtin.file_manager.backends import (
    SFTP_SUBSYSTEM_TIMEOUT,
    ScpShellBackend,
    SftpBackend,
    build_remote_backend,
)


class _FakeSftp:
    """Двойник SFTP-клиента с тем же набором методов, что и настоящий.

    Метода ``close()`` у ``asyncssh.SFTPClient`` нет: есть ``exit()`` и
    ``await wait_closed()``. Двойник с ``close()`` был щедрее настоящего
    класса, из-за чего вызов ``probe.close()`` проходил тесты и падал на
    живой кассе с работающей SFTP-подсистемой.
    """

    def __init__(self, stall_close: bool = False) -> None:
        self.exited = False
        self.waited = False
        self.stall_close = stall_close

    def exit(self) -> None:
        self.exited = True

    async def wait_closed(self) -> None:
        if self.stall_close:
            await asyncio.sleep(3600)
        self.waited = True


class _FakeConn:
    def __init__(self, sftp_error: BaseException | None = None, hang: bool = False) -> None:
        self.sftp_error = sftp_error
        self.hang = hang
        self.probe: _FakeSftp | None = None
        self.started = 0
        self.stall_close = False

    async def start_sftp_client(self):
        self.started += 1
        if self.hang:
            await asyncio.sleep(3600)
        if self.sftp_error is not None:
            raise self.sftp_error
        self.probe = _FakeSftp(stall_close=self.stall_close)
        return self.probe

    def is_closed(self) -> bool:
        return False


def test_fake_sftp_is_not_richer_than_the_real_one():
    """Сторож против повторного появления ``probe.close()``.

    Проверяются обе стороны: у настоящего класса ``close`` нет, и у двойника
    тоже нет. Если двойник вновь обзаведётся ``close``, возврат этого вызова
    снова пройдёт тесты и снова упадёт на кассе.
    """
    assert not hasattr(asyncssh.SFTPClient, "close"), (
        "asyncssh.SFTPClient всё-таки обзавёлся close() — сверьтесь с API"
    )
    assert not hasattr(_FakeSftp, "close"), (
        "двойник стал щедрее настоящего класса, тесты перестали ловить дефект"
    )
    assert hasattr(asyncssh.SFTPClient, "exit")
    assert hasattr(asyncssh.SFTPClient, "wait_closed")


@pytest.mark.asyncio
async def test_picks_sftp_when_subsystem_available():
    conn = _FakeConn()
    choice = await build_remote_backend(conn)

    assert isinstance(choice.backend, SftpBackend)
    assert choice.used_sftp is True
    assert conn.probe is not None, "проба SFTP не запускалась"
    assert conn.probe.exited is True, "пробный канал SFTP остался открытым"
    assert conn.probe.waited is True, "закрытие пробы не дождались"


@pytest.mark.asyncio
async def test_probe_that_never_finishes_closing_does_not_hang_upload():
    """Сервер, принявший пробу, но не закрывающий канал, не должен вешать выгрузку.

    Закрытие пробы ждёт под тем же таймаутом, что и её открытие: иначе
    ``await probe.wait_closed()`` висел бы вечно и выгрузка не завершалась
    бы ни успехом, ни ошибкой.
    """
    conn = _FakeConn()
    conn.stall_close = True

    choice = await build_remote_backend(conn, sftp_timeout=0.05)

    assert isinstance(choice.backend, SftpBackend)
    assert conn.probe is not None and conn.probe.exited is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        asyncssh.Error(0, "subsystem not available"),
        asyncssh.ChannelOpenError(3, "unknown channel type"),
        asyncssh.SFTPConnectionLost(0, "0 bytes read"),
        OSError("connection lost"),
    ],
    ids=["asyncssh-error", "channel-open", "sftp-connection-lost", "os-error"],
)
async def test_falls_back_to_scp_when_sftp_refused(error):
    conn = _FakeConn(sftp_error=error)
    choice = await build_remote_backend(conn)

    assert isinstance(choice.backend, ScpShellBackend)
    assert choice.used_sftp is False
    assert choice.close_backend is False


@pytest.mark.asyncio
async def test_sftp_probe_timeout_falls_back_instead_of_raising():
    """Сервер, который не отвечает на подсистему, не должен ронять перетаскивание."""
    conn = _FakeConn(hang=True)
    choice = await build_remote_backend(conn, sftp_timeout=0.05)

    assert isinstance(choice.backend, ScpShellBackend)
    assert choice.used_sftp is False


@pytest.mark.asyncio
async def test_own_connection_drives_close_backend():
    conn = _FakeConn()
    choice = await build_remote_backend(conn, own_connection=True)

    assert choice.used_sftp is True
    assert choice.close_backend is True
    assert choice.backend._own_connection is True


@pytest.mark.asyncio
async def test_fallback_never_claims_ownership():
    """У чужого соединения нельзя закрывать канал: им пользуется сессия кассы."""
    conn = _FakeConn(sftp_error=asyncssh.Error(0, "no subsystem"))
    choice = await build_remote_backend(conn, own_connection=True)

    assert isinstance(choice.backend, ScpShellBackend)
    assert choice.close_backend is False


@pytest.mark.asyncio
async def test_probe_runs_once_per_choice():
    conn = _FakeConn()
    await build_remote_backend(conn)
    assert conn.started == 1


def test_default_sftp_timeout_is_finite():
    assert 0 < SFTP_SUBSYSTEM_TIMEOUT < 60
