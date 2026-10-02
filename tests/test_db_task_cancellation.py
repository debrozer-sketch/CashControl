"""Тесты отмены сбора информации во время ожидания подключения к БД.

Регрессия: ``barcode_scanner._collect_from_db`` и ``scales._collect_from_db``
ждали ``CashSession.db_connect_task`` прямым ``await`` под
``contextlib.suppress(Exception)``. Отмена собирающей задачи (кнопка
«Обновить», фоновое обновление по TTL) уходила внутрь db_connect_task и
делала его cancelled навсегда. ``asyncio.CancelledError`` не наследует
Exception, поэтому ``suppress`` его не ловил и каждый последующий сбор
для этой вкладки падал без записи в лог.
"""

from __future__ import annotations

import asyncio

import pytest

from cashcontrol.core.info.collectors._db_task import wait_for_db_task


class _Session:
    def __init__(self, task: asyncio.Task | None) -> None:
        self.db_connect_task = task


async def test_our_cancellation_does_not_poison_shared_task():
    """Главный сценарий: отменяем сбор, общая задада БД должна выжить."""
    loop = asyncio.get_running_loop()
    started = loop.create_future()

    async def slow_db_connect() -> bool:
        started.set_result(True)
        await asyncio.sleep(10)  # долгий коннект к БД
        return True

    db_task = asyncio.ensure_future(slow_db_connect())
    session = _Session(db_task)

    async def collector() -> bool:
        return await wait_for_db_task(session)

    gather = asyncio.ensure_future(collector())
    await started
    gather.cancel()  # GUI отменяет текущий сбор

    with pytest.raises(asyncio.CancelledError):
        await gather

    # Ключевое утверждение: задача БД не отменена и не заблокирована.
    assert not db_task.cancelled(), "db_connect_task отменён чужим сбором"
    assert db_task.done() is False, "db_connect_task преждевременно завершён"

    # Следующий сбор (кнопка «Обновить» снова) обязан дождаться той же задачи.
    db_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await db_task


async def test_repeated_cancellations_never_break_later_collections():
    """Серия отмен не должна ломать последующие сборы."""
    loop = asyncio.get_running_loop()
    started = loop.create_future()

    async def slow_db_connect() -> bool:
        started.set_result(True)
        await asyncio.sleep(10)
        return True

    db_task = asyncio.ensure_future(slow_db_connect())
    session = _Session(db_task)
    await started

    for _ in range(5):
        task = asyncio.ensure_future(wait_for_db_task(session))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not db_task.cancelled()

    db_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await db_task


async def test_successful_task_reports_true():
    async def quick() -> bool:
        return True

    task = asyncio.ensure_future(quick())
    assert await wait_for_db_task(_Session(task)) is True


async def test_absent_task_reports_false():
    assert await wait_for_db_task(_Session(None)) is False


async def test_failing_task_reports_false_instead_of_raising():
    async def boom() -> bool:
        raise RuntimeError("БД недоступна")

    task = asyncio.ensure_future(boom())
    assert await wait_for_db_task(_Session(task)) is False


async def test_already_cancelled_task_reports_false_not_raises():
    """Если задачу отменили извне, коллектор идёт дальше, а не падает."""

    async def slow() -> bool:
        await asyncio.sleep(10)
        return True

    task = asyncio.ensure_future(slow())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await wait_for_db_task(_Session(task)) is False
