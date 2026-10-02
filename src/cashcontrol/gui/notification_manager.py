"""Журнал уведомлений: всё, что сообщили пользователю, остаётся здесь.

Модуль не знает про Qt-виджеты. За показ отвечает
``cashcontrol.gui.feedback``; сюда попадает только запись.

Прямого входа для записи нет: ``record`` зовёт только ``feedback.notify``.
Второй путь в журнал, ``NotificationManager.notify``, удалён в задаче 10
унификации — из-за него шестьдесят шесть мест вызова оставались без записи,
а формально обратная связь у них была.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from PySide6.QtCore import QObject, Signal

from cashcontrol.infrastructure.audit_logger import get_logger

logger = get_logger()


class Level(StrEnum):
    """Четыре уровня. ``StrEnum``, а не ``Enum``: палитра и журнал панели
    сравнивают уровень со строкой."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


def normalize_level(value: str | Level) -> Level:
    """Привести уровень к :class:`Level`.

    Раньше ``notify`` принимал любую строку, и опечатка ``sucess`` молча
    показывалась как ``info`` — с неверным цветом и без следа в логе.
    """
    if isinstance(value, Level):
        return value
    try:
        return Level(str(value).strip().lower())
    except ValueError:
        logger.warning(f"Неизвестный уровень уведомления {value!r}, показан как info")
        return Level.INFO


@dataclass(frozen=True)
class Notification:
    id: int
    timestamp: datetime
    level: Level
    message: str
    title: str = ""


class NotificationManager(QObject):
    """Хранит записи и отдаёт их панели через ``notification_added``."""

    notification_added = Signal(object)

    _instance: NotificationManager | None = None
    _counter: int = 0

    @classmethod
    def instance(cls) -> NotificationManager:
        if cls._instance is None:
            cls._instance = NotificationManager()
        return cls._instance

    @classmethod
    def _next_id(cls) -> int:
        cls._counter += 1
        return cls._counter

    def record(
        self,
        message: str,
        level: str | Level = Level.INFO,
        *,
        title: str = "",
    ) -> Notification:
        """Добавить запись в журнал и отда её панели."""
        n = Notification(
            id=self._next_id(),
            timestamp=datetime.now(),
            level=normalize_level(level),
            message=message,
            title=title,
        )
        self._notifications.append(n)
        self.notification_added.emit(n)
        return n

    def get_all(self) -> list[Notification]:
        return list(reversed(self._notifications))

    def clear(self) -> None:
        self._notifications.clear()
        # Счётчик сбрасывается вместе с журналом: иначе после очистки
        # идентификаторы продолжали бы расти от значения, накопленного
        # прошлой сессией, и их нельзя было бы сравнивать в тестах.
        type(self)._counter = 0

    def __init__(self) -> None:
        super().__init__()
        self._notifications: list[Notification] = []


def get_notification_manager() -> NotificationManager:
    return NotificationManager.instance()
