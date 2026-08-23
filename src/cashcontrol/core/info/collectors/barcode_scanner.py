"""
Barcode scanner collector.

For pos/touch/sco — reads barcodeScanner-serial-config.xml and extracts
all 'port' property values. Each port is looked up in usb_id_mapping.json
to get a human-readable device name.  USB connection is verified via
/sys/bus/usb/devices.

For sco3 — reads scanner config from PostgreSQL DB (hw_property table).

Applicable to: all cash types (pos, touch, sco, sco3)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cashcontrol.core.aliases.alias_manager import AliasManager
from cashcontrol.core.cash_types import has_feature
from cashcontrol.core.info.collectors._usb_mapper import (
    check_usb_connected,
    load_usb_mapping,
    lookup_device_by_path,
)
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

XML_PATH = (
    "/home/tc/storage/crystal-cash/config/plugins/"
    "barcodeScanner-serial-config.xml"
)

# SCO3 PostgreSQL query
_SCO3_QUERY = """
SELECT key, value
FROM public.hw_property
WHERE module = 'HARDWARE_SCANNER' AND key IN ('Default', 'Handle');
"""


class BarcodeScannerCollector:
    """Collects barcode scanner configuration."""

    async def collect(self, session: CashSession) -> dict[str, object]:
        """
        Collect barcode scanner info.

        Returns:
            Dict with:
                scanners: list of dicts, each:
                    {
                        "name":      "Zebra DS2208/DS9308 COM",
                        "port":      "/dev/usbSV05e0P1701",
                        "connected": True | False | None,
                    }
                scanner_error: error message or None
        """
        info: dict[str, object] = {
            "scanners": [],
            "scanner_error": None,
        }

        mapping = load_usb_mapping("scanner")

        try:
            if has_feature(session, "barcode_from_db"):
                port_values = await self._collect_from_db(session)
            else:
                port_values = await self._collect_from_xml(session)

            from cashcontrol.core.info.info_manager import InfoField

            scanners = []
            fields: list[InfoField] = []
            for port in port_values:
                name, device_info = lookup_device_by_path(port, mapping)
                connected = await check_usb_connected(session, device_info)
                scanners.append(
                    {"name": name, "port": port, "connected": connected}
                )
                vid_pid = None
                if device_info:
                    ids = device_info.get("usb_ids", [])
                    if ids:
                        vid_pid = ids[0]
                        parts = vid_pid.split(":")
                        if len(parts) == 2:
                            alias_key = AliasManager.usb_key(parts[0], parts[1])
                            fields.append(InfoField(
                                key=f"scanner_{port}",
                                label="Сканер",
                                value=name,
                                alias_key=alias_key,
                                builtin_value=name,
                            ))

            info["scanners"] = scanners
            if fields:
                info["_fields"] = fields

        except Exception as e:
            info["scanner_error"] = str(e)
            logger.error(
                f"Failed to collect scanner info from {session.host}: {e}"
            )

        return info

    async def _collect_from_xml(self, session: CashSession) -> list[str]:
        """Read port values from barcodeScanner-serial-config.xml."""
        result = await session.ssh.execute(f"cat {XML_PATH}")
        if not result.success:
            logger.warning(
                f"Cannot read scanner XML on {session.host}: {result.stderr}"
            )
            return []

        ports = re.findall(
            r'<property\s+key\s*=\s*"port"\s+value\s*=\s*"([^"]*)"',
            result.stdout,
        )
        # Deduplicate preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for p in ports:
            if p and p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

    async def _collect_from_db(self, session: CashSession) -> list[str]:
        """Read scanner ports from hw_property table (sco3)."""
        import json as _json

        try:
            rows = await session.db.execute(_SCO3_QUERY)
        except Exception as e:
            logger.warning(
                f"DB scanner query failed on {session.host}: {e}"
            )
            return []

        parsed: dict[str, str] = {}
        for row in rows:
            key, json_str = row[0], row[1]
            try:
                data = _json.loads(json_str)
                port = data.get("port")
                if port:
                    parsed[key] = port
            except _json.JSONDecodeError:
                pass

        result: list[str] = []
        for key in ("Default", "Handle"):
            if key in parsed:
                result.append(parsed[key])
        return result
