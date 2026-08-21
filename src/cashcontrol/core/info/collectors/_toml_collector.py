"""
Universal collector based on TOML description.

Executes SSH commands and returns a data dict compatible with InfoCollector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from cashcontrol.core.session import CashSession

from cashcontrol.infrastructure.audit_logger import get_logger

logger = get_logger()


class TomlCollector:
    """Collector loaded from a TOML file. Executes shell commands via SSH."""

    def __init__(self, toml_path: Path) -> None:
        import tomllib
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        meta = data["collector"]
        self.name: str = meta["name"]
        self.label: str = meta["label"]
        self.group: str = meta.get("group", "other")
        self.icon: str = meta.get("icon", "")
        self.cash_types: list[str] = meta.get("cash_types", [])
        self.order: int = meta.get("order", 99)
        self.fields: list[dict[str, Any]] = data.get("fields", [])
        self._fallbacks: dict[str, str] = {
            f["key"]: f.get("fallback", "\u2014") for f in self.fields
        }

    async def collect(self, session: CashSession) -> dict[str, str]:
        """
        Execute all field commands and return a data dict.

        Each field key maps to the command output (or fallback on error).
        """
        result: dict[str, str] = {}
        for field in self.fields:
            key = field["key"]
            command = field["command"]
            fallback = field.get("fallback", "\u2014")
            try:
                r = await session.ssh.execute(command, timeout=10)
                value = r.stdout.strip() if r.stdout and r.stdout.strip() else fallback
            except Exception:
                value = fallback
            result[key] = value
        return result

    def __repr__(self) -> str:
        return f"<TomlCollector name={self.name!r} fields={len(self.fields)}>"