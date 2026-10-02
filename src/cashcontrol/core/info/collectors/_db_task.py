"""Ожидание общей фоновой задачи подключения к БД.

``CashSession.db_connect_task`` создаётся один раз на вкладку и ждётся сразу
несколькими коллекторами. Прямой ``await`` здесь опасен: отмена собирающего
таска (кнопка «Обновить», фоновое обновление по TTL, закрытие вкладки)
передаётся asyncio внутрь ``db_connect_task``, и та задача навсегда
переходит в состояние cancelled. Ссылка на неё не пересоздаётся, поэтому
все следующие ``await`` бросают CancelledError, а он не ловится через
``except Exception``. Сбор информации для вкладки перестаёт работать без
единой записи в лог.

``asyncio.shield`` отделяет чужую задачу от нашей отмены.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = logging.getLogger("cashcontrol")

__all__ = ["wait_for_db_task"]


async def wait_for_db_task(session: CashSession) -> bool:
    """Дождаться фонового подключения к БД, не сломав его отменой.

    Возвращает ``True``, если задача отработала, ``False`` если она не была
    запущена, завершилась ошибкой или уже отменена. Отмена *этой* coroutine
    пробрасывается вызывающему, как и положено.
    """
    task: Any = getattr(session, "db_connect_task", None)
    if task is None:
        return False

    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # shield гарантирует, что отмена пришла извне нашей задачи, только
        # если мы сами отменяемся. Отменённый db_connect_task до этого
        # пережил чужую отмену и результата уже не даст.
        if not task.cancelled():
            raise
        logger.debug("db_connect_task уже отменён — продолжаю без БД")
        return False
    except Exception as exc:
        logger.debug(f"Фоновое подключение к БД не удалось: {exc}")
        return False
    return True
