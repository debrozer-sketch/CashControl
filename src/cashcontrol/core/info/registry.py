"""
Lazy collector registry — import collectors on demand, not at startup.

Usage:
    from cashcontrol.core.info.registry import get_collector, available_collectors

    collector = get_collector("os_info")
    data = await collector.collect(session)

Граница публичной сборки проходит по пакету ``cashcontrol.internal``: в нём
собираются сборщики и заголовки секций, не предназначенные для публичного
репозитория. Реестр грузит этот пакет один раз и молча продолжает работать,
если его нет, — в публичной сборке каталога ``internal/`` не существует, и
внутренние секции просто не появляются.
"""

from __future__ import annotations

import importlib
from contextlib import suppress
from dataclasses import dataclass


@dataclass(frozen=True)
class CollectorSpec:
    """Описание сборщика: чем грузить и какую секцию он рисует.

    ``group`` пустой у служебных секций: они собираются, но в панели
    информации не показываются.
    """

    key: str
    module: str
    cls: str
    section: str
    title: str = ""
    group: str | None = None
    order: int = 0
    group_order: int | None = None

    @property
    def service(self) -> bool:
        return self.group is None

    @property
    def display_order(self) -> int:
        """Порядок внутри группы.

        Отличается от порядка сбора: в группе «system» сборка идёт с
        ``cash_type``, а показ — с ``os``. Отдельное поле нужно, чтобы оба
        порядка пережили разрез по вариантам сборки.
        """
        return self.order if self.group_order is None else self.group_order


_COLLECTORS = "cashcontrol.core.info.collectors"

# Публичные сборщики. Внутренних имён здесь нет и быть не должно: этот файл
# попадает в публичный репозиторий целиком.
_PUBLIC_SPECS: tuple[CollectorSpec, ...] = (
    CollectorSpec(
        "cash_type", f"{_COLLECTORS}.cash_type", "CashTypeCollector",
        "cash_type", "Тип кассы", "system", 0, 2,
    ),
    CollectorSpec(
        "os_info", f"{_COLLECTORS}.os_info", "OSInfoCollector",
        "os", "Операционная система", "system", 1, 0,
    ),
    CollectorSpec(
        "cpu_info", f"{_COLLECTORS}.cpu_info", "CPUInfoCollector",
        "cpu", "Процессор", "system", 2, 1,
    ),
    CollectorSpec(
        "customer_display", f"{_COLLECTORS}.customer_display", "CustomerDisplayCollector",
        "customer_display", "Дисплей покупателя", "equipment", 4, 1,
    ),
    CollectorSpec(
        "barcode_scanner", f"{_COLLECTORS}.barcode_scanner", "BarcodeScannerCollector",
        "scanners", "Сканер штрих-кодов", "equipment", 5, 2,
    ),
    CollectorSpec(
        "scales", f"{_COLLECTORS}.scales", "ScalesCollector",
        "scales", "Весы", "equipment", 6, 3,
    ),
    CollectorSpec(
        "keyboard", f"{_COLLECTORS}.keyboard", "KeyboardCollector",
        "keyboard", "Клавиатура", "equipment", 7, 4,
    ),
)

_specs: dict[str, CollectorSpec] = {s.key: s for s in _PUBLIC_SPECS}
_cache: dict[str, object] = {}
_internal_loaded = False


def _ensure_internal() -> None:
    """Подключить пакет внутренних сборщиков, если он есть.

    Единственное место в программе, где допускается отсутствие модуля:
    публичной сборке он не нужен, и её единственный признак — этого каталога
    нет. Всё остальное ходит за секциями через реестр.
    """
    global _internal_loaded
    if _internal_loaded:
        return
    _internal_loaded = True
    with suppress(ImportError):
        from cashcontrol import internal

        register(internal.SPECS)


def register(specs: tuple[CollectorSpec, ...]) -> None:
    """Добавить сборщики в реестр.

    Вызывает пакет ``cashcontrol.internal`` при загрузке. Имён внутренних
    сборщиков в этом файле нет: их приносит только этот пакет.
    """
    for spec in specs:
        _specs[spec.key] = spec


def _ordered() -> list[CollectorSpec]:
    return sorted(_specs.values(), key=lambda s: s.order)


def get_collector(name: str):
    """Get collector instance by name (lazy — imports on first call)."""
    _ensure_internal()
    if name not in _cache:
        spec = _specs.get(name)
        if spec is None:
            raise KeyError(name)
        module = importlib.import_module(spec.module)
        cls = getattr(module, spec.cls)
        _cache[name] = cls()
    return _cache[name]


def invalidate_collectors() -> None:
    """Сбросить мемоизированные экземпляры коллекторов.

    Нужно после правки detection/*.toml и cash_types/*.toml: без сброса
    get_collector() возвращает прежний CashTypeCollector вместе с его
    TypeDetector, и новое правило детекции не вступает в силу до
    перезапуска приложения.
    """
    _cache.clear()


def available_collectors() -> list[str]:
    _ensure_internal()
    return list(_specs.keys())


def resolve_section(section: str) -> str | None:
    """Map a UI section name to a collector key from this registry."""
    _ensure_internal()
    for spec in _specs.values():
        if spec.section == section:
            return spec.key
    return None


def get_collector_for_section(section: str):
    """Collector instance for a UI section name (None if unknown)."""
    key = resolve_section(section)
    return get_collector(key) if key else None


def all_sections() -> list[str]:
    """Секции в порядке сбора."""
    _ensure_internal()
    return [s.section for s in _ordered()]


def service_sections() -> list[str]:
    """Секции, которые собираются, но в панели не рисуются."""
    _ensure_internal()
    return [s.section for s in _ordered() if s.service]


# Порядок разделов в панели информации. Пустые группы в ответ не попадают:
# в публичной сборке раздела «other» нет вовсе.
_GROUP_ORDER: tuple[str, ...] = ("system", "equipment", "other")


def section_groups() -> dict[str, list[str]]:
    """Отображаемые секции по группам, в исходном порядке."""
    _ensure_internal()
    grouped: dict[str, list[CollectorSpec]] = {}
    for spec in _specs.values():
        if spec.group is not None:
            grouped.setdefault(spec.group, []).append(spec)
    return {
        name: [s.section for s in sorted(grouped[name], key=lambda s: s.display_order)]
        for name in _GROUP_ORDER
        if name in grouped
    }


def section_titles() -> dict[str, str]:
    """Заголовки отображаемых секций."""
    _ensure_internal()
    return {s.section: s.title for s in _ordered() if s.title}
