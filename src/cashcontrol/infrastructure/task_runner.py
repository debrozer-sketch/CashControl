"""Запуск фоновых задач GUI без потери ссылки.

asyncio держит на задачу только слабую ссылку: если результат
``ensure_future`` не сохранить, задача может быть собран сборщиком мусора
в любой момент, и действие молча оборвётся посреди выполнения, без ошибки
и без записи в журнал. Отдельный отказ задачи к тому же приводит к
предупреждению "Task exception was never retrieved".

``spawn`` удерживает задачу до завершения и гарантирует, что исключение
из неё будет залогировано, а не потеряно.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Coroutine

logger = get_logger()

__all__ = ["cancel_all", "spawn"]

# Ссылка на живые фоновые задачи. Уборка происходит в add_done_callback.
_background: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, label: str = "") -> asyncio.Task:
    """Запустить coroutine в фоне, удержав ссылку до завершения."""
    task = asyncio.ensure_future(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    task.add_done_callback(_report_failure)
    if label:
        task.set_name(label)
    return task


def _report_failure(task: asyncio.Task) -> None:
    """Записать исключение из задачи, которая завершилась с ошибкой."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None:
        return
    name = task.get_name()
    logger.error(f"Фоновая задача {name or '<без имени>'} завершилась с ошибкой: {exc}")


def cancel_all() -> None:
    """Отменить все живые фоновые задачи (при выходе из приложения)."""
    for task in list(_background):
        if not task.done():
            task.cancel()
    _background.clear()


def active_count() -> int:
    return len(_background)
