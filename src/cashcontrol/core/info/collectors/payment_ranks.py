"""
Payment type ranks collector — reads paymentTypeRanks from Catalog DB via psql.

Applicable to sco3 cash type. Uses SSH to run psql -d Catalog.
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
    "WHERE property_key = 'paymentTypeRanks';\""
)


class PaymentRanksCollector:
    """Collects paymentTypeRanks from Catalog database via psql."""

    async def collect(self, session: CashSession) -> dict[str, object]:
        info: dict[str, object] = {
            "payment_ranks_raw": None,
            "payment_ranks_error": None,
        }

        cash_type = getattr(session, "cash_type", None) or ""
        if cash_type != "sco3":
            info["payment_ranks_skipped"] = "1"
            return info

        if not session.ssh_connected:
            info["payment_ranks_error"] = "SSH не подключён"
            return info

        try:
            result = await session.ssh.execute(PSQL_CMD)
            raw = result.stdout.strip()
            if raw:
                info["payment_ranks_raw"] = raw
            else:
                info["payment_ranks_error"] = "paymentTypeRanks не найдена"
        except Exception as e:
            info["payment_ranks_error"] = str(e)
            logger.error(
                f"Failed to collect payment ranks from {session.host}: {e}"
            )

        return info