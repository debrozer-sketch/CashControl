"""
QRID collector (Gazprom SBP QR-link ID).

Reads bank-gazprom_sbp-config.xml and extracts cashLinkQrId property.

Applicable to: pos only
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

XML_PATH = (
    "/home/tc/storage/crystal-cash/config/plugins/"
    "bank-gazprom_sbp-config.xml"
)
XML_NS = {"ns": "http://crystals.ru/cash/settings"}

APPLICABLE_TYPES = {"pos"}


class QRIDCollector:
    """Collects Gazprom SBP cashLinkQrId from config XML."""

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """
        Collect QRID value.

        Returns:
            Dict with:
                qrid:         QRID string, e.g. "123456789"
                qrid_skipped: "1" if not applicable for this cash type
                qrid_error:   error message if failed
        """
        info: dict[str, str | None] = {
            "qrid": None,
            "qrid_skipped": None,
            "qrid_error": None,
        }

        cash_type = getattr(session, "cash_type", None) or ""
        if cash_type and cash_type not in APPLICABLE_TYPES:
            info["qrid_skipped"] = "1"
            return info

        try:
            result = await session.ssh.execute(f"cat {XML_PATH}")
            if not result.success:
                info["qrid_error"] = "Файл конфигурации не найден"
                return info

            try:
                root = ET.fromstring(result.stdout)

                # Try with namespace
                elem = root.find(
                    './/ns:property[@key="cashLinkQrId"]', XML_NS
                )

                # Fallback without namespace
                if elem is None:
                    for e in root.iter():
                        if e.get("key") == "cashLinkQrId":
                            elem = e
                            break

                if elem is not None:
                    qrid = elem.get("value", "").strip()
                    if qrid:
                        info["qrid"] = qrid
                    else:
                        info["qrid_error"] = "cashLinkQrId пустой"
                else:
                    info["qrid_error"] = "cashLinkQrId не найден"

            except ET.ParseError as e:
                info["qrid_error"] = f"Ошибка парсинга XML: {e}"

        except Exception as e:
            info["qrid_error"] = str(e)
            logger.error(
                f"Failed to collect QRID from {session.host}: {e}"
            )

        return info