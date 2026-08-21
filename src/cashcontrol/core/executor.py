from __future__ import annotations

import sys
from typing import Any

from cashcontrol.core.info import InfoCollector
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()


class Executor:
    def __init__(self) -> None:
        self._config = ConfigManager()

    def run(self) -> None:
        self._setup()
        shop_info = self._resolve_shop_info()
        has_touch = self._detect_touch_and_build_context()
        self._log_start(shop_info, has_touch)
        self._execute_steps()
        self._finalize()

    def _setup(self) -> None:
        pass

    def _resolve_shop_info(self) -> dict[str, Any]:
        return {}

    def _detect_touch_and_build_context(self) -> bool:
        return False

    def _log_start(self, shop_info: dict[str, Any], has_touch: bool) -> None:
        logger.info("Starting CashControl")

    def _execute_steps(self) -> None:
        pass

    def _finalize(self) -> None:
        pass


if __name__ == "__main__":
    Executor().run()
