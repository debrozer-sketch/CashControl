from __future__ import annotations

from typing import Any

import defusedxml.ElementTree as ET  # noqa: N814

from cashcontrol.core.info.info_manager import BaseCollector


class QridCollector(BaseCollector):
    name = "qrid"

    async def collect(self, session) -> dict[str, Any]:
        data: dict[str, Any] = {}
        try:
            rc, stdout, _ = await session.run("cat /opt/cash/qrid 2>/dev/null || true")
            if rc == 0 and stdout.strip():
                data["qrid"] = stdout.strip()
        except Exception:
            pass
        return data
