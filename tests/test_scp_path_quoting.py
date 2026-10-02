"""Передача файлов по SCP на кассы TinyCore.

asyncssh собирает команду ``scp -t <путь>`` сам, пробел в имени не
экранируется, и TinyCore отвечает ``scp: ambiguous target``. Из-за этого
на таких кассах не работали:

- перетаскивание файла, в имени которого есть пробел;
- переименование при занятом имени: файловый сервис даёт копии вида
  ``имя (1).расширение``, то есть с пробелом всегда.

Проверено на тестовой кассе «Тиникор» (172.18.105.69): без экранирования
``report (1).txt`` падает, с экранированием проходит, а обычные имена
остаются нетронутыми.
"""

from __future__ import annotations

import shlex

import asyncssh
import pytest

from cashcontrol.builtin.file_manager.backends import SSHScpProvider


@pytest.fixture
def scp_calls(monkeypatch):
    """Перехватываем вызов asyncssh.scp и записываем его аргументы."""
    calls: list[tuple] = []

    async def _fake_scp(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(asyncssh, "scp", _fake_scp)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote",
    [
        "/home/tc/storage/отчёт.txt",
        "/home/tc/storage/report (1).txt",
        "/home/tc/storage/a b;c.txt",
        "/home/tc/storage/report.txt",
        "/home/tc/storage",
    ],
)
async def test_upload_remote_path_is_shell_quoted(scp_calls, remote):
    provider = SSHScpProvider(object())

    await provider.upload("/local/file.bin", remote)

    (args, _kwargs) = scp_calls[-1]
    assert args[1][1] == shlex.quote(remote), (
        "удалённый путь должен быть экранирован для удалённого shell"
    )


@pytest.mark.asyncio
async def test_plain_path_is_not_mangled(scp_calls):
    """Экранирование не должно ломать обычные имена."""
    provider = SSHScpProvider(object())

    await provider.upload("/local/file.bin", "/home/tc/storage/report.txt")

    (args, _kwargs) = scp_calls[-1]
    assert args[1][1] == "/home/tc/storage/report.txt"


@pytest.mark.asyncio
async def test_download_remote_path_is_quoted_too(scp_calls):
    provider = SSHScpProvider(object())

    await provider.download("/home/tc/storage/отчёт.txt", "/local/file.bin")

    (args, _kwargs) = scp_calls[-1]
    assert args[0][1] == shlex.quote("/home/tc/storage/отчёт.txt")


@pytest.mark.asyncio
async def test_local_path_is_passed_as_is(scp_calls):
    """Локальный путь экранировать нельзя: он не идёт в удалённый shell."""
    provider = SSHScpProvider(object())

    await provider.upload("/local/файл с пробелом.bin", "/home/tc/storage/a.txt")

    (args, _kwargs) = scp_calls[-1]
    assert args[0] == "/local/файл с пробелом.bin"


@pytest.mark.asyncio
async def test_upload_uses_own_connection_when_configured(monkeypatch):
    """С connect_kwargs перенос идёт по своему короткому соединению."""
    import cashcontrol.builtin.file_manager.backends as backends

    opened: list[dict] = []

    async def _fake_connect(**kwargs):
        opened.append(kwargs)
        raise RuntimeError("касса не отвечает")

    monkeypatch.setattr(backends, "connect_with_tofu", _fake_connect)
    provider = SSHScpProvider(object(), {"host": "10.0.0.1"})

    with pytest.raises(RuntimeError):
        await provider.upload("/local/file.bin", "/home/tc/storage/a b.txt")

    assert opened, "ожидалось отдельное подключение для переноса"


@pytest.mark.asyncio
async def test_upload_reuses_connection_without_connect_kwargs(scp_calls, monkeypatch):
    """Без connect_kwargs перенос идёт по уже открытому соединению."""
    import cashcontrol.builtin.file_manager.backends as backends

    def _must_not_be_called(**_kwargs):
        raise AssertionError("не должно быть нового подключения")

    monkeypatch.setattr(backends, "connect_with_tofu", _must_not_be_called)
    provider = SSHScpProvider(object())

    await provider.upload("/local/file.bin", "/home/tc/storage/a.txt")

    assert scp_calls, "перенос должен был выполниться"
