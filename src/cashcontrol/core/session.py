from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from cashcontrol.core.db import DBSession
from cashcontrol.core.ssh import CommandResult, SSHConnectionError, SSHSession
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()


class CashSession:
    """
    Connection session to a cash register.

    Manages the SSH connection (via :class:`SSHSession`) and the optional
    PostgreSQL connection (via :class:`DBSession`), exposing the simple
    interface consumed by the GUI and collectors.
    """

    def __init__(self, ip: str) -> None:
        self._ip = ip
        self._config = ConfigManager()
        self._ssh = SSHSession(ip)
        self._db: DBSession | None = None
        self._is_connected = False
        self._db_connected = False
        self._error_message: str | None = None

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def host(self) -> str:
        """Alias for ip — original API used by collectors and tools."""
        return self._ip

    @property
    def ssh(self) -> SSHSession:
        return self._ssh

    @property
    def db(self) -> DBSession | None:
        return self._db

    @db.setter
    def db(self, value: DBSession | None) -> None:
        self._db = value

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def db_connected(self) -> bool:
        return self._db_connected

    @db_connected.setter
    def db_connected(self, value: bool) -> None:
        self._db_connected = value

    @property
    def error_message(self) -> str | None:
        return self._error_message

    # ── Connect / disconnect ─────────────────────────────────────────────

    async def connect(self, connect_db: bool = False) -> bool:
        """Establish the SSH connection. Returns True on success."""
        timeout = self._config.settings.connection.connect_timeout
        try:
            await asyncio.wait_for(self._ssh.connect(), timeout=timeout)
        except asyncio.TimeoutError:
            self._error_message = f"SSH timeout connecting to {self._ip}"
            logger.warning(f"SSH timeout connecting to {self._ip}")
            return False
        except (OSError, SSHConnectionError) as e:
            self._error_message = str(e)
            logger.debug(f"SSH connect failed for {self._ip}: {e}")
            return False
        self._is_connected = True
        logger.info(f"SSH connected to {self._ip}")
        if connect_db:
            self.setup_db(database="sco_v3")
            await self.connect_db()
        return True

    def setup_db(self, database: str) -> None:
        """Create the DB session object (does not connect yet)."""
        conn = self._config.settings.connection
        self._db = DBSession(self._ip, port=conn.db_port, database=database)

    async def connect_db(self) -> bool:
        """Connect the previously configured DB session."""
        if not self._db:
            self._error_message = "DB session is not configured"
            return False
        try:
            await self._db.connect()
            self._db_connected = True
            return True
        except Exception as e:
            self._error_message = str(e)
            logger.debug(f"DB connect failed for {self._ip}: {e}")
            return False

    async def disconnect(self) -> None:
        if self._ssh:
            await self._ssh.disconnect()
            self._is_connected = False
        if self._db:
            with contextlib.suppress(Exception):
                await self._db.disconnect()
            self._db = None
            self._db_connected = False

    async def abort(self) -> None:
        """Hard-abort underlying connections (used on IP change)."""
        conn = getattr(self._ssh, "_conn", None)
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.abort()
            self._ssh._conn = None
        self._is_connected = False

    # ── Commands ─────────────────────────────────────────────────────────

    async def run(self, command: str, timeout: float = 30.0) -> tuple[int, str, str]:
        """Execute a shell command; returns (exit_code, stdout, stderr)."""
        if not self._is_connected:
            return -1, "", "Not connected"
        try:
            result: CommandResult = await self._ssh.execute(command, timeout=int(timeout))
            return result.exit_code, result.stdout, result.stderr
        except asyncio.TimeoutError:
            return -1, "", "Command timed out"
        except SSHConnectionError as e:
            return -1, "", str(e)
        except Exception as e:
            return -1, "", str(e)

    async def upload(self, local: Any, remote: str) -> bool:
        try:
            await self._ssh.upload_file(local, remote)
            return True
        except Exception as e:
            logger.error(f"Upload failed for {self._ip}: {e}")
            return False

    async def download(self, remote: str, local: Any) -> bool:
        try:
            await self._ssh.download_file(remote, local)
            return True
        except Exception as e:
            logger.error(f"Download failed for {self._ip}: {e}")
            return False

    # ── Context manager ──────────────────────────────────────────────────

    async def __aenter__(self) -> CashSession:
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        await self.disconnect()
