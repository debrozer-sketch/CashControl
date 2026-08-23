from __future__ import annotations

import asyncio
import contextlib

from cashcontrol.core.db import DBSession
from cashcontrol.core.session_interface import ExecResult, SessionInterface
from cashcontrol.core.ssh import CommandResult, SSHConnectionError, SSHSession
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()


class CashSession(SessionInterface):
    """
    Connection session to a cash register.

    Manages the SSH connection (via :class:`SSHSession`) and the optional
    PostgreSQL connection (via :class:`DBSession`), exposing the simple
    interface consumed by the GUI and collectors.
    """

    def __init__(self, ip: str, config: ConfigManager | None = None) -> None:
        self._ip = ip
        self._config = config or ConfigManager()
        self._ssh = SSHSession(ip, config=self._config)
        self._db: DBSession | None = None
        self._is_connected = False
        self._db_connected = False
        self._error_message: str | None = None
        self.cash_type: str = "unknown"
        self.cash_type_source: str = "unknown"

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
    def ssh_connected(self) -> bool:
        """Alias for is_connected — original dataclass API."""
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
        except TimeoutError:
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
        result = await self.exec(command, timeout=timeout)
        return result.exit_code, result.stdout, result.stderr

    async def exec(self, command: str, timeout: float = 30.0) -> ExecResult:
        """Execute a shell command (SessionInterface)."""
        if not self._is_connected:
            return ExecResult(-1, "", "Not connected")
        try:
            result: CommandResult = await self._ssh.execute(command, timeout=int(timeout))
            return ExecResult(result.exit_code, result.stdout, result.stderr)
        except TimeoutError:
            return ExecResult(-1, "", "Command timed out")
        except Exception as e:
            return ExecResult(-1, "", str(e))

    async def ping(self, timeout: float = 1.5) -> bool:
        """TCP probe of the SSH port — no authentication involved."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self._ip, self._config.settings.connection.ssh_port
                ),
                timeout=timeout,
            )
            writer.close()
            return True
        except Exception:
            return False

    async def upload(self, local: object, remote: str) -> bool:
        try:
            await self._ssh.upload_file(str(local), remote)
            return True
        except Exception as e:
            logger.warning(f"Upload to {self._ip} failed: {e}")
            return False

    async def download(self, remote: str, local: object) -> bool:
        try:
            await self._ssh.download_file(remote, str(local))
            return True
        except Exception as e:
            logger.warning(f"Download from {self._ip} failed: {e}")
            return False

    async def reboot(self) -> bool:
        """Best-effort terminal reboot over SSH."""
        result = await self.exec("reboot -f || reboot", timeout=15.0)
        return result.ok

    # ── Context manager ──────────────────────────────────────────────────

    async def __aenter__(self) -> CashSession:
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        await self.disconnect()
