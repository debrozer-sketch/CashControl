"""
SetRetail software info collector.

Reads /home/tc/storage/crystal-cash/config/register-modules.xml
and extracts productVersion from the XML root element.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

XML_PATH = "/home/tc/storage/crystal-cash/config/register-modules.xml"


class CashSoftwareCollector:
    """Collects SetRetail software version information."""

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """
        Collect software version from register-modules.xml.

        Returns:
            Dict with:
                setretail_version: e.g. "10.8.166.1147"
                setretail_path:    base config path
        """
        info: dict[str, str | None] = {
            "setretail_version": None,
            "setretail_path": "/home/tc/storage/crystal-cash",
        }

        try:
            result = await session.ssh.execute(f"cat {XML_PATH}")
            if not result.success or not result.stdout.strip():
                logger.warning(f"Cannot read {XML_PATH} on {session.host}")
                return info

            try:
                root = ET.fromstring(result.stdout)
                version = root.get("productVersion")
                if version:
                    info["setretail_version"] = version.strip()
                    logger.debug(
                        f"SetRetail version on {session.host}: {version.strip()}"
                    )
                else:
                    logger.warning(
                        f"productVersion attribute not found in {XML_PATH} on {session.host}"
                    )
            except ET.ParseError as e:
                logger.warning(f"XML parse error reading software version: {e}")

        except Exception as e:
            logger.error(f"Failed to collect software info from {session.host}: {e}")

        return info
