from __future__ import annotations

import json
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_data_dir

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger()

_ALIASES_FILE = "aliases.json"
_VERSION = 1


class AliasManager:
    _instance: AliasManager | None = None

    @classmethod
    def instance(cls) -> AliasManager:
        if cls._instance is None:
            cls._instance = AliasManager()
        return cls._instance

    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}
        self._path: Path = get_data_dir() / _ALIASES_FILE
        self._load()

    def resolve(self, key: str, fallback: str = "") -> str:
        return self._aliases.get(key, fallback)

    def has_alias(self, key: str) -> bool:
        return key in self._aliases

    def set_alias(self, key: str, name: str) -> None:
        self._aliases[key] = name.strip()
        self._save()

    def delete_alias(self, key: str) -> None:
        if key in self._aliases:
            del self._aliases[key]
            self._save()

    def get_all(self) -> dict[str, str]:
        return dict(self._aliases)

    @staticmethod
    def usb_key(vid: str, pid: str) -> str:
        return f"usb:{vid.lower()}:{pid.lower()}"

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._aliases = data.get("aliases", {})
        except Exception:
            logger.exception(f"Failed to load aliases from {self._path}")

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"version": _VERSION, "aliases": self._aliases}
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save aliases")


def get_alias_manager() -> AliasManager:
    return AliasManager.instance()