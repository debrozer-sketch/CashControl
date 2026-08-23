"""
SSH client — asynchronous SSH connections with automatic password iteration.

Features:
- Async SSH via asyncssh
- Automatic password iteration from config
- Command execution with timeout
- File transfer (SCP)
- Connection pooling and reuse
- Graceful disconnect

Usage:
    from cashcontrol.core.ssh import SSHSession

    session = SSHSession("192.168.1.100")

    async with session:
        result = await session.execute("uptime")
        print(result.stdout)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import asyncssh

from cashcontrol.core.security.password_manager import PasswordManager
from cashcontrol.infrastructure.audit_logger import audit_log, get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager
from cashcontrol.infrastructure.path_resolver import get_data_dir

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger()

SERVER_HOST_KEY_ALGS = [
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "rsa-sha2-512",
    "rsa-sha2-256",
    "ssh-rsa",
]


@dataclass
class CommandResult:
    """Result of SSH command execution."""

    stdout: str
    stderr: str
    exit_code: int
    success: bool

    @property
    def output(self) -> str:
        """Combined stdout and stderr."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)


class SSHConnectionError(Exception):
    """SSH connection failed."""

    pass


class SSHSession:
    """
    Asynchronous SSH session to a cash register.

    Manages connection lifecycle, automatic password iteration,
    command execution, and file transfers.
    """

    def __init__(
        self, host: str, port: int | None = None,
        config: ConfigManager | None = None,
    ) -> None:
        """
        Initialize SSH session.

        Args:
            host: Target hostname or IP
            port: SSH port (defaults to config value)
            config: Optional injected ConfigManager (DI)
        """
        self.host = host
        self._config = config or ConfigManager()
        self.port = port or self._config.settings.connection.ssh_port
        self.login = self._config.settings.connection.ssh_login
        self.timeout = self._config.settings.connection.timeout

        self._conn: asyncssh.SSHClientConnection | None = None
        self._password_manager = PasswordManager()
        self._successful_password: str | None = None
        # Лимит одновременных SSH-каналов — предотвращает ChannelOpenError
        self._channel_semaphore = asyncio.Semaphore(4)

    def _known_hosts_entry(self) -> tuple[Path, str]:
        kh_path = get_data_dir() / "known_hosts"
        host_expr = f"[{self.host}]:{self.port}" if self.port != 22 else self.host
        return kh_path, host_expr

    def _is_host_known(self) -> bool:
        """TOFU-проверка: есть ли запись для этого хоста в data/known_hosts."""
        kh_path, host_expr = self._known_hosts_entry()
        if not kh_path.exists():
            return False
        for line in kh_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts and parts[0] == host_expr:
                return True
        return False

    def _record_host_key(self) -> None:
        """Сохранить ключ сервера текущего соединения (Trust On First Use)."""
        assert self._conn is not None
        key = self._conn.get_server_host_key()
        if key is None:
            raise SSHConnectionError(
                f"Server did not present a host key ({self.host})"
            )
        kh_path, host_expr = self._known_hosts_entry()
        kh_path.parent.mkdir(parents=True, exist_ok=True)
        entry = f"{host_expr} {key.export_public_key().decode('ascii')}"
        with kh_path.open("a", encoding="utf-8") as f:
            f.write(entry + "\n")
        logger.info(f"Host key recorded for {self.host} (TOFU)")

    async def _dial(
        self, password: str, verify_host_key: bool
    ) -> asyncssh.SSHClientConnection:
        kwargs: dict = {
            "host": self.host,
            "port": self.port,
            "username": self.login,
            "password": password,
            "server_host_key_algs": SERVER_HOST_KEY_ALGS,
        }
        if verify_host_key:
            kwargs["known_hosts"] = str(self._known_hosts_entry()[0])
        else:
            kwargs["known_hosts"] = None
        return await asyncio.wait_for(asyncssh.connect(**kwargs), timeout=self.timeout)

    async def connect(self) -> None:
        """
        Establish SSH connection with automatic password iteration.

        Tries passwords from config in order. Caches successful password.

        Raises:
            SSHConnectionError: If connection fails with all passwords
        """
        if self._conn and not self._conn.is_closed():
            logger.debug(f"Already connected to {self.host}")
            return

        logger.info(f"Connecting to {self.host}:{self.port} as {self.login}")

        # Trust On First Use: при первом контакте ключ сервера записывается
        # в data/known_hosts, дальше соединение всегда с проверкой.
        first_contact = not self._is_host_known()
        verify_host_key = not first_contact

        # Try passwords in order
        last_error = None
        attempt = 0

        for password in self._password_manager.get_passwords_for_ip(self.host, "ssh"):
            attempt += 1
            try:
                logger.debug(f"SSH attempt {attempt} for {self.host}")

                conn = await self._dial(password, verify_host_key)

                if first_contact:
                    self._conn = conn
                    try:
                        self._record_host_key()
                    finally:
                        conn.close()
                        await conn.wait_closed()
                    logger.info(
                        f"First contact with {self.host}: host key recorded, "
                        "reconnecting with verification"
                    )
                    conn = await self._dial(password, verify_host_key=True)

                self._conn = conn

                # Success!
                self._successful_password = password
                self._password_manager.cache_success(self.host, password, "ssh")

                logger.info(f"SSH connected to {self.host} (attempt {attempt})")
                audit_log(
                    action_type="connection",
                    action_name="ssh_connect",
                    target=self.host,
                    result="success",
                    attempts=attempt,
                )
                return

            except (
                asyncssh.PermissionDenied,
                asyncssh.PasswordChangeRequired,
            ) as e:
                # Wrong password, try next
                logger.debug(f"SSH auth failed for {self.host}: {e}")
                last_error = e
                continue

            except asyncssh.HostKeyNotVerifiable as e:
                host_expr = self._known_hosts_entry()[1]
                msg = (
                    f"Host key verification failed for {host_expr}: ключ сервера "
                    "не совпадает с сохранённым в data/known_hosts. Возможна "
                    "подмена (MITM) либо устройство перешито. Проверьте ключ и "
                    "при подтверждении удалите строку хоста из known_hosts."
                )
                logger.error(msg)
                audit_log(
                    action_type="connection",
                    action_name="ssh_connect",
                    target=self.host,
                    result="failure",
                    error_message="host key mismatch (possible MITM)",
                )
                raise SSHConnectionError(msg) from e

            except TimeoutError as e:
                # Network timeout
                logger.warning(f"SSH timeout connecting to {self.host}")
                last_error = e
                break  # Don't try other passwords if we can't reach host

            except Exception as e:
                # Other errors (network, protocol, etc)
                logger.exception("SSH error connecting [host=%s]", self.host)
                last_error = e
                break

        # All passwords failed
        error_msg = f"SSH connection failed to {self.host}:{self.port}"
        if last_error:
            error_msg += f" - {last_error}"

        logger.error(error_msg)
        audit_log(
            action_type="connection",
            action_name="ssh_connect",
            target=self.host,
            result="failure",
            error_message=str(last_error),
            attempts=attempt,
        )

        raise SSHConnectionError(error_msg)

    async def disconnect(self) -> None:
        """Close SSH connection gracefully."""
        if self._conn and not self._conn.is_closed():
            logger.debug(f"Disconnecting from {self.host}")
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None
            logger.info(f"SSH disconnected from {self.host}")

    async def execute(
        self,
        command: str,
        timeout: int | None = None,
        check: bool = False,
    ) -> CommandResult:
        """
        Execute command on remote host.

        Args:
            command: Shell command to execute
            timeout: Command timeout in seconds (defaults to session timeout)
            check: If True, raise exception on non-zero exit code

        Returns:
            CommandResult with stdout, stderr, exit_code

        Raises:
            SSHConnectionError: If not connected
            asyncio.TimeoutError: If command times out
            RuntimeError: If check=True and exit code != 0

        Example:
            result = await session.execute("uptime")
            if result.success:
                print(result.stdout)
        """
        if not self._conn or self._conn.is_closed():
            raise SSHConnectionError(f"Not connected to {self.host}")

        timeout = timeout or self.timeout

        try:
            logger.debug(f"Executing on {self.host}: {command}")

            async with self._channel_semaphore:
                # Указываем encoding=None, чтобы получать сырые байты, а не падать на utf-8
                result = await asyncio.wait_for(
                    self._conn.run(command, check=False, encoding=None), timeout=timeout
                )

            # Вспомогательная функция для умного декодирования
            def _decode(data: bytes | str | None) -> str:
                if not data:
                    return ""
                if isinstance(data, str):
                    return data
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    # Если utf-8 не подошел, пробуем cp1251 (Windows-1251)
                    return data.decode("cp1251", errors="replace")

            stdout = _decode(result.stdout).strip()
            stderr = _decode(result.stderr).strip()
            exit_code = result.exit_status or 0

            cmd_result = CommandResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                success=(exit_code == 0),
            )

            if check and not cmd_result.success:
                raise RuntimeError(
                    f"Command failed with exit code {exit_code}: {stderr}"
                )

            logger.debug(
                f"Command completed on {self.host}: exit={exit_code}, "
                f"stdout={len(stdout)} bytes, stderr={len(stderr)} bytes"
            )

            return cmd_result

        except TimeoutError:
            logger.error(f"Command timeout on {self.host}: {command}")
            raise

        except Exception:
            logger.exception("Command execution error [host=%s]", self.host)
            raise

    async def upload_file(
        self, local_path: str, remote_path: str, preserve: bool = True
    ) -> None:
        """
        Upload file to remote host via SCP.

        Args:
            local_path: Local file path
            remote_path: Remote file path
            preserve: Preserve file attributes

        Raises:
            SSHConnectionError: If not connected
        """
        if not self._conn or self._conn.is_closed():
            raise SSHConnectionError(f"Not connected to {self.host}")

        try:
            logger.info(f"Uploading to {self.host}: {local_path} -> {remote_path}")

            await asyncssh.scp(
                local_path,
                (self._conn, remote_path),
                preserve=preserve,
            )

            logger.info(f"Upload completed to {self.host}: {remote_path}")

        except Exception:
            logger.exception("Upload failed [host=%s]", self.host)
            raise

    async def download_file(
        self, remote_path: str, local_path: str, preserve: bool = True
    ) -> None:
        """
        Download file from remote host via SCP.

        Args:
            remote_path: Remote file path
            local_path: Local file path
            preserve: Preserve file attributes

        Raises:
            SSHConnectionError: If not connected
        """
        if not self._conn or self._conn.is_closed():
            raise SSHConnectionError(f"Not connected to {self.host}")

        try:
            logger.info(f"Downloading from {self.host}: {remote_path} -> {local_path}")

            await asyncssh.scp(
                (self._conn, remote_path),
                local_path,
                preserve=preserve,
            )

            logger.info(f"Download completed from {self.host}: {local_path}")

        except Exception:
            logger.exception("Download failed [host=%s]", self.host)
            raise

    @property
    def is_connected(self) -> bool:
        """Check if session is connected."""
        return self._conn is not None and not self._conn.is_closed()

    # Context manager support
    async def __aenter__(self) -> SSHSession:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    def __repr__(self) -> str:
        status = "connected" if self.is_connected else "disconnected"
        return f"<SSHSession {self.login}@{self.host}:{self.port} [{status}]>"
