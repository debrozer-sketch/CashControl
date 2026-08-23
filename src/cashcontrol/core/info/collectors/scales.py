"""
Scales collector.

For pos/touch/sco — reads scales XML config files.
For sco3 — reads from PostgreSQL DB (hw_property table, module=HARDWARE_SCALES).

Applicable to: all cash types
"""

from __future__ import annotations

import contextlib
import json as _json
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

# Possible XML config paths for scales
_XML_PATHS = [
    "/home/tc/storage/crystal-cash/config/plugins/scales-shtrih-config.xml",
    "/home/tc/storage/crystal-cash/config/plugins/scales-massa-config.xml",
    "/home/tc/storage/crystal-cash/config/plugins/scales-config.xml",
]

# SCO3 DB query
_SCO3_QUERY = """
SELECT DISTINCT value
FROM public.hw_property
WHERE module = 'HARDWARE_SCALES' AND key LIKE 'scales_%';
"""


class ScalesCollector:
    """Collects scales (weighing scales) configuration."""

    async def collect(self, session: CashSession) -> dict[str, object]:
        """
        Collect scales info.

        Returns:
            Dict with:
                scales: list of dicts:
                    {
                        "name":      "Весы Штрих-Слим",
                        "port":      "/dev/usbSV1fc9P80a3",
                        "connected": True | False | None,
                    }
                scales_error: error message or None
        """
        info: dict[str, object] = {
            "scales": [],
            "scales_error": None,
        }

        mapping = load_usb_mapping("scale")

        try:
            if has_feature(session, "scales_from_db"):
                port_values = await self._collect_from_db(session)
            else:
                port_values = await self._collect_from_xml(session)

            from cashcontrol.core.info.info_manager import InfoField

            scales = []
            fields: list[InfoField] = []
            for port in port_values:
                name, device_info = lookup_device_by_path(port, mapping)
                connected = await check_usb_connected(session, device_info)
                scales.append(
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
                                key=f"scale_{port}",
                                label="Весы",
                                value=name,
                                alias_key=alias_key,
                                builtin_value=name,
                            ))

            info["scales"] = scales
            if fields:
                info["_fields"] = fields

        except Exception as e:
            info["scales_error"] = str(e)
            logger.error(
                f"Failed to collect scales info from {session.host}: {e}"
            )

        return info

    async def _collect_from_xml(self, session: CashSession) -> list[str]:
        """Try each known scales XML path and extract port values."""
        for xml_path in _XML_PATHS:
            result = await session.ssh.execute(f"cat {xml_path} 2>/dev/null")
            if not result.success or not result.stdout.strip():
                continue

            ports = re.findall(
                r'<property\s+key\s*=\s*"port"\s+value\s*=\s*"([^"]*)"',
                result.stdout,
            )
            if ports:
                seen: set[str] = set()
                unique: list[str] = []
                for p in ports:
                    if p and p not in seen:
                        seen.add(p)
                        unique.append(p)
                return unique

        return []

    async def _collect_from_db(self, session: CashSession) -> list[str]:
        """Read scales ports from hw_property table (sco3)."""
        task = getattr(session, "db_connect_task", None)
        if task is not None:
            with contextlib.suppress(Exception):
                await task
        try:
            rows = await session.db.execute(_SCO3_QUERY)
        except Exception as e:
            logger.warning(f"DB scales query failed on {session.host}: {e}")
            return []

        ports: set[str] = set()
        for row in rows:
            try:
                data = _json.loads(row[0])
                port = data.get("port")
                if port:
                    ports.add(port)
            except (_json.JSONDecodeError, TypeError, IndexError):
                pass

        return list(ports)
