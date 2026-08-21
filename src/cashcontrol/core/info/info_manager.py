from __future__ import annotations

import asyncio
import time
from enum import auto, StrEnum
from typing import Any, Callable
from dataclasses import dataclass, field


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


ALL_SECTIONS: list[str] = [
    "cash_type",
    "os",
    "cpu",
    "software",
    "fiscal_printer",
    "customer_display",
    "scanners",
    "scales",
    "keyboard",
    "bank_terminal",
    "dns",
    "loymax",
    "qrid",
]

SECTION_GROUPS: dict[str, list[str]] = {
    "system": ["os", "cpu", "software", "cash_type"],
    "equipment": [
        "fiscal_printer",
        "customer_display",
        "scanners",
        "scales",
        "keyboard",
        "bank_terminal",
    ],
    "other": ["dns", "loymax", "qrid"],
}

SECTION_TITLES: dict[str, str] = {
    "os": "Операционная система",
    "cpu": "Процессор",
    "software": "ПО кассы",
    "cash_type": "Тип кассы",
    "fiscal_printer": "Фискальный регистратор",
    "customer_display": "Дисплей покупателя",
    "scanners": "Сканер штрих-кодов",
    "scales": "Весы",
    "keyboard": "Клавиатура",
    "bank_terminal": "Банковский терминал",
    "dns": "DNS",
    "loymax": "Loymax",
    "qrid": "QRID (Газпром СБП)",
}

GROUP_TITLES: dict[str, str] = {
    "system": "Система",
    "equipment": "Оборудование",
    "other": "Прочее",
}


@dataclass
class CashInfoSnapshot:
    """Complete snapshot of cash register information."""

    host: str = ""
    timestamp: float = field(default_factory=time.time)

    cash_type: InfoSection = field(default_factory=lambda: InfoSection("cash_type"))
    os: InfoSection = field(default_factory=lambda: InfoSection("os"))
    cpu: InfoSection = field(default_factory=lambda: InfoSection("cpu"))
    software: InfoSection = field(default_factory=lambda: InfoSection("software"))
    fiscal_printer: InfoSection = field(default_factory=lambda: InfoSection("fiscal_printer"))
    customer_display: InfoSection = field(default_factory=lambda: InfoSection("customer_display"))
    scanners: InfoSection = field(default_factory=lambda: InfoSection("scanners"))
    scales: InfoSection = field(default_factory=lambda: InfoSection("scales"))
    keyboard: InfoSection = field(default_factory=lambda: InfoSection("keyboard"))
    bank_terminal: InfoSection = field(default_factory=lambda: InfoSection("bank_terminal"))
    dns: InfoSection = field(default_factory=lambda: InfoSection("dns"))
    loymax: InfoSection = field(default_factory=lambda: InfoSection("loymax"))
    qrid: InfoSection = field(default_factory=lambda: InfoSection("qrid"))

    def get_section(self, name: str) -> InfoSection | None:
        return getattr(self, name, None)

    def is_complete(self) -> bool:
        return all(
            s.status != CollectionStatus.LOADING
            for name in ALL_SECTIONS
            if (s := self.get_section(name)) is not None
        )

    def has_errors(self) -> bool:
        return any(
            s.status == CollectionStatus.ERROR
            for name in ALL_SECTIONS
            if (s := self.get_section(name)) is not None
        )

    def sections_by_group(self) -> dict[str, list[InfoSection]]:
        result: dict[str, list[InfoSection]] = {}
        for group, names in SECTION_GROUPS.items():
            sections = []
            for name in names:
                sec = self.get_section(name)
                if sec is not None:
                    sections.append(sec)
            result[group] = sections
        return result


class BaseCollector:
    name: str = ""

    async def collect(self, session) -> dict[str, Any]:
        return {}


# Section name → (module, class) inside collectors package.
# Imported lazily to keep application startup fast.
_COLLECTOR_SPECS: dict[str, tuple[str, str]] = {
    "cash_type": ("cashcontrol.core.info.collectors.cash_type", "CashTypeCollector"),
    "os": ("cashcontrol.core.info.collectors.os_info", "OSInfoCollector"),
    "cpu": ("cashcontrol.core.info.collectors.cpu_info", "CPUInfoCollector"),
    "software": ("cashcontrol.core.info.collectors.cash_software", "CashSoftwareCollector"),
    "fiscal_printer": ("cashcontrol.core.info.collectors.fiscal_printer", "FiscalPrinterCollector"),
    "customer_display": ("cashcontrol.core.info.collectors.customer_display", "CustomerDisplayCollector"),
    "scanners": ("cashcontrol.core.info.collectors.barcode_scanner", "BarcodeScannerCollector"),
    "scales": ("cashcontrol.core.info.collectors.scales", "ScalesCollector"),
    "keyboard": ("cashcontrol.core.info.collectors.keyboard", "KeyboardCollector"),
    "bank_terminal": ("cashcontrol.core.info.collectors.bank_terminal", "BankTerminalCollector"),
    "dns": ("cashcontrol.core.info.collectors.dns_info", "DNSInfoCollector"),
    "loymax": ("cashcontrol.core.info.collectors.loymax", "LoymaxCollector"),
    "qrid": ("cashcontrol.core.info.collectors.qrid", "QridCollector"),
}


class InfoCollector:
    """
    Coordinates collection from all info collectors with caching.

    Wave 1: cash_type (sequential — other collectors may use its result).
    Wave 2: all remaining collectors run concurrently with a timeout.
    """

    TASK_TIMEOUT = 10.0

    def __init__(self) -> None:
        from cashcontrol.infrastructure.config_manager import ConfigManager

        self._config = ConfigManager()
        self._cache_ttl = self._config.settings.general.info_cache_ttl
        self._cache: dict[str, tuple[float, CashInfoSnapshot]] = {}
        self._collectors: dict[str, Any] = {}
        self._extra_collectors: list[Any] = []

    # ── Collector management ─────────────────────────────────────────────

    def register(self, collector: BaseCollector) -> None:
        """Register an extra collector (its .name must match a section)."""
        self._extra_collectors.append(collector)

    def _build_collectors(self) -> dict[str, Any]:
        """Build section → collector mapping (lazy imports)."""
        import importlib

        collectors: dict[str, Any] = {}
        for section, (module_path, cls_name) in _COLLECTOR_SPECS.items():
            try:
                module = importlib.import_module(module_path)
                collectors[section] = getattr(module, cls_name)()
            except Exception:
                import logging

                logging.getLogger("cashcontrol").exception(
                    f"Failed to load collector {section}"
                )

        # TOML collectors from collectors/ directory
        try:
            from cashcontrol.core.info.collectors._toml_collector import TomlCollector
            from cashcontrol.infrastructure.path_resolver import get_collectors_dir

            coll_dir = get_collectors_dir()
            if coll_dir.exists():
                for path in sorted(coll_dir.glob("*.toml")):
                    try:
                        tc = TomlCollector(path)
                        if tc.name not in collectors:
                            collectors[tc.name] = tc
                    except Exception:
                        pass
        except Exception:
            pass

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
                return cached_snapshot

        snapshot = CashInfoSnapshot(host=session.host)
        collectors = self._build_collectors()
        for extra in self._extra_collectors:
            name = getattr(extra, "name", "")
            if name and name not in collectors:
                collectors[name] = extra

        # Phase A: cash_type first (sequential)
        ct_section = await self._collect_one(session, "cash_type", collectors["cash_type"])
        setattr(snapshot, "cash_type", ct_section)
        if on_section_ready:
            on_section_ready(ct_section)

        # Phase B: remaining sections in parallel
        remaining = [
            n for n in ALL_SECTIONS if n != "cash_type" and n in collectors
        ]

        async def collect_one(name: str) -> tuple[str, InfoSection]:
            try:
                section = await asyncio.wait_for(
                    self._collect_one(session, name, collectors[name]),
                    timeout=self.TASK_TIMEOUT,
                )
            except TimeoutError:
                section = InfoSection(name, CollectionStatus.TIMEOUT)
            except Exception as e:
                section = InfoSection(name, CollectionStatus.ERROR, error=str(e))
            return name, section

        tasks = [collect_one(n) for n in remaining]
        for coro in asyncio.as_completed(tasks):
            name, section = await coro
            setattr(snapshot, name, section)
            if on_section_ready:
                on_section_ready(section)

        self._cache[session.host] = (time.time(), snapshot)
        return snapshot

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
                (v for k, v in data.items() if k.endswith("_skipped") and v == "1"),
                None,
            )
            status = CollectionStatus.SKIPPED if skip_val else CollectionStatus.COMPLETE

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

            return InfoSection(section_name, status, data=data, fields=fields)
        except Exception as e:
            return InfoSection(section_name, CollectionStatus.ERROR, error=str(e))

    # ── Cache ────────────────────────────────────────────────────────────

    def clear_cache(self, host: str | None = None) -> None:
        if host is None:
            self._cache.clear()
        elif host in self._cache:
            del self._cache[host]

    def get_cache_stats(self) -> dict[str, int]:
        return {"cached_hosts": len(self._cache), "cache_ttl": self._cache_ttl}
