from __future__ import annotations

from typing import Any

import defusedxml.ElementTree as ET  # noqa: N814

from cashcontrol.core.info.info_manager import BaseCollector


class KeyboardCollector(BaseCollector):
    name = "keyboard"

    async def collect(self, session) -> dict[str, Any]:
        data: dict[str, Any] = {}
        try:
            rc, stdout, _ = await session.run("cat /proc/bus/input/devices 2>/dev/null || true")
            if rc == 0:
                if "AT Translated" in stdout:
                    data["keyboard_model"] = "ps2"
                elif "USB" in stdout and ("Keyboard" in stdout or "HID" in stdout):
                    for line in stdout.splitlines():
                        if "Keyboard" in line or "HID" in line:
                            data["keyboard_model"] = line.strip()
                            break
                if not data.get("keyboard_model"):
                    data["keyboard_model"] = "unknown"
        except Exception:
            pass
        return data
