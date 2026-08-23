"""
Cash type collector — determines cash register type via the cash_types system.

Delegates to core.cash_types.TypeDetector (rules from detection/*.toml).
The type is stored in session.cash_type for use by other collectors
that need to filter by cash type.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from cashcontrol.core.cash_types import TypeDetector
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

XML_PATH = "/home/tc/storage/crystal-cash/config/register-modules.xml"


class CashTypeCollector:
    """
    Determines cash register type.

    Result is stored both in the returned dict and in session.cash_type
    so that subsequent collectors can access it without re-reading files.
    """

    def __init__(self) -> None:
        self._detector = TypeDetector()

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """
        Collect cash type information.

        Args:
            session: Connected CashSession

        Returns:
            Dict with:
                cash_type: canonical type id or "unknown"
                sw_version: productVersion attribute from the crystal XML (reuse the read)
                sw_path:    canonical software base path
        """
        info: dict[str, str | None] = {
            "cash_type": None,
            "sw_version": None,
            "sw_path": "/home/tc/storage/crystal-cash",
        }

        existing = getattr(session, "cash_type", None)
        manual = getattr(session, "cash_type_source", "") == "manual"
        if existing and existing != "unknown":
            info["cash_type"] = existing
            logger.debug(
                f"cash_type already set for {session.host}: {existing}"
                f" ({'manual' if manual else 'auto'})"
            )
            await self._fill_sw_version(session, info)
            return info

        cache: dict[str, str] = {}
        detected: str | None = None

        try:
            result = await session.ssh.execute(f"cat {XML_PATH}")
            if result.success and result.stdout.strip():
                cache[XML_PATH] = result.stdout
                self._extract_sw_version(result.stdout, info)
            else:
                logger.warning(
                    f"Cannot read {XML_PATH} on {session.host}: {result.stderr}"
                )

            detected = await self._detector.detect(session, cache=cache)
        except Exception as e:
            logger.error(f"Failed to detect cash type on {session.host}: {e}")

        info["cash_type"] = detected or "unknown"

        # Store in session for other collectors
        session.cash_type = info["cash_type"]
        session.cash_type_source = "auto" if detected else "unknown"

        logger.info(
            f"Cash type on {session.host}: {info['cash_type']} "
            f"(version: {info['sw_version']})"
        )
        return info

    def _extract_sw_version(self, xml_text: str, info: dict[str, str | None]) -> None:
        try:
            root = ET.fromstring(xml_text)
            pv = root.get("productVersion")
            if pv:
                info["sw_version"] = pv.strip()
        except ET.ParseError:
            pass

    async def _fill_sw_version(self, session: CashSession, info: dict[str, str | None]) -> None:
        try:
            result = await session.ssh.execute(f"cat {XML_PATH}")
            if result.success and result.stdout.strip():
                self._extract_sw_version(result.stdout, info)
        except Exception:
            pass
