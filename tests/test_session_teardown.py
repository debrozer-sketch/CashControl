"""Закрытие сессии: SSH и БД должны освобождаться всегда.

Регрессия в ``CashSession.disconnect`` и ``abort``:

1. ``await self._ssh.disconnect()`` шёл без ``try/finally``. Если SSH рвал
   соединение, исключение прерывало метод: ``_is_connected`` оставался
   ``True``, а подключение к БД не закрывалось вообще.
2. ``self._db = None`` выполнялся безусловно, даже если ``db.disconnect()``
   упал. asyncpg-соединение оставалось открытым без владельца.
3. ``db_connect_task`` обнулялся, но не отменялся. Задача, дойдя до
   ``DBSession.connect()`` после ``abort()``, создавала соединение, которое
   уже никто не закрывал.
"""

from __future__ import annotations

import asyncio

import pytest

from cashcontrol.core.session import CashSession


class _FakeSSH:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.disconnect_calls = 0
        self.abort_calls = 0

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.fail:
            raise ConnectionResetError("соединение разорвано")

    def abort(self) -> None:
        self.abort_calls += 1


class _FakeDB:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.disconnect_calls = 0
        self.closed = False

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.fail:
            raise RuntimeError("БД не закрывается")
        self.closed = True


def _session(ssh=None, db=None) -> CashSession:
    session = CashSession("10.0.0.1")
    session._ssh = ssh if ssh is not None else _FakeSSH()
    session._db = db
    return session


# ── 1. Обрыв SSH не должен мешать закрытию БД ───────────────────────────

async def test_db_is_closed_even_if_ssh_disconnect_raises():
    db = _FakeDB()
    session = _session(ssh=_FakeSSH(fail=True), db=db)
    session._is_connected = True

    await session.disconnect()  # не должно бросать

    assert db.disconnect_calls == 1, "БД не закрылась из-за ошибки SSH"
    assert session._is_connected is False


async def test_disconnect_propagates_nothing_on_ssh_failure():
    session = _session(ssh=_FakeSSH(fail=True))
    session._is_connected = True
    await session.disconnect()  # исключение наружу не выходит


# ── 2. Неудача закрытия БД не должна терять ссылку ───────────────────────

async def test_db_reference_kept_when_close_fails():
    db = _FakeDB(fail=True)
    session = _session(db=db)
    session._db_connected = True

    await session.disconnect()

    assert session._db is db, (
        "ссылка потеряна при неудачном закрытии: соединение осиротеет"
    )
    assert session._db_connected is False


async def test_db_reference_dropped_after_successful_close():
    db = _FakeDB()
    session = _session(db=db)

    await session.disconnect()

    assert db.closed is True
    assert session._db is None


async def test_retry_closes_db_after_transient_failure():
    """Второй вызов disconnect() обязан добить соединение."""
    db = _FakeDB(fail=True)
    session = _session(db=db)

    await session.disconnect()
    assert session._db is db

    db.fail = False
    await session.disconnect()

    assert session._db is None
    assert db.closed is True


# ── 3. Фоновая задача подключения к БД отменяется ───────────────────────

async def test_db_connect_task_is_cancelled():
    session = _session()
    started = asyncio.Event()

    async def _slow_connect() -> bool:
        started.set()
        await asyncio.sleep(30)
        return True

    task = asyncio.ensure_future(_slow_connect())
    await started.wait()
    session.db_connect_task = task

    await session.disconnect()

    assert session.db_connect_task is None
    await asyncio.sleep(0)
    assert task.cancelled(), "фоновая задача подключения не отменена"


async def test_db_connect_task_cancelled_on_abort():
    session = _session()
    started = asyncio.Event()

    async def _slow_connect() -> bool:
        started.set()
        await asyncio.sleep(30)
        return True

    task = asyncio.ensure_future(_slow_connect())
    await started.wait()
    session.db_connect_task = task

    await session.abort()

    assert session.db_connect_task is None
    await asyncio.sleep(0)  # cancel() только запрашивает отмену
    assert task.cancelled()


async def test_completed_db_task_is_not_cancelled_again():
    """Готовая задача не должна трогаться, иначе теряется её результат."""
    session = _session()

    async def _done() -> bool:
        return True

    task = asyncio.ensure_future(_done())
    await task
    session.db_connect_task = task

    await session.disconnect()

    assert not task.cancelled()
    assert task.result() is True


# ── abort ───────────────────────────────────────────────────────────────

async def test_abort_closes_db_and_ssh_even_with_failures():
    db = _FakeDB(fail=True)
    ssh = _FakeSSH(fail=True)
    session = _session(ssh=ssh, db=db)
    session._is_connected = True
    session._db_connected = True

    await session.abort()

    assert ssh.abort_calls == 1
    assert db.disconnect_calls == 1
    assert session._is_connected is False
    assert session._db_connected is False


async def test_disconnect_without_db_is_safe():
    session = _session()
    session._is_connected = True
    await session.disconnect()
    assert session._is_connected is False


async def test_disconnect_is_idempotent():
    db = _FakeDB()
    session = _session(db=db)
    await session.disconnect()
    await session.disconnect()
    assert db.disconnect_calls == 1


@pytest.mark.parametrize("method", ["disconnect", "abort"])
async def test_both_paths_release_everything(method):
    db = _FakeDB()
    ssh = _FakeSSH()
    session = _session(ssh=ssh, db=db)
    session._is_connected = True
    session._db_connected = True

    await getattr(session, method)()

    assert session._is_connected is False
    assert session._db_connected is False
    assert session._db is None
    assert session.db_connect_task is None
