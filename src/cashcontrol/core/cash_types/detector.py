"""TypeDetector — runs detection rules from detection/*.toml by priority."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

BUNDLED_DIR = Path(__file__).parent / "bundled_detection"


def _rule_priority(rule: dict[str, Any]) -> int:
    try:
        return -int(rule.get("priority", 0))
    except (TypeError, ValueError):
        return 0


class TypeDetector:
    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = []
        self.load_rules()

    def load_rules(self) -> None:
        from cashcontrol.infrastructure.path_resolver import get_detection_dir

        files: dict[str, dict] = {}
        for directory in (BUNDLED_DIR, get_detection_dir()):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.toml")):
                try:
                    with path.open("rb") as f:
                        files[path.stem] = tomllib.load(f)
                except Exception as e:
                    logger.error(f"Failed to parse detection file {path}: {e}")

        rules: list[dict[str, Any]] = []
        for data in files.values():
            rules.extend(data.get("rules") or [])
        rules.sort(key=_rule_priority)
        self._rules = rules

    def reload(self) -> None:
        self.load_rules()

    @property
    def rules(self) -> list[dict[str, Any]]:
        return list(self._rules)

    async def detect(
        self, session: CashSession, cache: dict[str, str] | None = None
    ) -> str | None:
        """Run rules in priority order; first hit wins. None -> unknown."""
        from cashcontrol.core.cash_types.strategies import STRATEGIES

        cache = cache if cache is not None else {}
        for rule in self._rules:
            strategy_name = rule.get("strategy")
            strategy = STRATEGIES.get(strategy_name)
            if strategy is None:
                logger.warning(f"Unknown detection strategy '{strategy_name}'")
                continue
            try:
                result = await strategy(rule, session, cache)
            except Exception as e:
                logger.error(f"Detection rule '{rule.get('id')}' failed: {e}")
                continue
            if result:
                return result
        return None
