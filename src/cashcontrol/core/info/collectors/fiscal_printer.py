"""
Fiscal printer (FR) collector.

Reads /home/tc/storage/comproxy/ComProxy.ini and extracts
the physical_port field to determine how the fiscal printer is connected.

Port mapping:
    /dev/ttyS0 → COM1
    /dev/ttyS1 → COM2
    /dev/usbPIRIT* → USB (PIRIT)
    /dev/usbS* → USB
    other → shown as-is

Applicable to: all cash types (pos, touch, sco, sco3)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

INI_PATH = "/home/tc/storage/comproxy/ComProxy.ini"


class FiscalPrinterCollector:
    """Collects fiscal printer connection info from ComProxy.ini."""

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """
        Collect fiscal printer info.

        Returns:
            Dict with:
                fr_port:        human-readable port, e.g. "COM2", "USB"
                fr_port_raw:    raw value from ini, e.g. "/dev/ttyS1"
                fr_error:       error message if failed, else None
        """
        info: dict[str, str | None] = {
            "fr_port": None,
            "fr_port_raw": None,
            "fr_error": None,
        }

        try:
            result = await session.ssh.execute(f"cat {INI_PATH}")
            if not result.success:
                info["fr_error"] = f"Файл не найден: {INI_PATH}"
                logger.warning(
                    f"Cannot read {INI_PATH} on {session.host}: {result.stderr}"
                )
                return info

            match = re.search(
                r"^\s*physical_port\s*=\s*(.+)$",
                result.stdout,
                re.MULTILINE | re.IGNORECASE,
            )
            if not match:
                info["fr_error"] = "Параметр physical_port не найден"
                return info

            raw = match.group(1).strip()
            info["fr_port_raw"] = raw

            # Determine friendly port name
            if raw.startswith("/dev/ttyS"):
                try:
                    num = int(raw.split("ttyS")[1])
                    info["fr_port"] = f"COM{num + 1}"
                except (ValueError, IndexError):
                    info["fr_port"] = raw
            elif "usbPIRIT" in raw:
                info["fr_port"] = "USB (PIRIT)"
            elif raw.startswith("/dev/usb") or raw.startswith("/dev/ttyUSB"):
                info["fr_port"] = "USB"
            else:
                info["fr_port"] = raw

            logger.debug(
                f"FR port on {session.host}: {info['fr_port']} (raw: {raw})"
            )

        except Exception as e:
            info["fr_error"] = str(e)
            logger.error(
                f"Failed to collect fiscal printer info from {session.host}: {e}"
            )

        return info