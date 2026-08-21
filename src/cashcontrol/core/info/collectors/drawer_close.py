"""
Drawer close check collector — reads retailOnlyDrawerClose from Catalog DB via psql.

Collects data for all cash types; filtering by type is done in the rule.
Uses SSH to run psql on localhost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

PSQL_CMD = (
    "/usr/bin/psql -U postgres -h 127.0.0.1 -d catalog -t -A -c "
    '"SELECT property_value FROM sales_management_properties '
    "WHERE property_key = 'retailOnlyDrawerClose';\""
)


class DrawerCloseCollector:
    """Collects retailOnlyDrawerClose from Catalog database via psql."""

    async def collect(self, session: CashSession) -> dict[str, object]:
        info: dict[str, object] = {
            "drawer_close_raw": None,
            "drawer_close_error": None,
        }

        if not session.ssh_connected:
            info["drawer_close_error"] = "SSH не подключён"
            logger.warning(
                f"DrawerClose: SSH not connected for {session.host}"
            )
            return info

        try:
            result = await session.ssh.execute(PSQL_CMD)
            if result.stderr and "error" in result.stderr.lower():
                info["drawer_close_error"] = result.stderr.strip()[:200]
                logger.warning(
                    f"DrawerClose psql stderr on {session.host}: {result.stderr}"
                )
                return info
            raw = result.stdout.strip()
            if raw and "row" not in raw.lower():
                info["drawer_close_raw"] = raw
            else:
                info["drawer_close_error"] = "retailOnlyDrawerClose не найдена"
                logger.debug(
                    f"DrawerClose: key not found on {session.host}, "
                    f"stdout={result.stdout!r}, stderr={result.stderr!r}"
                )
        except Exception as e:
            info["drawer_close_error"] = str(e)
            logger.error(
                f"DrawerClose: exception on {session.host}: {e}"
            )

        return info