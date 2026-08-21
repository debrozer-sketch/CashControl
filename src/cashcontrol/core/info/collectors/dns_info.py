"""DNS info collector — reads /etc/resolv.conf and extracts nameserver IPs."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()


class DNSInfoCollector:
    async def collect(self, session: CashSession) -> dict[str, object]:
        info: dict[str, object] = {"dns_servers": None}
        try:
            result = await session.ssh.execute("cat /etc/resolv.conf")
            if result.success:
                pattern = r"^\s*nameserver\s+((?:\d{1,3}\.){3}\d{1,3})\s*$"
                servers = re.findall(pattern, result.stdout, re.MULTILINE | re.IGNORECASE)
                info["dns_servers"] = servers if servers else None
        except Exception as e:
            logger.error(f"Failed to collect DNS info from {session.host}: {e}")
        return info