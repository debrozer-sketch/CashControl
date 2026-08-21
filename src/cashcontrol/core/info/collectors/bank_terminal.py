"""
Bank terminal (payment terminal / pinpad) collector.

Reads pinpad.ini and extracts ComPort and optionally EnableUSB fields.

Port mapping:
    ComPort=1    → COM1
    ComPort=86   with EnableUSB=1 → USB (EnableUSB mode)

Applicable to: all cash types
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

# Possible base storage paths for different cash register setups
_BASE_PATHS = [
    "/home/tc/storage/crystal-cash",
    "/opt/tce/storage/crystal-cash",
]

_INI_RELATIVE = "banks/sberbank/linux/pinpad.ini"


class BankTerminalCollector:
    """Collects bank/payment terminal connection info from pinpad.ini."""

    async def _read_pinpad_ini(self, session: CashSession) -> str | None:
        for base in _BASE_PATHS:
            path = f"{base}/{_INI_RELATIVE}"
            result = await session.ssh.execute(f"cat {path}")
            if result.success and result.stdout.strip():
                return result.stdout
        return None

    @staticmethod
    def _parse_pinpad_ini(content: str) -> tuple[str | None, bool]:
        com_port: str | None = None
        enable_usb: bool = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip()
                if key == "ComPort":
                    com_port = value
                elif key == "EnableUSB" and value == "1":
                    enable_usb = True
        return com_port, enable_usb

    @staticmethod
    def _port_display_name(com_port: str, enable_usb: bool) -> str:
        if com_port == "86" and enable_usb:
            return "USB (EnableUSB)"
        try:
            return f"COM{int(com_port)}"
        except ValueError:
            return f"COM{com_port}"

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        info: dict[str, str | None] = {
            "bank_port": None,
            "bank_port_raw": None,
            "bank_usb_mode": None,
            "bank_error": None,
        }

        try:
            content = await self._read_pinpad_ini(session)
            if content is None:
                info["bank_error"] = "Файл pinpad.ini не найден"
                logger.warning(
                    f"Cannot read pinpad.ini on {session.host} "
                    f"(tried: {[f'{b}/{_INI_RELATIVE}' for b in _BASE_PATHS]})"
                )
                return info

            com_port, enable_usb = self._parse_pinpad_ini(content)
            if com_port is None:
                info["bank_error"] = "Параметр ComPort не найден в pinpad.ini"
                return info

            info["bank_port_raw"] = com_port
            info["bank_usb_mode"] = "1" if enable_usb else "0"
            info["bank_port"] = self._port_display_name(com_port, enable_usb)
            logger.debug(f"Bank terminal on {session.host}: {info['bank_port']}")

        except Exception as e:
            info["bank_error"] = str(e)
            logger.error(f"Failed to collect bank terminal info from {session.host}: {e}")

        return info