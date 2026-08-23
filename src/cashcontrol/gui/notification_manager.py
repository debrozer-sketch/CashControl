from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QObject, Signal


class NotificationLevel:
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Notification:
    timestamp: datetime
    level: str
    message: str
    id: int = field(default_factory=lambda: NotificationManager._next_id())


class NotificationManager(QObject):
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

    def notify(self, message: str, level: str = NotificationLevel.INFO) -> None:
        n = Notification(timestamp=datetime.now(), level=level, message=message)
        self._notifications.append(n)
        self.notification_added.emit(n)

    def get_all(self) -> list[Notification]:
        return list(reversed(self._notifications))

    def clear(self) -> None:
        self._notifications.clear()

    def __init__(self) -> None:
        super().__init__()
        self._notifications: list[Notification] = []


def get_notification_manager() -> NotificationManager:
    return NotificationManager.instance()
