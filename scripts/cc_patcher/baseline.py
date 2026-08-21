from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


DEV_BASELINE = Path("scripts") / ".dev-baseline.json"
RELEASE_BASELINE = Path("scripts") / ".release-baseline.json"


class BaselineManager:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict | None:
        if not self.path.is_file():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, version: str, files: dict[str, str]) -> None:
        data = {
            "version": version,
            "snapshot_at": datetime.now().isoformat(timespec="seconds"),
            "files": files,
        }
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
