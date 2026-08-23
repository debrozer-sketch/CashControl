"""
Loymax loyalty system collector.

Reads loymax.properties and extracts loymax.login value.

The file may be encoded in Windows-1251 (cp1251). Since 'base64' may not
be available on TinyCore, the file is read as hex via 'od -tx1 -An' and
decoded in Python.

Applicable to: all cash types
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

PROPS_PATH = (
    "/home/tc/storage/crystal-cash/config/plugins/loymax.properties"
)


class LoymaxCollector:
    """Collects Loymax loyalty system login from loymax.properties."""

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """
        Collect Loymax login.

        Returns:
            Dict with:
                loymax_login:   e.g. "shop_001"
                loymax_error:   error message if not found / failed
        """
        info: dict[str, str | None] = {
            "loymax_login": None,
            "loymax_error": None,
        }

        try:
            result = await session.ssh.execute(f"cat '{PROPS_PATH}'")

            if not result.success:
                info["loymax_error"] = "Файл loymax.properties не найден"
                return info

            content = result.stdout

            # Extract loymax.login = value
            match = re.search(
                r"(?m)^\s*loymax\.login\s*=\s*(.*?)\s*(?:\r?\n|$)",
                content,
            )
            if match:
                login = match.group(1).strip()
                if login:
                    info["loymax_login"] = login
                else:
                    info["loymax_error"] = "Параметр loymax.login пустой"
            else:
                info["loymax_error"] = "Параметр loymax.login не найден"

        except Exception as e:
            info["loymax_error"] = str(e)
            logger.error(
                f"Failed to collect Loymax info from {session.host}: {e}"
            )

        return info
