"""Как секция превращается в строки панели информации.

Большинство секций рисуется общим способом — по готовым полям секции. Но у
некоторых подписи строк отличаются от имён полей, и для них нужен свой
сборщик. Список таких секций задаёт не этот файл, а владелец данных о них:
публичные сборщики подписаны здесь, внутренние приходят из
``cashcontrol.internal``.

Поэтому в публичной сборке реестр пуст, и внутренние секции уехали вместе с
данными — рисовать их нечего, а общего правила для них не существует.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from cashcontrol.core.info.info_manager import InfoField, InfoSection


@dataclass(frozen=True)
class SectionRenderer:
    """Сборщик строк секции.

    ``needs_feature_gate`` означает, что секция показывается не всегда: тип
    кассы может не поддерживать её. Проверку применяет интерфейс, он же
    оставляет след о неприменимости, — сам сборщик про тип кассы ничего не знает.
    """

    build: Callable[[InfoSection], list[InfoField]]
    needs_feature_gate: bool = False


_renderers: dict[str, SectionRenderer] = {}
_loaded = False


def register(name: str, renderer: SectionRenderer) -> None:
    _renderers[name] = renderer


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    with suppress(ImportError):
        from cashcontrol.internal import render

        render.register(_renderers)


def renderer_for(name: str) -> SectionRenderer | None:
    """Сборщик секции или ``None``, если секция рисуется общим способом."""
    _load()
    return _renderers.get(name)


__all__ = ["SectionRenderer", "register", "renderer_for"]
