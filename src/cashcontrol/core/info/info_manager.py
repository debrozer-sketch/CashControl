from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from cashcontrol.infrastructure.config_manager import ConfigManager

from cashcontrol.core.info import registry
from cashcontrol.infrastructure.audit_logger import get_logger

logger = get_logger()


class CollectionStatus(StrEnum):
    PENDING = auto()
    LOADING = auto()
    COMPLETE = auto()
    TIMEOUT = auto()
    ERROR = auto()
    SKIPPED = auto()


@dataclass
class InfoField:
    key: str
    label: str
    value: str
    alias_key: str | None = None
    builtin_value: str = ""


@dataclass
class InfoSection:
    name: str
    status: CollectionStatus = CollectionStatus.PENDING
    data: dict[str, Any] = field(default_factory=dict)
    fields: list[InfoField] = field(default_factory=list)
    error: str | None = None


ALL_SECTIONS: list[str] = registry.all_sections()

# Секции, которые собираются, но в панели информации не рисуются: у них нет
# группы. _render_section в gui/cash_session_widget.py их пропускает.
SECTION_GROUPS: dict[str, list[str]] = registry.section_groups()

SECTION_TITLES: dict[str, str] = registry.section_titles()


@dataclass
class CashInfoSnapshot:
    """Complete snapshot of cash register information."""

    host: str = ""
    timestamp: float = field(default_factory=time.time)

    cash_type: InfoSection = field(default_factory=lambda: InfoSection("cash_type"))
    os: InfoSection = field(default_factory=lambda: InfoSection("os"))
    cpu: InfoSection = field(default_factory=lambda: InfoSection("cpu"))
    customer_display: InfoSection = field(default_factory=lambda: InfoSection("customer_display"))
    scanners: InfoSection = field(default_factory=lambda: InfoSection("scanners"))
    scales: InfoSection = field(default_factory=lambda: InfoSection("scales"))
    keyboard: InfoSection = field(default_factory=lambda: InfoSection("keyboard"))

    def __post_init__(self) -> None:
        # Секции без собственного поля задаёт реестр, а не этот файл: у
        # внутренних сборщиков полей здесь нет, и в публичной сборке вместо
        # них будет None из get_section.
        for name in registry.all_sections():
            if not hasattr(self, name):
                setattr(self, name, InfoSection(name))

    def get_section(self, name: str) -> InfoSection | None:
        return getattr(self, name, None)


# Section names — collector imports resolve via core.info.registry.
# Содержит и отображаемые секции, и служебные, которые нужны только диагностике.


def _collection_order() -> tuple[str, ...]:
    """Порядок сбора с возвратом секции «software» на её место.

    Секции ПО больше нет, но запись осталась: resolve_section вернёт для неё
    None и сборка пропустит. Держать её в середине списка нужно ради волн
    сбора — первой идёт cash_type, её результатом пользуются остальные.
    """
    order: list[str] = []
    for name in registry.all_sections():
        order.append(name)
        if name == "cpu":
            order.append("software")
    return tuple(order)


_SECTIONS: tuple[str, ...] = _collection_order()


class InfoCollector:
    """
    Coordinates collection from all info collectors with caching.

    Wave 1: cash_type (sequential — other collectors may use its result).
    Wave 2: the rest, at most ``_parallel_workers`` at a time.
    Wave 3: whatever wave 2 lost, one collector at a time.
    """

    TASK_TIMEOUT = 10.0

    # Границы параметра info_parallel_workers. Верхняя граница не равна
    # числу секций намеренно: начиная примерно с половины секций сборщики
    # снова выстраиваются в очередь перед семафором каналов из core/ssh.py,
    # и очередь начинает съедать общий таймаут. Значение по умолчанию равно
    # пределу каналов в SSHSession._channel_semaphore — при нём ни один
    # сборщик не ждёт семафор, то есть таймаут тратится на работу.
    MIN_PARALLEL_WORKERS = 1
    MAX_PARALLEL_WORKERS = 8
    DEFAULT_PARALLEL_WORKERS = 4

    def __init__(self, config: ConfigManager | None = None) -> None:
        from cashcontrol.infrastructure.config_manager import ConfigManager

        self._config = config or ConfigManager()
        self._cache_ttl = self._config.settings.general.info_cache_ttl
        self._cache: dict[str, tuple[float, CashInfoSnapshot]] = {}
        self._collectors: dict[str, Any] = {}
        self._parallel_workers = self._clamp_workers(
            self._config.settings.general.info_parallel_workers
        )

    @classmethod
    def _clamp_workers(cls, value: object) -> int:
        """Привести параметр к рабочему диапазону.

        settings.json правится рукой, и туда можно вписать 0 или 99. Ноль
        означал бы «не запускать сборщики вовсе», а 99 вернул бы ровно тот
        дефект, который эта правка чинит. Значение вне диапазона берётся к
        умолчанию, а не к границе: молчаливая подмена «99» на «8» выглядела
        бы как работающее ограничение, которого на самом деле нет.
        """
        try:
            workers = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return cls.DEFAULT_PARALLEL_WORKERS
        if not (cls.MIN_PARALLEL_WORKERS <= workers <= cls.MAX_PARALLEL_WORKERS):
            return cls.DEFAULT_PARALLEL_WORKERS
        return workers

    # ── Collector management ─────────────────────────────────────────────

    def _ensure_collectors(self) -> None:
        """Build the section→collector mapping once and reuse it.

        Сбор идёт из потока GUI, поэтому импорт модулей и сканирование
        каталога collectors/ выполняются один раз, а не на каждый вызов.
        """
        if not self._collectors:
            self.reload()

    def reload(self) -> None:
        """Rebuild the section→collector mapping (used after settings changes).

        Мемоизированные экземпляры сбрасываются, иначе правка
        detection/*.toml и cash_types/*.toml не вступит в силу: реестр
        вернул бы прежний CashTypeDetector.
        """
        from cashcontrol.core.info.registry import invalidate_collectors

        invalidate_collectors()
        self._invalidate_detection_cache()
        self._collectors = self._build_collectors()

    @staticmethod
    def _invalidate_detection_cache() -> None:
        """Сбросить кэш правил детекции и реестр типов касс."""
        from cashcontrol.core.cash_types import get_cash_type_registry
        from cashcontrol.infrastructure.path_resolver import get_detection_dir

        try:
            get_cash_type_registry().reload()
        except Exception as exc:
            logger.warning(f"Реестр типов касс не перечитан: {exc}")

        detection_dir = get_detection_dir()
        if detection_dir.is_dir():
            logger.debug(f"Перечитываются правила детекции из {detection_dir}")

    def _build_collectors(self) -> dict[str, Any]:
        """Build section → collector mapping (lazy imports via registry)."""
        from cashcontrol.core.info.registry import get_collector_for_section

        collectors: dict[str, Any] = {}
        for section in _SECTIONS:
            try:
                collector = get_collector_for_section(section)
                if collector is not None:
                    collectors[section] = collector
            except Exception:
                import logging

                logging.getLogger("cashcontrol").exception(
                    f"Failed to load collector {section}"
                )

        # TOML collectors from collectors/ directory
        try:
            import tomllib

            from cashcontrol.core.info.collectors._toml_collector import TomlCollector
            from cashcontrol.infrastructure.path_resolver import get_collectors_dir

            coll_dir = get_collectors_dir()
            if coll_dir.exists():
                for path in sorted(coll_dir.glob("*.toml")):
                    try:
                        # Файл без секции [collector] — не коллектор, а
                        # набор правил [[rule]]. Такие файлы разбирает
                        # TomlRuleChecker, и раньше здесь они падали с
                        # KeyError('collector') и попадали в лог как
                        # «не загружен», хотя работали исправно.
                        with path.open("rb") as fh:
                            if "collector" not in tomllib.load(fh):
                                continue

                        tc = TomlCollector(path)
                        if tc.name not in collectors:
                            collectors[tc.name] = tc
                    except Exception as exc:
                        # Молчаливый pass скрывал битый TOML: пользователь
                        # правил файл, коллектор не появлялся, причину
                        # найти было негде.
                        logger.warning(f"Коллектор {path.name} не загружен: {exc}")
        except Exception as exc:
            logger.warning(f"Каталог коллекторов недоступен: {exc}")

        return collectors

    # ── Collection ───────────────────────────────────────────────────────

    async def collect_all(
        self,
        session,
        force: bool = False,
        on_section_ready: Callable[[InfoSection], None] | None = None,
    ) -> CashInfoSnapshot:
        if not force and session.host in self._cache:
            cached_time, cached_snapshot = self._cache[session.host]
            if (time.time() - cached_time) < self._cache_ttl:
                # Кэш-хит: панели рендерятся через on_section_ready, поэтому
                # отдадим секции закешированного снапшота так же, как при
                # живом сборе, иначе UI навсегда останется на скелетонах.
                if on_section_ready:
                    from dataclasses import fields as _dc_fields

                    for f in _dc_fields(cached_snapshot):
                        section = getattr(cached_snapshot, f.name, None)
                        if isinstance(section, InfoSection):
                            on_section_ready(section)
                return cached_snapshot

        snapshot = CashInfoSnapshot(host=session.host)
        self._ensure_collectors()
        collectors = dict(self._collectors)

        # Phase A: cash_type first (sequential)
        ct_collector = collectors.get("cash_type")
        if ct_collector is None:
            ct_section = InfoSection(
                "cash_type", CollectionStatus.ERROR, error="Коллектор типа кассы недоступен"
            )
        else:
            ct_section = await self._collect_one(session, "cash_type", ct_collector)
        snapshot.cash_type = ct_section
        if on_section_ready:
            on_section_ready(ct_section)

        # Phase B: remaining sections, at most _parallel_workers at a time.
        remaining = [
            n for n in ALL_SECTIONS if n != "cash_type" and n in collectors
        ]
        # Раньше вход во вторую фазу не был виден в логе: на кассе, где она
        # не начиналась, журнал обрывался на строке типа кассы, и было
        # нельзя отличить «фаза не пошла» от «фаза идёт, но молчит».
        logger.debug(
            f"Вторая фаза на {session.host}: {len(remaining)} секций, "
            f"параллельно до {self._parallel_workers}, "
            f"собрано всего {len(collectors)} сборщиков"
        )

        async def collect_one(name: str) -> tuple[str, InfoSection]:
            try:
                section = await asyncio.wait_for(
                    self._collect_one(session, name, collectors[name]),
                    timeout=self.TASK_TIMEOUT,
                )
            except TimeoutError:
                # Раньше здесь не было ни строки в лог: секция молча уходила
                # в TIMEOUT, и по журналу нельзя было отличить «касса не
                # отвечает» от «секция не применима». Имя секции, адрес и
                # сколько ждали — этого хватает, чтобы искать причину сразу.
                logger.warning(
                    f"Секция {name} на {session.host} не ответила за "
                    f"{self.TASK_TIMEOUT:g} с"
                )
                section = InfoSection(
                    name,
                    CollectionStatus.TIMEOUT,
                    error=f"Касса не ответила за {self.TASK_TIMEOUT:g} с",
                )
            except Exception as e:
                section = InfoSection(name, CollectionStatus.ERROR, error=str(e))
            return name, section

        # Очередь вместо задачи на каждую секцию. Раньше все секции второй
        # фазы стартовали разом, и на кассе TinyCore залп упирался в лимит
        # одновременных каналов: сборщики стояли в очереди, пока их общий
        # TASK_TIMEOUT истекал, и уходили в TIMEOUT, не выполнив ни одной
        # команды. Теперь одновременно работает ровно столько сборщиков,
        # сколько указано в настройке, а доставка в GUI остаётся по мере
        # готовности секций, как при as_completed.
        todo = deque(remaining)
        done: asyncio.Queue[tuple[str, InfoSection]] = asyncio.Queue()

        async def worker() -> None:
            # deque общий, но popleft синхронный, а цикл событий однопоточный:
            # каждый сборщик забирает своё имя до первого await.
            while todo:
                await done.put(await collect_one(todo.popleft()))

        workers = min(self._parallel_workers, len(remaining))
        running = [asyncio.ensure_future(worker()) for _ in range(workers)]

        timed_out: list[str] = []
        try:
            for _ in range(len(remaining)):
                name, section = await done.get()
                setattr(snapshot, name, section)
                if section.status is CollectionStatus.TIMEOUT:
                    timed_out.append(name)
                if on_section_ready:
                    on_section_ready(section)
        finally:
            # Отмена сбора (кнопка «Обновить», закрытие вкладки) не должна
            # оставлять сборщики бить по кассе: без этого очередь дорабатывалась
            # бы уже после того, как её результат никому не нужен.
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)

        # Phase C: повторный проход по секциям без результата.
        if timed_out:
            await self._retry_sequential(
                session, timed_out, collectors, snapshot, on_section_ready
            )

        # Провал целиком в кэш не кладём: иначе кратковременный обрыв SSH
        # отравляет кэш на info_cache_ttl, повторные попытки берут тот же
        # битый снимок, а кнопка «Переподключить» не появляется.
        if self._snapshot_is_usable(snapshot):
            self._cache[session.host] = (time.time(), snapshot)
        elif session.host in self._cache:
            logger.debug(f"Сбор для {session.host} провален, кэш сброшен")
            del self._cache[session.host]
        return snapshot

    async def _retry_sequential(
        self,
        session,
        names: list[str],
        collectors: dict[str, Any],
        snapshot: CashInfoSnapshot,
        on_section_ready: Callable[[InfoSection], None] | None,
    ) -> None:
        """Пересобрать секции без результата по одной, заменяя неудачу.

        Ограничение параллелизма уменьшает число отказов, но не отменяет
        их: касса может не успеть и при малом числе одновременных сборщиков.
        Второй проход идёт строго последовательно, и это не компромисс, а
        приём: на кассе, отказывающей в залпе, последовательный проход
        проходит. Так секция либо получает данные, либо честно остаётся
        пустой — и то и другое видно в панели.

        Повторяются только TIMEOUT: это единственный статус без причины.
        ERROR уже объяснён текстом (файла нет, БД выключена), SKIPPED —
        решение коллектора, COMPLETE — данные. Повторять их значило бы
        зря тратить команды на кассе.
        """
        logger.info(
            f"Повторный проход на {session.host}: {len(names)} секций без "
            f"результата ({', '.join(names)}), по одной"
        )

        recovered: list[str] = []
        still_failed: list[str] = []

        for name in names:
            try:
                section = await asyncio.wait_for(
                    self._collect_one(session, name, collectors[name]),
                    timeout=self.TASK_TIMEOUT,
                )
            except TimeoutError:
                # Повтор не ответил за то же время. Прежняя секция с текстом
                # «касса не ответила» полезнее голого ERROR, поэтому её
                # оставляем и повтор в запись результата не отдаём.
                logger.warning(
                    f"Повтор секции {name} на {session.host} тоже не ответил "
                    f"за {self.TASK_TIMEOUT:g} с"
                )
                still_failed.append(name)
                continue

            # Результат повтора заменяет неудачный, а не ложится рядом:
            # в снимке и в панели для секции остаётся ровно одна запись,
            # поэтому вместо «Таймаут» оператор видит данные или настоящую
            # ошибку сбора.
            setattr(snapshot, name, section)
            if on_section_ready:
                on_section_ready(section)
            if section.status is CollectionStatus.COMPLETE:
                recovered.append(name)
            else:
                still_failed.append(name)

        logger.info(
            f"Повторный проход на {session.host}: восстановлено "
            f"{len(recovered)} из {len(names)}"
            + (f", без результата: {', '.join(still_failed)}" if still_failed else "")
        )

    @staticmethod
    def _snapshot_is_usable(snapshot: CashInfoSnapshot) -> bool:
        """Есть ли в снимке хоть одна секция, наполненная данными."""
        from dataclasses import fields as _dc_fields

        checked = 0
        for f in _dc_fields(snapshot):
            section = getattr(snapshot, f.name, None)
            if not isinstance(section, InfoSection):
                continue
            checked += 1
            if section.status in (CollectionStatus.COMPLETE, CollectionStatus.SKIPPED):
                return True
        # cash_type собирается всегда, поэтому без него считать нечего.
        return checked == 0

    async def _collect_one(
        self,
        session,
        section_name: str,
        collector: Any,
    ) -> InfoSection:
        """Collect a single section and return the InfoSection."""
        try:
            data = await collector.collect(session)

            skip_val = next(
                (v for k, v in data.items() if k.endswith("_skipped") and v in ("1", 1)),
                None,
            )
            err_val = next(
                (v for k, v in data.items() if k.endswith("_error") and v),
                None,
            )
            if skip_val is not None:
                status = CollectionStatus.SKIPPED
            elif err_val is not None:
                # Раньше COMPLETE был веткой по умолчанию, и секция с
                # записанной коллектором ошибкой рисовалась как зелёная.
                status = CollectionStatus.ERROR
            else:
                status = CollectionStatus.COMPLETE

            fields = data.pop("_fields", None)
            if fields is None:
                fields = [
                    InfoField(
                        key=k,
                        label=k.replace("_", " ").title(),
                        value=str(v),
                    )
                    for k, v in data.items()
                    if not k.endswith("_error")
                    and not k.endswith("_skipped")
                    and not k.endswith("_raw")
                ]

            return InfoSection(
                section_name, status, data=data, fields=fields,
                error=str(err_val) if err_val else None,
            )
        except Exception as e:
            return InfoSection(section_name, CollectionStatus.ERROR, error=str(e))

    # ── Cache ────────────────────────────────────────────────────────────

    def clear_cache(self, host: str | None = None) -> None:
        if host is None:
            self._cache.clear()
        elif host in self._cache:
            del self._cache[host]


_info_collector: InfoCollector | None = None


def get_info_collector() -> InfoCollector:
    """Return the shared InfoCollector instance.

    The TTL cache lives on the instance, so it must be shared across
    widgets/loads; a fresh instance per call would never hit the cache.
    """
    global _info_collector
    if _info_collector is None:
        _info_collector = InfoCollector()
    return _info_collector
