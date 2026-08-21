from __future__ import annotations

from typing import Any

import defusedxml.ElementTree as ET  # noqa: N817

from cashcontrol.core.info.info_manager import BaseCollector


class CashSoftwareCollector(BaseCollector):
    name = "software"

    async def collect(self, session) -> dict[str, Any]:
        data: dict[str, Any] = {}
        try:
            rc, stdout, _ = await session.run("ls /opt/cash/ 2>/dev/null || true")
            if rc == 0:
                data["packages"] = [s.strip() for s in stdout.splitlines() if s.strip()]
        except Exception:
            pass
        return data
