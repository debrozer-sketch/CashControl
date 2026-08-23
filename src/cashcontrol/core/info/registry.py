"""
Lazy collector registry — import collectors on demand, not at startup.

Usage:
    from cashcontrol.core.info.registry import get_collector, available_collectors

    collector = get_collector("os")
    data = await collector.collect(session)
"""

from __future__ import annotations

import importlib

_COLLECTOR_SPECS: dict[str, tuple[str, str]] = {
    "bank_terminal": ("cashcontrol.core.info.collectors.bank_terminal", "BankTerminalCollector"),
    "barcode_scanner": ("cashcontrol.core.info.collectors.barcode_scanner", "BarcodeScannerCollector"),
    "cash_software": ("cashcontrol.core.info.collectors.cash_software", "CashSoftwareCollector"),
    "cash_type": ("cashcontrol.core.info.collectors.cash_type", "CashTypeCollector"),
    "cpu_info": ("cashcontrol.core.info.collectors.cpu_info", "CPUInfoCollector"),
    "customer_display": ("cashcontrol.core.info.collectors.customer_display", "CustomerDisplayCollector"),
    "dns_info": ("cashcontrol.core.info.collectors.dns_info", "DNSInfoCollector"),
    "drawer_close": ("cashcontrol.core.info.collectors.drawer_close", "DrawerCloseCollector"),
    "fiscal_printer": ("cashcontrol.core.info.collectors.fiscal_printer", "FiscalPrinterCollector"),
    "keyboard": ("cashcontrol.core.info.collectors.keyboard", "KeyboardCollector"),
    "loymax": ("cashcontrol.core.info.collectors.loymax", "LoymaxCollector"),
    "os_info": ("cashcontrol.core.info.collectors.os_info", "OSInfoCollector"),
    "payment_ranks": ("cashcontrol.core.info.collectors.payment_ranks", "PaymentRanksCollector"),
    "qrid": ("cashcontrol.core.info.collectors.qrid", "QRIDCollector"),
    "scales": ("cashcontrol.core.info.collectors.scales", "ScalesCollector"),
}

_cache: dict[str, object] = {}

# UI section name → canonical collector key
SECTION_ALIASES: dict[str, str] = {
    "os": "os_info",
    "cpu": "cpu_info",
    "dns": "dns_info",
    "software": "cash_software",
    "scanners": "barcode_scanner",
}


def get_collector(name: str):
    """Get collector instance by name (lazy — imports on first call)."""
    if name not in _cache:
        module_path, cls_name = _COLLECTOR_SPECS[name]
        module = importlib.import_module(module_path)
        cls = getattr(module, cls_name)
        _cache[name] = cls()
    return _cache[name]


def available_collectors() -> list[str]:
    return list(_COLLECTOR_SPECS.keys())


def resolve_section(section: str) -> str | None:
    """Map a UI section name to a collector key from this registry."""
    key = SECTION_ALIASES.get(section, section)
    return key if key in _COLLECTOR_SPECS else None


def get_collector_for_section(section: str):
    """Collector instance for a UI section name (None if unknown)."""
    key = resolve_section(section)
    return get_collector(key) if key else None
