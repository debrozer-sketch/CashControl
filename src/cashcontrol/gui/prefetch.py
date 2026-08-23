"""Hover-prefetch: warm idempotent resources before the actual click.

Только безопасные операции без побочных эффектов: TCP-preconnect кассы.
Никаких команд, ребутов, обращений к БД по наведению.
"""

from __future__ import annotations

import asyncio
import time

from cashcontrol.infrastructure.audit_logger import get_logger

logger = get_logger()

_THROTTLE_S = 3.0


class Prefetcher:
    """Throttled fire-and-forget prefetch keyed by (kind, ip)."""

    def __init__(self) -> None:
        self._last: dict[tuple[str, str], float] = {}

    def schedule_tcp(self, ip: str | None, port: int = 22) -> None:
        if not ip:
            return
        key = ("tcp", ip)
        now = time.monotonic()
        if now - self._last.get(key, 0.0) < _THROTTLE_S:
            return
        self._last[key] = now
        asyncio.ensure_future(self._tcp(ip, port))

    async def _tcp(self, ip: str, port: int) -> None:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=1.0
            )
            writer.close()
            logger.debug(f"Prefetch TCP ok: {ip}:{port}")
        except Exception:
            logger.debug(f"Prefetch TCP miss: {ip}:{port}")


_prefetcher: Prefetcher | None = None


def get_prefetcher() -> Prefetcher:
    global _prefetcher
    if _prefetcher is None:
        _prefetcher = Prefetcher()
    return _prefetcher
