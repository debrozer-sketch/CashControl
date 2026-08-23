"""SessionInterface — public session API (ADR-004).

The facade hides transports (SSH/DB/VNC) behind one interface so that
GUI code never imports ssh.py/db.py directly and tests can use mocks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class SessionInterface(ABC):
    """Unified device API over SSH/DB/VNC transports."""

    @abstractmethod
    async def connect(self) -> bool:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def ping(self) -> bool:
        """Lightweight liveness probe (no authentication)."""

    @abstractmethod
    async def exec(self, command: str, timeout: float = 30.0) -> ExecResult:
        ...

    @abstractmethod
    async def upload(self, local: Path | str, remote: str) -> bool:
        ...

    @abstractmethod
    async def download(self, remote: str, local: Path | str) -> bool:
        ...
