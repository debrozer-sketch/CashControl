"""
Keyboard collector.

Reads keyboard-config.xml and extracts the localizedName property
to identify the keyboard model.

Applicable to: pos only
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from cashcontrol.core.cash_types import has_feature
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

XML_PATH = (
    "/home/tc/storage/crystal-cash/config/modules/keyboard-config.xml"
)
XML_NS = {"ns": "http://crystals.ru/cash/settings"}



class KeyboardCollector:
    """Collects keyboard model from keyboard-config.xml."""

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """
        Collect keyboard model info.

        Returns:
            Dict with:
                keyboard_model:   e.g. "ШК2008-РФ"
                keyboard_skipped: "1" if not applicable
                keyboard_error:   error message if failed
        """
        info: dict[str, str | None] = {
            "keyboard_model": None,
            "keyboard_skipped": None,
            "keyboard_error": None,
        }

        cash_type = getattr(session, "cash_type", None) or ""
        if cash_type and not has_feature(session, "keyboard"):
            info["keyboard_skipped"] = "1"
            return info

        try:
            result = await session.ssh.execute(f"cat {XML_PATH}")
            if not result.success:
                info["keyboard_error"] = "Файл конфигурации не найден"
                return info

            try:
                root = ET.fromstring(result.stdout)

                # Try with namespace first
                model_elem = root.find(
                    ".//ns:property[@key='model']", XML_NS
                )
                name = None

                if model_elem is not None:
                    # localizedName nested inside model
                    ln = model_elem.find(
                        "./ns:property[@key='localizedName']", XML_NS
                    )
                    if ln is not None:
                        name = ln.get("value")

                if not name:
                    # Try direct search anywhere in tree
                    for elem in root.iter():
                        if elem.get("key") == "localizedName":
                            val = elem.get("value")
                            if val:
                                name = val
                                break

                if name:
                    info["keyboard_model"] = name.strip()
                else:
                    info["keyboard_error"] = "Модель клавиатуры не найдена"

            except ET.ParseError as e:
                info["keyboard_error"] = f"Ошибка парсинга XML: {e}"

        except Exception as e:
            info["keyboard_error"] = str(e)
            logger.error(
                f"Failed to collect keyboard info from {session.host}: {e}"
            )

        return info