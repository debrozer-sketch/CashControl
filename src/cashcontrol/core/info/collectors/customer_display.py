"""
Customer display collector.

Reads customerDisplay-firich-config.xml and extracts the 'port' property
to determine how the customer display is connected.

Port mapping:
    /dev/usbSV*  → USB (Штрих-Т USB)
    /dev/ttyS1   → COM2 (Штрих-Т COM2)

Applicable to: pos only
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

XML_PATH = (
    "/home/tc/storage/crystal-cash/config/plugins/"
    "customerDisplay-firich-config.xml"
)

APPLICABLE_TYPES = {"pos"}


class CustomerDisplayCollector:
    """Collects customer display connection info."""

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """
        Collect customer display info.

        Skipped (returns skipped=True) for non-POS cash types.

        Returns:
            Dict with:
                display_port:   human-readable, e.g. "USB" or "COM2"
                display_port_raw: raw path from XML
                display_skipped: "1" if not applicable for this cash type
                display_error:  error message if failed
        """
        info: dict[str, str | None] = {
            "display_port": None,
            "display_port_raw": None,
            "display_skipped": None,
            "display_error": None,
        }

        # Skip for non-POS types
        cash_type = getattr(session, "cash_type", None) or ""
        if cash_type and cash_type not in APPLICABLE_TYPES:
            info["display_skipped"] = "1"
            return info

        try:
            result = await session.ssh.execute(f"cat {XML_PATH}")
            if not result.success:
                info["display_error"] = "Файл конфигурации не найден"
                return info

            # Find port property via regex (more robust than full XML parse)
            match = re.search(
                r'<property\s+key\s*=\s*"port"\s+value\s*=\s*"([^"]*)"',
                result.stdout,
            )
            if not match:
                info["display_error"] = "Параметр port не найден"
                return info

            raw = match.group(1).strip()
            info["display_port_raw"] = raw

            if raw.startswith("/dev/usbS") or "/usb" in raw.lower():
                info["display_port"] = "USB (Штрих-Т)"
            elif raw.startswith("/dev/ttyS"):
                try:
                    num = int(raw.split("ttyS")[1])
                    info["display_port"] = f"COM{num + 1} (Штрих-Т)"
                except (ValueError, IndexError):
                    info["display_port"] = f"Штрих-Т ({raw})"
            else:
                info["display_port"] = raw

            logger.debug(
                f"Customer display on {session.host}: {info['display_port']}"
            )

        except Exception as e:
            info["display_error"] = str(e)
            logger.error(
                f"Failed to collect display info from {session.host}: {e}"
            )

        return info