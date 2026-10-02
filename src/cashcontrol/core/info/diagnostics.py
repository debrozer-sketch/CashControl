"""Публичные точки входа диагностики.

Сами проверки, названия секций и названия банков — данные конкретного
торговля, и лежат они в ``cashcontrol.internal``. Здесь форма находки, базовый
класс проверки и вход, через который ими пользуется интерфейс. В публичной
сборке внутреннего пакета нет, поэтому проверок нет тоже: список пуст, а
панель проблем просто молчит.

Пустой список — не ошибка импорта. Публичная версия программы обязана
запускаться и показывать панель информации.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cashcontrol.core.info.info_manager import CashInfoSnapshot


@dataclass
class ProblemIssue:
    section: str
    message: str
    severity: str = "warning"  # "warning" | "error"
    # Идентификатор проверки, а не её подпись. По нему ищется исправление в
    # реестре фиксов: подпись «Денежный ящик» — для человека и для
    # сопоставления с фиксом не годится. Само исправление объявляет проверка,
    # поэтому интерфейсу не нужно знать, какие проверки чинятся, а какие нет:
    # он спрашивает реестр и рисует кнопку по ответу.
    check_id: str = ""


class DiagnosticCheck(ABC):
    """Base class for one diagnostic rule."""

    id: str = "check"

    def applies_to(self, cash_type: str) -> bool:
        """Override to restrict the check to specific cash types/features."""
        return True

    @abstractmethod
    def check(self, snapshot: CashInfoSnapshot, cash_type: str) -> ProblemIssue | None:
        ...


_checker: object | None = None
_loaded = False


def _load() -> None:
    global _checker, _loaded
    if _loaded:
        return
    _loaded = True
    with suppress(ImportError):
        from cashcontrol.internal import rules

        _checker = rules.ProblemChecker()


def make_problem_checker():
    """Сборщик находок или ``None``, если проверок в сборке нет."""
    _load()
    return _checker


def check(snapshot: CashInfoSnapshot, cash_type: str) -> list[ProblemIssue]:
    """Все находки по снимку; в публичной сборке список пуст."""
    checker = make_problem_checker()
    if checker is None:
        return []
    return checker.check(snapshot, cash_type)


__all__ = [
    "DiagnosticCheck",
    "ProblemIssue",
    "check",
    "make_problem_checker",
]
