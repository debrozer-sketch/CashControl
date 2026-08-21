"""CPU info collector — collects CPU information."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

class CPUInfoCollector:
    """Collects CPU information."""

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """Collect CPU info."""
        info = {"cpu_model": None, "cpu_cores": None}

        try:
            # CPU model
            result = await session.ssh.execute(
                "grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs"
            )
            if result.success:
                info["cpu_model"] = result.stdout.strip()

            # CPU cores
            result = await session.ssh.execute("nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo")
            if result.success and result.stdout.strip():
                info["cpu_cores"] = result.stdout.strip()

        except Exception as e:
            logger.error(f"Failed to collect CPU info from {session.host}: {e}")

        return info