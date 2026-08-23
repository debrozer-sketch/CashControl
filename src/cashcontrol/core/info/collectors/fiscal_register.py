"""
Fiscal register (ФР) collector.

Reads /home/tc/storage/comproxy/ComProxy.ini, finds physical_port:
  /dev/ttyS0  → COM1
  /dev/ttyS1  → COM2
  /dev/usbPIRIT* → USB (PIRIT)
  /dev/usb*   → USB

All cash types: pos, touch, sco, sco3.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cashcontrol.core.cash_types import has_feature
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

INI_PATH = "/home/tc/storage/comproxy/ComProxy.ini"


def _port_to_human(raw: str) -> str:
    """Convert Linux device path to human-readable port name."""
    raw = raw.strip()
    if raw.startswith("/dev/ttyS"):
        try:
            n = int(raw.split("ttyS")[1])
            return f"COM{n + 1}"
        except (ValueError, IndexError):
            return raw
    if "usbPIRIT" in raw:
        return "USB (PIRIT)"
    if raw.startswith("/dev/usb"):
        return "USB"
    return raw


class FiscalRegisterCollector:
    """Collects fiscal register connection info from ComProxy.ini."""

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """
        Returns:
            {
                "fr_port":  Human-readable port, e.g. "COM2", "USB"
                "fr_raw":   Raw value from ini, e.g. "/dev/ttyS1"
                "fr_error": Error message if failed, else None
            }
        """
        info: dict[str, str | None] = {
            "fr_port":  None,
            "fr_raw":   None,
            "fr_error": None,
        }

        cash_type = (session.cash_type or "").lower()
        if cash_type and not has_feature(session, "fiscal_register"):
            return info

        try:
            result = await session.ssh.execute(f"cat {INI_PATH}")
            if not result.success:
                info["fr_error"] = f"Файл не найден: {result.stderr.strip()}"
                logger.warning(f"ComProxy.ini not found on {session.host}")
                return info

            match = re.search(
                r"^\s*physical_port\s*=\s*(.+)$",
                result.stdout,
                re.MULTILINE | re.IGNORECASE,
            )
            if match:
                raw = match.group(1).strip()
                info["fr_raw"]  = raw
                info["fr_port"] = _port_to_human(raw)
            else:
                info["fr_error"] = "Параметр physical_port не найден"

        except Exception as e:
            info["fr_error"] = str(e)
            logger.error(f"Failed to collect FR info from {session.host}: {e}")

        return info
