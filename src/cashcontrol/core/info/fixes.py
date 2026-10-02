"""Протокол исправления найденных проблем.

Само исправление — это запись на кассе, а значит данные конкретного
торговля: какое значение и в какую строку писать. Оно живёт в
``cashcontrol.internal``. Здесь форма, общая для любой починки, и точка
входа ``get_fix``.

Исправление пишет, поэтому устроено иначе, чем чтение:

- решение о записи принимает оператор, а не таймер: ``plan()`` только
  показывает, что именно будет изменено, и ничего не выполняет;
- значение, которое будет записано, задано исправлением, а не приходит с
  кассы и не вводится строкой оператором;
- перед записью старое значение читается и сохраняется, чтобы изменение
  можно было вернуть обратно;
- запись идемпотентна: повтор не меняет ничего и не пишет дважды;
- после записи значение читается обратно и сверяется — успех объявляется
  по факту, а не по коду возврата команды;
- ничего не применяется молча и повторно при неудаче.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession


@dataclass(frozen=True)
class FixPlan:
    """Что именно будет изменено. Ничего не выполнено."""

    fix_id: str
    title: str
    before: str
    after: str
    sql: str
    # Когда изменение вступит в силу. Пусто означает «сразу», и это осознанное
    # решение: молчаливое применение здесь опаснее отсутствия, а «сразу» —
    # утверждение о поведении чужой системы, которое легко ошибить.
    effect: str = ""

    def summary(self) -> str:
        return f"{self.title}: {self.before} → {self.after}"


@dataclass(frozen=True)
class FixResult:
    """Итог попытки. ``applied`` означает факт, а не намерение."""

    fix_id: str
    applied: bool
    before: str
    after: str
    message: str

    @property
    def changed(self) -> bool:
        return self.applied and self.before != self.after


class Fix(ABC):
    """Одно исправление: умеет показать план и выполнить его."""

    id: str = "fix"
    title: str = "Исправление"
    # Когда правка вступит в силу. Пишется самим исправлением, потому что это
    # свойство кассового ПО, а не интерфейса: у ящика значение читается сразу,
    # у DNS касса перечитывает ключи только при загрузке. Диалог подставляет
    # эту строку, а не выдумывает свою, иначе оператор увидит «исправлено» и
    # решит, что резолвер сменился, хотя касса ещё работает со старым.
    effect_note: str = ""

    @abstractmethod
    async def plan(self, session: CashSession) -> FixPlan | None:
        """Вернуть план, если есть что исправлять, иначе ``None``.

        ``None`` — не ошибка: проблема уже отсутствует, либо исправление к
        этой кассе не относится.
        """

    @abstractmethod
    async def apply(self, session: CashSession) -> FixResult:
        """Выполнить план и вернуть проверенный итог."""

    def _plan(self, before: str, after: str, sql: str) -> FixPlan:
        return FixPlan(
            fix_id=self.id,
            title=self.title,
            before=before,
            after=after,
            sql=sql,
            effect=self.effect_note,
        )


def get_fix(fix_id: str) -> Fix | None:
    """Исправление по идентификатору или ``None``.

    ``None`` — обычный ответ, а не поломка: в публичной сборке исправлений
    нет вообще, и интерфейс просто не рисует кнопку.
    """
    with suppress(ImportError):
        from cashcontrol.internal.fixer import get_fix as _get_fix

        return _get_fix(fix_id)
    return None


__all__ = ["Fix", "FixPlan", "FixResult", "get_fix"]
