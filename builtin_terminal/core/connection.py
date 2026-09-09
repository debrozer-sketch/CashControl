"""SSH-соединение: asyncssh-клиент, TOFU known_hosts, keepalive, реконнект."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import asyncssh

_LOG = logging.getLogger("ssh_term.core.connection")

_SERVER_HOST_KEY_ALGS = (
    "ssh-ed25519-cert-v01@openssh.com",
    "ecdsa-sha2-nistp521-cert-v01@openssh.com",
    "ecdsa-sha2-nistp384-cert-v01@openssh.com",
    "ecdsa-sha2-nistp256-cert-v01@openssh.com",
    "ssh-ed25519",
    "ecdsa-sha2-nistp521",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp256",
    "ssh-rsa",
    "rsa-sha2-512",
    "rsa-sha2-256",
)


class _TofuSSHClient(asyncssh.SSHClient):
    """Клиент с TOFU-валидацией host key: новый ключ принимает и записывает."""

    def __init__(self, owner: "SSHConnection") -> None:
        self._owner = owner

    def validate_host_public_key(self, host: str, addr: str,
                                 port: int, key: asyncssh.SSHKey) -> bool:
        return self._owner._trust_new_host_key(host, addr, port, key)


class SSHConnection:
    """Одно SSH-соединение к хосту. Ядро: без Qt, без цикла создания."""

    def __init__(
        self,
        host: str,
        username: str,
        port: int = 22,
        password: Optional[str] = None,
        client_keys: Optional[list[str]] = None,
        known_hosts_path: Optional[Path] = None,
        connect_timeout: float = 15.0,
        keepalive_interval: float = 15.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self._client_keys = list(client_keys or [])
        self._known_hosts_path = known_hosts_path
        self._connect_timeout = connect_timeout
        self._keepalive_interval = keepalive_interval

        self._conn: Optional[asyncssh.SSHClientConnection] = None
        self._lock = asyncio.Lock()
        self._closed = False

        # заполняется после успешного коннекта
        self.successful_password: Optional[str] = None

    # ---- properties ----

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.is_closed()

    # ---- public API ----

    async def connect(self) -> None:
        """Подключение (или реконнект). Бросает исключение при неудаче."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("connection closed for good")
            if self.is_connected:
                return
            self._conn = await self._connect_inner()

    async def close(self) -> None:
        """Закрыть навсегда (в отличие от disconnect — реконнект запрещён)."""
        self._closed = True
        conn, self._conn = self._conn, None
        if conn is not None:
            conn.close()
            try:
                await asyncio.wait_for(conn.wait_closed(), timeout=5.0)
            except (asyncio.TimeoutError, OSError):
                pass

    async def acquire(self) -> asyncssh.SSHClientConnection:
        """Получить живое соединение (реконнект, если умерло)."""
        if not self.is_connected:
            await self.connect()
        assert self._conn is not None
        return self._conn

    # ---- internals ----

    async def _connect_inner(self) -> asyncssh.SSHClientConnection:
        # TOFU: сверку делает ТОЛЬКО _TofuSSHClient.validate_host_public_key ->
        # _trust_new_host_key (известный ключ из файла принимаем, новый — дописываем,
        # изменившийся — отвергаем). known_hosts в asyncssh не передаём: пустой
        # b"" исключает и его встроенный матчер, и фолбэк на ~/.ssh/known_hosts,
        # иначе при появлении файла поведение незаметно разделилось бы на два
        # конкурирующих механизма.
        kwargs: dict[str, object] = {
            "known_hosts": b"",
            "connect_timeout": int(self._connect_timeout),
            "keepalive_interval": int(self._keepalive_interval),
            "keepalive_count_max": 3,
            "server_host_key_algs": list(_SERVER_HOST_KEY_ALGS),
            "agent_path": None,  # в прототипе явно отключаем agent, только пароль/ключ
            "username": self.username,
            "client_factory": lambda: _TofuSSHClient(self),  # type: ignore[dict-item]
        }
        if self._password:
            kwargs["password"] = self._password
            kwargs["preferred_auth"] = "password,keyboard-interactive"
            self.successful_password = self._password
        if self._client_keys:
            kwargs["client_keys"] = self._client_keys

        last_error: Optional[Exception] = None
        loop = asyncio.get_running_loop()
        for attempt in range(1, 3):
            t0 = loop.time()
            try:
                conn = await asyncssh.connect(self.host, self.port, **kwargs)
                _LOG.info(
                    "connected to %s:%s in %.2fs (attempt %s)",
                    self.host, self.port, loop.time() - t0, attempt,
                )
                return conn
            except asyncssh.HostKeyNotVerifiable:
                raise  # ключ изменился и не принят — ошибка безопасности, без ретрая
            except (OSError, asyncssh.Error, ValueError) as exc:
                last_error = exc
                _LOG.warning(
                    "connect attempt %s to %s:%s failed after %.2fs: %s",
                    attempt, self.host, self.port, loop.time() - t0, exc,
                )
                if attempt < 2:
                    await asyncio.sleep(1.5 * attempt)

        raise ConnectionError(f"cannot connect to {self.host}:{self.port}: {last_error}") from last_error

    def _trust_new_host_key(self, host: str, addr: str, port: int,
                            server_host_key: "asyncssh.SSHKey") -> bool:
        """TOFU: сверяет host key с нашим known_hosts-файлом.

        Вызывается кастомным SSHClient на каждый коннект (asyncssh known_hosts
        не используется, см. _connect_inner). Итог: известный ключ — принимаем,
        новый — дописываем в файл, изменившийся для того же host:port — отвергаем.
        """
        path = self._known_hosts_path
        if path is None:
            return bool(addr)  # без хранилища доверяем всем (прототип)
        entry = f"[{addr or host}]:{port} {server_host_key.export_public_key('openssh')}\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            data = path.read_text(encoding="utf-8")
            if entry in data:
                return True
            prefix = f"[{addr or host}]:{port} "
            if any(line.startswith(prefix) for line in data.splitlines() if line.strip()):
                # ключ изменился — отказ (классический TOFU-mismatch)
                _LOG.warning("TOFU mismatch for %s:%s — rejecting", addr or host, port)
                return False
            path.write_text(data + entry, encoding="utf-8")
        else:
            path.write_text(entry, encoding="utf-8")
        _LOG.info("TOFU: trusted new host key for %s:%s", addr or host, port)
        return True

    # ---- context manager ----

    async def __aenter__(self) -> "SSHConnection":
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
