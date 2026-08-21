from __future__ import annotations

from typing import Any

import defusedxml.ElementTree as ET  # noqa: N817

from cashcontrol.core.info.info_manager import BaseCollector


class CashTypeCollector(BaseCollector):
    name = "cash_type"

    async def collect(self, session) -> dict[str, Any]:
        data: dict[str, Any] = {}
        try:
            rc, stdout, stderr = await session.run("cat /etc/cash.conf 2>/dev/null || true")
            if rc == 0 and stdout.strip():
                for line in stdout.splitlines():
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        data[k.strip()] = v.strip()
            if not data:
                rc2, out2, _ = await session.run("cat /etc/cash_type 2>/dev/null || echo unknown")
                data["cash_type"] = out2.strip()
        except Exception:
            data["cash_type"] = "unknown"
        return data
