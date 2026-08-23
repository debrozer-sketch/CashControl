"""
PostgreSQL client — asynchronous database connections with automatic password iteration.

Features:
- Async DB via asyncpg
- Automatic password iteration from config
- Query execution with timeout
- Connection pooling
- Graceful disconnect

Usage:
    from cashcontrol.core.db import DBSession

    session = DBSession("192.168.1.100")

    async with session:
        rows = await session.execute("SELECT version()")
        print(rows[0])
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg

from cashcontrol.core.security.password_manager import PasswordManager
from cashcontrol.infrastructure.audit_logger import audit_log, get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()


class DBConnectionError(Exception):
    """Database connection failed."""

    pass


class DBSession:
    """
    Asynchronous PostgreSQL session to a cash register database.

    Manages connection lifecycle, automatic password iteration,
    and query execution.
    """

    def __init__(
        self,
        host: str,
        port: int | None = None,
        database: str | None = None,
        config: ConfigManager | None = None,
    ) -> None:
        """
        Initialize DB session.

        Args:
            host: Target hostname or IP
            port: PostgreSQL port (defaults to config value)
            database: Database name (defaults to config value)
            config: Optional injected ConfigManager (DI)
        """
        self.host = host
        self._config = config or ConfigManager()
        self.port = port or self._config.settings.connection.db_port
        self.login = self._config.settings.connection.db_login
        self.database = database  # must be passed explicitly; no global default
        self.timeout = self._config.settings.connection.timeout

        self._conn: asyncpg.Connection | None = None
        self._password_manager = PasswordManager()
        self._successful_password: str | None = None
        # asyncpg does not support concurrent queries on a single Connection
        self._lock: asyncio.Lock = asyncio.Lock()

    async def connect(self) -> None:
        """
        Establish PostgreSQL connection with automatic password iteration.

        Tries passwords from config in order. Caches successful password.

        Raises:
            DBConnectionError: If connection fails with all passwords
        """
        if self._conn and not self._conn.is_closed():
            logger.debug(f"Already connected to {self.host}:{self.port}/{self.database}")
            return

        logger.info(
            f"Connecting to PostgreSQL {self.host}:{self.port}/{self.database} as {self.login}"
        )

        # Try passwords in order
        last_error = None
        attempt = 0

        for password in self._password_manager.get_passwords_for_ip(self.host, "db"):
            attempt += 1
            try:
                logger.debug(f"DB attempt {attempt} for {self.host}")

                self._conn = await asyncio.wait_for(
                    asyncpg.connect(
                        host=self.host,
                        port=self.port,
                        user=self.login,
                        password=password,
                        database=self.database,
                        timeout=self.timeout,
                    ),
                    timeout=self.timeout,
                )

                # Success!
                self._successful_password = password
                self._password_manager.cache_success(self.host, password, "db")

                logger.info(f"DB connected to {self.host} (attempt {attempt})")
                audit_log(
                    action_type="connection",
                    action_name="db_connect",
                    target=f"{self.host}:{self.port}/{self.database}",
                    result="success",
                    attempts=attempt,
                )
                return

            except asyncpg.InvalidPasswordError as e:
                # Wrong password, try next
                logger.debug(f"DB auth failed for {self.host}: {e}")
                last_error = e
                continue

            except TimeoutError as e:
                # Network timeout
                logger.warning(f"DB timeout connecting to {self.host}")
                last_error = e
                break  # Don't try other passwords if we can't reach host

            except asyncpg.PostgresError as e:
                # Other DB errors (wrong database, network, etc)
                logger.exception("DB error connecting [host=%s]", self.host)
                last_error = e
                break

            except Exception as e:
                # Unexpected errors
                logger.exception("Unexpected DB error [host=%s]", self.host)
                last_error = e
                break

        # All passwords failed
        error_msg = f"DB connection failed to {self.host}:{self.port}/{self.database}"
        if last_error:
            error_msg += f" - {last_error}"

        logger.error(error_msg)
        audit_log(
            action_type="connection",
            action_name="db_connect",
            target=f"{self.host}:{self.port}/{self.database}",
            result="failure",
            error_message=str(last_error),
            attempts=attempt,
        )

        raise DBConnectionError(error_msg)

    async def disconnect(self) -> None:
        """Close database connection gracefully."""
        if self._conn and not self._conn.is_closed():
            logger.debug(f"Disconnecting from DB {self.host}")
            await self._conn.close()
            self._conn = None
            logger.info(f"DB disconnected from {self.host}")

    # ── Internal query helper ───────────────────────────────────────────

    async def _execute(
        self,
        fetch_method: str,
        query: str,
        args: tuple[Any, ...],
        timeout: int | None = None,
        use_lock: bool = False,
    ) -> Any:
        """Shared query logic — connection check, timeout, error handling.

        Args:
            fetch_method: Name of asyncpg method ('fetch', 'fetchrow', 'fetchval').
            query: SQL query string.
            args: Query parameters.
            timeout: Query timeout in seconds.
            use_lock: Acquire the per-connection lock (for multi-row fetch).

        Returns:
            Raw result from asyncpg (list, row, or value).

        Raises:
            DBConnectionError: If not connected.
            asyncpg.PostgresError, TimeoutError: Propagated from asyncpg.
        """
        if not self._conn or self._conn.is_closed():
            msg = f"Not connected to {self.host}"
            raise DBConnectionError(msg)

        timeout = timeout or self.timeout

        async def _run() -> Any:
            method = getattr(self._conn, fetch_method)
            logger.debug(f"Executing query on {self.host}: {query[:100]}...")
            result = await asyncio.wait_for(method(query, *args), timeout=timeout)
            return result

        try:
            if use_lock:
                async with self._lock:
                    result = await _run()
            else:
                result = await _run()

            if fetch_method == "fetch":
                logger.debug(f"Query completed on {self.host}: {len(result)} rows")
            return result

        except TimeoutError:
            logger.error(f"Query timeout on {self.host}: {query[:100]}")
            raise

        except asyncpg.PostgresError:
            logger.exception("Query error [host=%s]", self.host)
            raise

        except Exception:
            logger.exception("Unexpected query error [host=%s]", self.host)
            raise

    # ── Public query methods ────────────────────────────────────────────

    async def execute(self, query: str, *args: Any, timeout: int | None = None) -> list[Any]:
        """Execute SQL query and return all rows.

        See _execute docstring for full parameter documentation.
        """
        result = await self._execute("fetch", query, args, timeout, use_lock=True)
        return result

    @property
    def is_connected(self) -> bool:
        """Check if session is connected."""
        return self._conn is not None and not self._conn.is_closed()

    # Context manager support
    async def __aenter__(self) -> DBSession:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    def __repr__(self) -> str:
        status = "connected" if self.is_connected else "disconnected"
        return (
            f"<DBSession {self.login}@{self.host}:{self.port}/{self.database} "
            f"[{status}]>"
        )
