"""
Connection collector — reports which SSH password successfully connected.

The value is local app state (not remote output): it lets declarative
rules warn about legacy/default passwords, e.g.:

    [[rule]]
    section = "connection"
    key = "ssh_password_used"
    op = "=="
    value = "324012"
    message = "Старый пароль!"

The section is intentionally never shown in the UI: no group mapping and
``_fields`` is cleared so the password cannot leak into the info display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession


class ConnectionCollector:
    """Collects local connection facts (not remote SSH output)."""

    async def collect(self, session: CashSession) -> dict[str, object]:
        ssh = getattr(session, "ssh", None)
        used = getattr(ssh, "successful_password", None) if ssh is not None else None
        return {
            "ssh_password_used": used if isinstance(used, str) else "",
            "_fields": [],
        }
