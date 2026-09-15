"""asyncssh-based transport helpers: TOFU connection, shell runner, SCP provider."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import logging
import os
import re
import secrets
import stat as _stat
import tempfile
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import asyncssh

from cashcontrol.builtin.file_manager.models import (
    FileKind,
    HostKeyMismatchError,
    RemoteAuthError,
    RemoteConnectionError,
    RemoteFileInfo,
    RemoteFilesError,
    RemoteNotFoundError,
    RemotePermissionError,
    ShellResult,
    TransferOptions,
    UnsupportedByBackendError,
    basename_remote,
    escape_sh,
    join_remote,
    parent_remote,
)

if TYPE_CHECKING:
    from cashcontrol.builtin.file_manager.models import (
        ProgressCallback,
        ScpTransferProvider,
        ShellRunner,
    )

logger = logging.getLogger("cashcontrol.builtin.file_manager.backends")

# Order matters: ed25519 first, then ecdsa, then RSA (with the modern
# SHA-2 variants before the legacy ssh-rsa for older TinyCore sshd).
SERVER_KEY_ALGS = ("ssh-ed25519", "ecdsa-sha2-nistp256", "rsa-sha2-512", "rsa-sha2-256", "ssh-rsa")

# How long to wait for the SFTP subsystem handshake before falling back to SCP.
SFTP_SUBSYSTEM_TIMEOUT = 10.0


def default_config_dir() -> Path:
    """Global config directory (overridable via ``RFILES_CONFIG_DIR``)."""
    config_dir = os.environ.get("RFILES_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).expanduser()
    return Path.home() / ".config" / "remote-files"


def host_expr(host: str, port: int) -> str:
    """known_hosts host expression (bracketed when a non-default port is used)."""
    if port == 22:
        return host
    return f"[{host}]:{port}"


class HostKeyStore:
    """TOFU host key store; matches OpenSSH ``known_hosts`` line format.

    Lines are ``<host_expr> <key_type> <base64>`` so the file stays human
    readable and interchangeable with OpenSSH tooling where possible.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_config_dir() / "known_hosts"

    def host_expr(self, host: str, port: int) -> str:
        return host_expr(host, port)

    def is_known(self, host: str, port: int) -> bool:
        """Return True when the host expression already has at least one key."""
        expr = self.host_expr(host, port)
        if not self.path.is_file():
            return False
        for line in self.path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts and parts[0] == expr:
                return True
        return False

    def record(self, host: str, port: int, exported_public_key: bytes) -> None:
        """Append a public key for the given host (mismatched keys are not replaced)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        expr = self.host_expr(host, port)
        text = exported_public_key.decode("ascii")
        line = f"{expr} {text}\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"HostKeyStore({str(self.path)!r})"


def default_known_hosts_path() -> Path:
    return default_config_dir() / "known_hosts"


def build_connect_kwargs(
    *,
    host: str,
    port: int,
    username: str,
    password: str | None,
    key_file: str | None,
    timeout: float,
    known_hosts: str | Path | None,
) -> dict[str, Any]:
    """Build asyncssh.connect() keyword arguments from plain parameters."""
    if not password and not key_file:
        raise RemoteAuthError("Для аутентификации нужен пароль или файл ключа")
    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "username": username,
        "server_host_key_algs": SERVER_KEY_ALGS,
        "known_hosts": str(known_hosts) if known_hosts is not None else None,
        "connect_timeout": timeout,
    }
    if password:
        kwargs["password"] = password
    if key_file:
        kwargs["client_keys"] = [str(Path(key_file).expanduser())]
    return kwargs


def translate_connect_error(exc: BaseException) -> RemoteFilesError:
    """Map an asyncssh connection failure onto a typed Remote Files error."""
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        return HostKeyMismatchError(
            "Ключ хоста не совпадает с сохранённым; проверьте идентификацию сервера"
        )
    if isinstance(exc, asyncssh.PermissionDenied):
        return RemoteAuthError(f"Не удалось пройти аутентификацию: {exc}")
    if isinstance(exc, (TimeoutError, OSError, asyncssh.Error)):
        return RemoteConnectionError(str(exc))
    return RemoteFilesError(str(exc))


async def connect_with_tofu(
    *,
    host: str,
    port: int = 22,
    username: str = "root",
    password: str | None = None,
    key_file: str | None = None,
    known_hosts: str | Path | None = None,
    timeout: float = 15.0,
    hostkey_store: HostKeyStore | None = None,
) -> asyncssh.SSHClientConnection:
    """Connect with first-contact host key recording; then reconnect verifying.

    On every new host the key is recorded into the store and the session is
    re-established with verification enabled (trust-on-first-use).
    """
    store = hostkey_store if hostkey_store is not None else HostKeyStore(known_hosts)
    first_contact = not store.is_known(host, port)
    logger.info(
        "Подключение: host=%s port=%d user=%s timeout=%s known_hosts=%s (первый контакт: %s)",
        host,
        port,
        username,
        timeout,
        store.path,
        first_contact,
    )

    if first_contact:
        logger.info("Записываем идентификацию хоста (TOFU) перед повторным подключением…")
        first_kwargs = build_connect_kwargs(
            host=host,
            port=port,
            username=username,
            password=password,
            key_file=key_file,
            timeout=timeout,
            known_hosts=None,
        )
        try:
            probe = await asyncssh.connect(**first_kwargs)
        except (TimeoutError, OSError, asyncssh.Error) as exc:
            logger.warning("Пробное подключение не удалось: %s", exc, exc_info=True)
            raise translate_connect_error(exc) from exc
        try:
            key = probe.get_server_host_key().export_public_key()
            fingerprint = hashlib.sha256(key).hexdigest()[:16]
            store.record(host, port, key)
            logger.info("Ключ хоста сохранили в %s (sha256:%s…)", store.path, fingerprint)
        finally:
            probe.close()
            await probe.wait_closed()

    kwargs = build_connect_kwargs(
        host=host,
        port=port,
        username=username,
        password=password,
        key_file=key_file,
        timeout=timeout,
        known_hosts=store.path,
    )
    logger.info("Повторное подключение с проверкой ключа по %s…", store.path)
    try:
        conn = await asyncssh.connect(**kwargs)
    except (TimeoutError, OSError, asyncssh.Error) as exc:
        logger.warning("Подключение не удалось: %s", exc, exc_info=True)
        raise translate_connect_error(exc) from exc
    logger.info("SSH-соединение установлено: host=%s port=%d", host, port)
    return conn


class SSHShellRunner:
    """Runs shell primitives over a *single persistent interactive shell*.

    asyncssh.spawns a fresh exec channel per ``conn.run()``. Some servers
    (TinyCore/dropbear) stop acknowledging channel opens after a few requests,
    which would hang ``conn.run()`` forever. Using one long-lived interactive
    shell channel sidesteps that and makes browsing on such hosts reliable.
    Each command is framed with a random marker line, so output boundaries and
    exit codes are always recoverable.
    """

    def __init__(self, conn: asyncssh.SSHClientConnection, timeout: float | None = None) -> None:
        self._conn = conn
        self.timeout = timeout if timeout is not None else 15.0
        self._lock = asyncio.Lock()
        self._process: asyncssh.SSHClientProcess | None = None
        self._seq = 0

    async def _ensure_process(self, effective: float) -> asyncssh.SSHClientProcess:
        proc = self._process
        alive = (
            proc is not None
            and not self._conn.is_closed()
            and not proc.stdout.at_eof()
        )
        if alive:
            return proc  # type: ignore[return-value]
        if proc is not None:
            with suppress(OSError, asyncssh.Error):
                proc.close()
            self._process = None
        try:
            opened = await asyncio.wait_for(
                self._conn.create_process(encoding=None), timeout=effective
            )
        except TimeoutError as exc:
            await self._force_close()
            raise RemoteFilesError(
                "Не удалось открыть интерактивный shell на сервере (таймаут)"
            ) from exc
        except (OSError, asyncssh.Error) as exc:
            raise RemoteFilesError(f"Не удалось открыть интерактивный shell: {exc}") from exc
        self._process = opened
        return opened

    async def run(self, command: str, timeout: float | None = None) -> ShellResult:
        effective = timeout if timeout is not None else self.timeout
        async with self._lock:
            proc = await self._ensure_process(effective)
            seq = self._seq
            self._seq += 1
            token = f"RF{seq}_{secrets.token_hex(4)}"
            start = time.monotonic()
            logger.info("Выполняем: %s", command)
            try:
                frame = f"{{ {command}; }} 2>&1; printf '\\n{token}:%s\\n' \"$?\""
                proc.stdin.write(frame.encode() + b"\n")
                await asyncio.wait_for(proc.stdin.drain(), timeout=effective)
                out = bytearray()
                deadline = time.monotonic() + effective
                rc = 1
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                    if line is None:
                        raise RemoteFilesError("Интерактивный shell завершился на сервере")
                    if line in (b"", b"\n"):
                        continue
                    if line.startswith(f"{token}:".encode()):
                        rc_str = line[len(token) + 1 :].strip()
                        with suppress(ValueError):
                            rc = int(rc_str)
                        break
                    out += line
                logger.info("Команда выполнена: rc=%d (за %.1f с)", rc, time.monotonic() - start)
                return ShellResult(stdout=bytes(out), stderr=b"", exit_code=rc)
            except TimeoutError as exc:
                logger.warning("Таймаут команды «%s»; пересоздаём shell", command)
                await self._abort()
                raise RemoteFilesError(
                    f"Команда на сервере не выполнена: истекло время ожидания ({effective:.0f} с)"
                ) from exc
            except (OSError, asyncssh.Error) as exc:
                logger.warning("Ошибка «%s»: %s; пересоздаём shell", command, exc)
                await self._abort()
                raise RemoteFilesError(f"Команда на сервере не выполнена: {exc}") from exc

    async def _abort(self) -> None:
        """Drop the current shell channel (unblocks reads stuck on a dead shell)."""
        proc = self._process
        self._process = None
        if proc is None or proc.stdout.at_eof():
            return
        with suppress(Exception):
            proc.close()
            await asyncio.wait_for(proc.wait_closed(), timeout=2.0)

    @asynccontextmanager
    async def transfer_section(self):
        """Hold the shell lock for the duration of a transfer so shell commands
        and the SCP channel never run concurrently on the same connection.
        TinyCore/dropbear starts interleaving protocol traffic badly when a
        shell command and an scp transfer overlap, which wedges the connection.
        The interactive channel is left open — reopening it on dropbear after a
        close + scp pair hangs, so we never close it here.
        """
        async with self._lock:
            yield

    async def _force_close(self) -> None:
        """Close the whole SSH connection to unblock a stuck channel open."""
        conn = self._conn
        if not conn.is_closed():
            logger.warning("Принудительно закрываем SSH-соединение (зависло открытие канала)")
            conn.close()
            with suppress(Exception):
                await asyncio.wait_for(conn.wait_closed(), timeout=2.0)


def _as_bytes(value: Any, encoding: str) -> bytes:
    """Coerce asyncssh ``SSHCompletedProcess`` output (``str``/``bytes``/None)."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if value is None:
        return b""
    return str(value).encode(encoding or "utf-8", errors="replace")


class SSHScpProvider:
    """SCP transfers.

    Normally they run over the same existing SSH connection. For servers like
    TinyCore/dropbear, which mangle an SSH connection once the interactive
    shell channel coexists with (or outlives) an scp session, pass
    ``connect_kwargs`` and each transfer will open its own short-lived
    connection with no other channels on it.
    """

    def __init__(
        self,
        conn: asyncssh.SSHClientConnection,
        connect_kwargs: dict[str, object] | None = None,
    ) -> None:
        self._conn = conn
        self._connect_kwargs = connect_kwargs

    @asynccontextmanager
    async def _session(self):
        if not self._connect_kwargs:
            yield self._conn
            return
        conn = await connect_with_tofu(**self._connect_kwargs)
        try:
            yield conn
        finally:
            conn.close()
            await conn.wait_closed()

    async def upload(self, local: str | Path, remote: str, preserve: bool = True) -> None:
        async with self._session() as conn:
            await asyncssh.scp(str(local), (conn, remote), preserve=preserve)

    async def download(self, remote: str, local: str | Path, preserve: bool = True) -> None:
        async with self._session() as conn:
            await asyncssh.scp((conn, remote), str(local), preserve=preserve)


__all__ = [
    "SERVER_KEY_ALGS",
    "SFTP_SUBSYSTEM_TIMEOUT",
    "HostKeyStore",
    "SSHScpProvider",
    "SSHShellRunner",
    "build_connect_kwargs",
    "connect_with_tofu",
    "default_config_dir",
    "default_known_hosts_path",
    "host_expr",
    "translate_connect_error",
]


# --- merged from sftp_backend.py ---


"""SFTP backend built on asyncssh: primary high-fidelity remote backend."""


logger = logging.getLogger("cashcontrol.builtin.file_manager.sftp")


def sftp_attrs_to_info(path: str, name: str, attrs: Any) -> RemoteFileInfo:
    """Convert an asyncssh SFTPAttr report into a RemoteFileInfo."""
    permissions = int(attrs.permissions) if getattr(attrs, "permissions", None) else None
    kind = FileKind.OTHER
    if mode := permissions:
        if _stat.S_ISLNK(mode):
            kind = FileKind.SYMLINK
        elif _stat.S_ISDIR(mode):
            kind = FileKind.DIRECTORY
        elif _stat.S_ISREG(mode):
            kind = FileKind.FILE

    mtime = getattr(attrs, "mtime", None)
    modified_at = datetime.fromtimestamp(mtime, tz=UTC).replace(tzinfo=None) if mtime else None
    size = getattr(attrs, "size", None)
    uid = getattr(attrs, "uid", None)
    gid = getattr(attrs, "gid", None)
    return RemoteFileInfo(
        path=path,
        name=name,
        kind=kind,
        size=size,
        modified_at=modified_at,
        mode=permissions,
        owner=str(uid) if uid is not None else None,
        group=str(gid) if gid is not None else None,
        hidden=name.startswith("."),
    )


def _translate_op_error(exc: BaseException) -> RemoteFilesError:
    if isinstance(exc, RemoteFilesError):
        return exc
    code = getattr(exc, "code", None)
    if code == asyncssh.sftp.FX_NO_SUCH_FILE:
        return RemoteNotFoundError(str(exc))
    if code == asyncssh.sftp.FX_PERMISSION_DENIED:
        return RemotePermissionError(str(exc))
    if code in (asyncssh.sftp.FX_OP_UNSUPPORTED, asyncssh.sftp.FX_FAILURE):
        return RemoteFilesError(str(exc))
    if isinstance(exc, OSError):
        err_code = getattr(exc, "errno", None)
        if err_code in (errno.ENOENT, errno.ENOTDIR):
            return RemoteNotFoundError(str(exc))
        if err_code in (errno.EACCES, errno.EPERM):
            return RemotePermissionError(str(exc))
    return RemoteFilesError(str(exc))


async def _sftp_rename_overwrite(sftp, old: str, new: str) -> None:
    """Replace ``new`` with ``old`` over SFTP.

    Обычный SFTPv3 ``SSH_FXP_RENAME`` НЕ перезаписывает существующий файл —
    серверы без posix-rename (asyncssh SFTPServer, dropbear и т.п.) отвечают на
    такую перезапись FX_FAILURE, из-за чего сохранение в редакторе падало с
    "Failure". Пробуем расширение posix-rename (атомарно), а если оно не
    поддержано — удаляем цель и переименовываем заново (с проверками, чтобы
    не потерять оригинал при сбое).
    """
    first = None
    try:
        await sftp.posix_rename(old, new)
        return
    except (OSError, asyncssh.Error) as exc:
        first = exc
    assert first is not None

    # posix-rename недоступен: убеждаемся, что и источник, и цель существуют,
    # и что цель — обычный файл, прежде чем её удалять.
    try:
        await sftp.lstat(old)
    except (OSError, asyncssh.Error):
        raise first from None  # источника нет — настоящая ошибка, не политика перезаписи
    try:
        attrs = await sftp.lstat(new)
    except (OSError, asyncssh.Error):
        raise first from None  # цели нет — rename обязан был пройти, пробрасываем исходную ошибку
    if _stat.S_ISDIR(attrs.permissions):
        raise RemoteFilesError(f"{new} is a directory and cannot be replaced") from first
    await sftp.remove(new)
    await sftp.rename(old, new)


class SftpBackend:
    """RemoteFsBackend implementation over asyncssh's SFTP subsystem."""

    name = "sftp"

    def __init__(
        self,
        host: str = "",
        port: int = 22,
        username: str = "root",
        password: str | None = None,
        key_file: str | None = None,
        known_hosts_path: str | Path | None = None,
        connection: asyncssh.SSHClientConnection | None = None,
        own_connection: bool = False,
        timeout: float = 15.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._key_file = key_file
        self._timeout = timeout
        self._known_hosts_path = known_hosts_path
        self._conn = connection
        self._own_connection = own_connection
        self._sftp: asyncssh.SFTPClient | None = None

    async def connect(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            return
        self._conn = await connect_with_tofu(
            host=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            key_file=self._key_file,
            known_hosts=self._known_hosts_path,
            timeout=self._timeout,
        )
        self._own_connection = True

    async def _ensure_sftp(self) -> asyncssh.SFTPClient:
        await self.connect()
        if self._sftp is None:
            assert self._conn is not None
            logger.info("Запрашиваем SFTP-подсистему на %s…", self._host or self._conn.get_extra_info("peername"))
            try:
                self._sftp = await asyncio.wait_for(
                    self._conn.start_sftp_client(), SFTP_SUBSYSTEM_TIMEOUT
                )
            except (TimeoutError, OSError, asyncssh.Error) as exc:
                logger.warning("SFTP-подсистема недоступна: %s", exc, exc_info=True)
                raise RemoteConnectionError(
                    "SFTP-подсистема недоступна на удалённой машине; попробуйте протокол «scp»"
                ) from exc
            logger.info("SFTP-подсистема готова")
        return self._sftp

    async def close(self) -> None:
        if self._sftp is not None:
            self._sftp.exit()
            self._sftp = None
        if self._own_connection and self._conn is not None and not self._conn.is_closed():
            self._conn.close()
            self._conn = None

    async def list_dir(self, path: str) -> list[RemoteFileInfo]:
        sftp = await self._ensure_sftp()
        try:
            names = await sftp.listdir(path)
        except (OSError, asyncssh.Error) as exc:
            raise _translate_op_error(exc) from exc
        entries: list[RemoteFileInfo] = []
        for name in names:
            full = join_remote(path, name)
            try:
                attrs = await sftp.lstat(full)
                entries.append(sftp_attrs_to_info(full, name, attrs))
            except (OSError, asyncssh.Error):
                entries.append(
                    RemoteFileInfo(path=full, name=name, kind=FileKind.OTHER, hidden=name.startswith("."))
                )
        return entries

    async def stat(self, path: str) -> RemoteFileInfo:
        sftp = await self._ensure_sftp()
        try:
            attrs = await sftp.lstat(path)
        except (OSError, asyncssh.Error) as exc:
            raise _translate_op_error(exc) from exc
        return sftp_attrs_to_info(path, basename_remote(path), attrs)

    async def mkdir(self, path: str, mode: int | None = None) -> None:
        sftp = await self._ensure_sftp()
        try:
            await sftp.mkdir(path, mode=mode or 0o755)
        except (OSError, asyncssh.Error) as exc:
            raise _translate_op_error(exc) from exc

    async def rename(self, source: str, destination: str) -> None:
        sftp = await self._ensure_sftp()
        try:
            await sftp.rename(source, destination)
        except (OSError, asyncssh.Error) as exc:
            raise _translate_op_error(exc) from exc

    async def remove(self, path: str, recursive: bool = False) -> None:
        sftp = await self._ensure_sftp()
        try:
            attrs = await sftp.lstat(path)
        except (OSError, asyncssh.Error) as exc:
            raise _translate_op_error(exc) from exc
        if _stat.S_ISDIR(attrs.permissions):
            if not recursive:
                raise RemotePermissionError(f"{path} is a directory; delete recursively?")
            for name in await sftp.listdir(path):
                await self.remove(join_remote(path, name), recursive=True)
            await sftp.rmdir(path)
        else:
            await sftp.remove(path)

    async def chmod(self, path: str, mode: int) -> None:
        sftp = await self._ensure_sftp()
        try:
            await sftp.chmod(path, mode & 0o7777)
        except (OSError, asyncssh.Error) as exc:
            raise _translate_op_error(exc) from exc

    async def chown(
        self,
        path: str,
        owner: str | None = None,
        group: str | None = None,
    ) -> None:
        sftp = await self._ensure_sftp()
        uid = await self._resolve_id(owner, passwd=True) if owner is not None else None
        gid = await self._resolve_id(group, passwd=False) if group is not None else None
        try:
            await sftp.chown(path, uid=uid, gid=gid)
        except (OSError, asyncssh.Error) as exc:
            raise _translate_op_error(exc) from exc

    async def _resolve_id(self, name: str, *, passwd: bool = True) -> int | None:
        """Map an owner/group name to a numeric id via a one-shot shell command."""
        if name.isdigit():
            return int(name)
        assert self._conn is not None
        flag = "u" if passwd else "g"
        proc = await self._conn.run(f"id -{flag} {escape_sh(name)}")
        if proc is None or not proc.stdout:
            raise RemoteFilesError(f"Не удалось определить id для «{name}»")
        try:
            return int(proc.stdout)
        except ValueError as exc:
            raise RemoteFilesError(f"Не удалось определить id для «{name}»: {proc.stdout!r}") from exc

    @staticmethod
    def _temp_name(path: str, options: TransferOptions) -> str:
        return f"{path}{options.temp_suffix}-{secrets.token_hex(4)}"

    async def upload(
        self,
        local: Path,
        remote: str,
        options: TransferOptions,
        progress: ProgressCallback | None = None,
    ) -> None:
        sftp = await self._ensure_sftp()
        local = Path(local)

        def _progress(src: str, dst: str, copied: int, total: int) -> None:
            if progress is not None:
                progress(src, dst, int(copied), int(total))

        if local.is_dir():
            if not options.recursive:
                raise RemotePermissionError(f"{local} is a directory; recursion is required")
            await sftp.put(str(local), remote, recurse=True, preserve=options.preserve_mtime, progress_handler=_progress)
            return

        if options.atomic:
            temp = self._temp_name(remote, options)
            try:
                await sftp.put(str(local), temp, preserve=options.preserve_mtime, progress_handler=_progress)
                await _sftp_rename_overwrite(sftp, temp, remote)
            except BaseException as exc:
                with suppress(OSError, asyncssh.Error):
                    await sftp.remove(temp)
                raise _translate_op_error(exc) from exc
        else:
            await sftp.put(str(local), remote, preserve=options.preserve_mtime, progress_handler=_progress)

    async def download(
        self,
        remote: str,
        local: Path,
        options: TransferOptions,
        progress: ProgressCallback | None = None,
    ) -> None:
        sftp = await self._ensure_sftp()
        local = Path(local)

        def _progress(src: str, dst: str, copied: int, total: int) -> None:
            if progress is not None:
                progress(src, dst, int(copied), int(total))

        attrs = await sftp.lstat(remote)
        if _stat.S_ISDIR(attrs.permissions):
            if not options.recursive:
                raise RemotePermissionError(f"{remote} is a directory; recursion is required")
            await sftp.get(remote, str(local), recurse=True, preserve=options.preserve_mtime, progress_handler=_progress)
            return

        if options.atomic:
            temp = self._temp_name(str(local), options)
            try:
                await sftp.get(remote, temp, preserve=options.preserve_mtime, progress_handler=_progress)
                os.replace(temp, local)
            except BaseException as exc:
                with suppress(OSError):
                    os.remove(temp)
                raise _translate_op_error(exc) from exc
        else:
            await sftp.get(remote, str(local), preserve=options.preserve_mtime, progress_handler=_progress)

    async def read_file(self, path: str, max_bytes: int = 10 * 1024 * 1024) -> bytes:
        sftp = await self._ensure_sftp()
        try:
            async with sftp.open(path, "rb") as handle:
                data = await handle.read(max_bytes + 1)
        except (OSError, asyncssh.Error) as exc:
            raise _translate_op_error(exc) from exc
        if len(data) > max_bytes:
            raise RemoteFilesError(f"{path} exceeds the {max_bytes}-byte read limit")
        return bytes(data)

    async def write_file_atomic(self, path: str, data: bytes, mode: int | None = None) -> None:
        sftp = await self._ensure_sftp()
        temp = self._temp_name(path, TransferOptions())
        try:
            async with sftp.open(temp, "wb") as handle:
                await handle.write(data)
            if mode is not None:
                await sftp.chmod(temp, mode & 0o7777)
            await _sftp_rename_overwrite(sftp, temp, path)
        except BaseException as exc:
            with suppress(OSError, asyncssh.Error):
                await sftp.remove(temp)
            raise _translate_op_error(exc) from exc


__all__ = ["SftpBackend", "sftp_attrs_to_info"]


# --- merged from scp_shell_backend.py ---


"""SCP + shell backend: fallback for machines without an SFTP subsystem.

Uses ``ls``/``stat`` primitives for listing (machine readable, LC_ALL=C) and a
ScpTransferProvider for file movement. ``read_file``/``write_file_atomic`` are
implemented through SCP round-trips to a temp file so the built-in editor works
even without SFTP.
"""


GNU_STAT_FMT = "%F|%s|%Y|%a|%u|%g|%l"
BUSYBOX_STAT_FMT = "%s|%Y|%a|%u|%g"
PROBE_GNU = "LC_ALL=C stat -c '%F' /"
PROBE_BUSYBOX = f"stat -c '{BUSYBOX_STAT_FMT}' /"
PROBE_LS = "ls -la /"

_MONTH = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# ``ls -la``: <type><rwxrwxrwx> <n> <owner> <group> <size> <Mon> <dd> <HH:MM|YYYY> <name> …
_LS_LINE_RE = re.compile(
    r"^(?P<type>[dlbcps-])(?P<perms>[-rwxsStT]{9})\s+\d+\s+"
    r"(?P<owner>\S+)\s+(?P<group>\S+)\s+(?P<size>\d+)\s+"
    r"(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+(?P<when>\d{1,2}:\d{2}|\d{4})\s+"
    r"(?P<name>.+)$"
)

_PERM_BITS = (0o400, 0o200, 0o100, 0o040, 0o020, 0o010, 0o004, 0o002, 0o001)
_SPECIAL_BITS = (0o4000, 0o2000, 0o1000)


def _err_text(result: ShellResult) -> str:
    """Combine stderr and a non-empty stdout for shell-failure diagnostics."""
    stderr = result.stderr.decode("utf-8", errors="replace")
    stdout = result.stdout.decode("utf-8", errors="replace")
    parts = [part.strip() for part in (stderr, stdout) if part.strip()]
    return "\n".join(parts) if parts else f"rc={result.exit_code}"


@dataclass(frozen=True)
class ParsedStat:
    kind: FileKind = FileKind.OTHER
    size: int | None = None
    mtime: int | None = None
    perms: int | None = None
    owner: str | None = None
    group: str | None = None
    link_target: str | None = None


def build_stat_command(path: str, gnu: bool) -> str:
    fmt = GNU_STAT_FMT if gnu else BUSYBOX_STAT_FMT
    prefix = "LC_ALL=C " if gnu else ""
    return f"{prefix}stat -c '{fmt}' {escape_sh(path)}"


def build_ls_command(path: str) -> str:
    return f"ls -1A {escape_sh(path)}"


def build_test_dir_command(path: str) -> str:
    return f"test -d {escape_sh(path)} && echo d || echo f"


def build_readlink_command(path: str) -> str:
    return f"readlink {escape_sh(path)} 2>/dev/null || true"


def build_ls_la_command(path: str) -> str:
    return f"ls -la {escape_sh(path)}"


def _ls_path(path: str) -> str:
    path = path.rstrip("/")
    return path + "/" if path else "/"


def _perms_from_ls(spec: str) -> int | None:
    if len(spec) != 9:
        return None
    value = 0
    for i, char in enumerate(spec):
        if char == "r" or char == "w" or char in "x":
            value |= _PERM_BITS[i]
        elif char == "s":
            value |= _PERM_BITS[i] | _SPECIAL_BITS[i // 3]
        elif char == "S":
            # setuid/setgid/bit-липучки БЕЗ бита выполнения (ls показывает
            # верхний регистр именно когда execute не выставлен)
            value |= _SPECIAL_BITS[i // 3]
        elif char == "t":
            value |= _PERM_BITS[i] | 0o1000
        elif char == "T":
            value |= 0o1000
    return value


def _kind_from_ls(spec_type: str) -> FileKind:
    if spec_type == "d":
        return FileKind.DIRECTORY
    if spec_type == "l":
        return FileKind.SYMLINK
    if spec_type == "-":
        return FileKind.FILE
    return FileKind.OTHER


def _parse_ls_timestamp(month: str, day: str, when: str) -> int | None:
    month_num = _MONTH.get(month[:3].lower())
    if month_num is None:
        return None
    try:
        day_num = int(day)
        if ":" in when:
            hour, minute = (int(part) for part in when.split(":"))
            now = datetime.now()
            stamp = datetime(now.year, month_num, day_num, hour, minute)
            if stamp > now:
                stamp = datetime(now.year - 1, month_num, day_num, hour, minute)
            return int(stamp.timestamp())
        return int(datetime(int(when), month_num, day_num).timestamp())
    except ValueError:
        return None


def parse_ls_la_line(line: str) -> tuple[ParsedStat, str, str | None]:
    """Parse one ``ls -la`` line into metadata plus the entry and link target."""
    match = _LS_LINE_RE.match(line.strip())
    if match is None:
        raise ValueError(f"Unexpected ls -la line: {line!r}")
    kind = _kind_from_ls(match.group("type"))
    name = match.group("name").strip()
    link_target: str | None = None
    if kind is FileKind.SYMLINK and " -> " in name:
        name, link_target = name.split(" -> ", 1)
        name = name.strip()
    size = int(match.group("size"))
    mtime = _parse_ls_timestamp(match.group("month"), match.group("day"), match.group("when"))
    parsed = ParsedStat(
        kind=kind,
        size=size,
        mtime=mtime,
        perms=_perms_from_ls(match.group("perms")),
        owner=match.group("owner") or None,
        group=match.group("group") or None,
        link_target=link_target,
    )
    return parsed, name, link_target


def _kind_from_gnu(token: str) -> FileKind:
    if token.startswith("directory"):
        return FileKind.DIRECTORY
    if token.startswith("symbolic link"):
        return FileKind.SYMLINK
    if token.startswith("regular"):
        return FileKind.FILE
    return FileKind.OTHER


def _full_mode(kind: FileKind, perms: int | None) -> int | None:
    if perms is None:
        return None
    base = perms & 0o7777
    type_bits = {
        FileKind.DIRECTORY: 0o040000,
        FileKind.SYMLINK: 0o120000,
        FileKind.FILE: 0o100000,
    }
    return base | type_bits.get(kind, 0)


def parse_gnu_stat_line(line: str) -> ParsedStat:
    """Parse ``%F|%s|%Y|%a|%u|%g|%l`` output into structured metadata."""
    fields = line.split("|")
    if len(fields) < 6:
        raise ValueError(f"Unexpected stat output: {line!r}")
    kind = _kind_from_gnu(fields[0])
    try:
        size = int(fields[1]) if fields[1] else None
        mtime = int(float(fields[2])) if fields[2] else None
        perms = int(fields[3], 8) if fields[3] else None
    except ValueError as exc:
        raise ValueError(f"Unexpected stat output: {line!r}") from exc
    return ParsedStat(
        kind=kind,
        size=size,
        mtime=mtime,
        perms=perms,
        owner=fields[4] or None,
        group=fields[5] or None,
        link_target=fields[6] if len(fields) > 6 and fields[6] else None,
    )


def parse_busybox_stat_line(line: str) -> ParsedStat:
    """Parse ``%s|%Y|%a|%u|%g`` output (kind resolved separately)."""
    fields = line.split("|")
    if len(fields) < 3:
        raise ValueError(f"Unexpected stat output: {line!r}")
    try:
        size = int(fields[0]) if fields[0] else None
        mtime = int(float(fields[1])) if fields[1] else None
        perms = int(fields[2], 8) if fields[2] else None
    except ValueError as exc:
        raise ValueError(f"Unexpected stat output: {line!r}") from exc
    return ParsedStat(
        size=size,
        mtime=mtime,
        perms=perms,
        owner=fields[3] if len(fields) > 3 and fields[3] else None,
        group=fields[4] if len(fields) > 4 and fields[4] else None,
    )


def _info_from_parsed(
    parsed: ParsedStat,
    *,
    path: str,
    name: str,
) -> RemoteFileInfo:
    full_mode = _full_mode(parsed.kind, parsed.perms)
    modified_at = datetime.fromtimestamp(parsed.mtime) if parsed.mtime is not None else None
    return RemoteFileInfo(
        path=path,
        name=name,
        kind=parsed.kind,
        size=parsed.size,
        modified_at=modified_at,
        mode=full_mode,
        owner=parsed.owner,
        group=parsed.group,
        link_target=parsed.link_target,
        hidden=name.startswith("."),
    )


class ScpShellBackend:
    """RemoteFsBackend implementation over shell primitives + SCP transfers."""

    name = "scp"

    def __init__(
        self,
        runner: ShellRunner,
        scp: ScpTransferProvider | None = None,
        timeout: float | None = None,
    ) -> None:
        self._runner = runner
        self._scp = scp
        self._timeout = timeout
        self._mode: str | None = None  # "gnu" | "busybox" | "ls"
        self._has_readlink: bool = True

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def _run(self, command: str, timeout: float | None = None) -> ShellResult:
        return await self._runner.run(command, timeout=timeout if timeout is not None else self._timeout)

    async def _dir_kind(self, kind: FileKind, path: str) -> FileKind:
        if kind is not FileKind.SYMLINK:
            return kind
        result = await self._run(build_test_dir_command(path))
        if result.ok and result.stdout.strip() == b"d":
            return FileKind.DIRECTORY
        return kind

    async def _probe(self) -> None:
        if self._mode is not None:
            return
        gnu_probe = await self._run(PROBE_GNU)
        if gnu_probe.ok and gnu_probe.stdout.strip() == b"directory":
            self._mode = "gnu"
            return
        busybox_probe = await self._run(PROBE_BUSYBOX)
        if busybox_probe.ok and busybox_probe.stdout.strip():
            self._mode = "busybox"
            readlink_probe = await self._run("command -v readlink")
            self._has_readlink = readlink_probe.ok
            return
        ls_probe = await self._run(PROBE_LS)
        if ls_probe.ok and b"total" in ls_probe.stdout:
            self._mode = "ls"
            return
        raise UnsupportedByBackendError(
            "На удалённом хосте нет ни stat, ни рабочего ls; список файлов недоступен"
        )

    @staticmethod
    def _map_ls_error(path: str, result: ShellResult) -> RemoteFilesError:
        text = _err_text(result)
        if "No such file" in text:
            return RemoteNotFoundError(f"{path}: {text}")
        if "Permission" in text:
            return RemotePermissionError(f"{path}: {text}")
        return RemoteFilesError(f"{path}: {text}")

    async def list_dir(self, path: str) -> list[RemoteFileInfo]:
        await self._probe()
        if self._mode == "ls":
            return await self._list_dir_via_ls(path)
        result = await self._run(build_ls_command(_ls_path(path)))
        if not result.ok:
            raise self._map_ls_error(path, result)
        names = [n for n in result.stdout.decode("utf-8", errors="replace").splitlines() if n]
        entries: list[RemoteFileInfo] = []
        for name in names:
            full = join_remote(path, name)
            try:
                entries.append(await self._stat_entry(full))
            except RemoteNotFoundError:
                continue
        return entries

    async def _list_dir_via_ls(self, path: str) -> list[RemoteFileInfo]:
        result = await self._run(build_ls_la_command(_ls_path(path)))
        if not result.ok:
            raise self._map_ls_error(path, result)
        entries: list[RemoteFileInfo] = []
        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("total ") or stripped == "total":
                continue
            try:
                parsed, name, _ = parse_ls_la_line(stripped)
            except ValueError:
                continue
            if name in (".", "..", "./", "../"):
                continue
            name = name.rstrip("/")
            full = join_remote(path, name)
            parsed = replace(parsed, kind=await self._dir_kind(parsed.kind, full))
            entries.append(_info_from_parsed(parsed, path=full, name=name))
        return entries

    async def _stat_entry(self, path: str) -> RemoteFileInfo:
        await self._probe()
        name = basename_remote(path)
        if self._mode == "ls":
            return await self._stat_via_ls(path, name)
        result = await self._run(build_stat_command(path, gnu=self._mode == "gnu"))
        if not result.ok:
            text = _err_text(result)
            if "No such file" in text:
                raise RemoteNotFoundError(path)
            if "Permission" in text:
                raise RemotePermissionError(path)
            raise RemoteFilesError(f"{path}: {text}")
        line = result.stdout.decode("utf-8", errors="replace").strip()
        if self._mode == "gnu":
            parsed = parse_gnu_stat_line(line)
            parsed = replace(parsed, kind=await self._dir_kind(parsed.kind, path))
        else:
            parsed = parse_busybox_stat_line(line)
            kind = FileKind.FILE
            link_target: str | None = None
            if self._has_readlink:
                readlink = await self._run(build_readlink_command(path))
                if readlink.ok and readlink.stdout.strip():
                    link_target = readlink.stdout.decode("utf-8", errors="replace").strip()
                    kind = FileKind.SYMLINK
            if kind is FileKind.SYMLINK or link_target is None:
                test_dir = await self._run(build_test_dir_command(path))
                if test_dir.ok and test_dir.stdout.strip() == b"d":
                    kind = FileKind.DIRECTORY
            parsed = ParsedStat(
                kind=kind,
                size=parsed.size,
                mtime=parsed.mtime,
                perms=parsed.perms,
                owner=parsed.owner,
                group=parsed.group,
                link_target=link_target,
            )
        return _info_from_parsed(parsed, path=path, name=name)

    async def _stat_via_ls(self, path: str, name: str) -> RemoteFileInfo:
        if path == "/":
            return RemoteFileInfo(path="/", name="/", kind=FileKind.DIRECTORY, hidden=False)
        parent = parent_remote(path)
        result = await self._run(build_ls_la_command(_ls_path(parent)))
        if not result.ok:
            raise self._map_ls_error(path, result)
        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("total "):
                continue
            try:
                parsed, entry_name, _ = parse_ls_la_line(stripped)
            except ValueError:
                continue
            if entry_name in (".", "..", "./", "../"):
                continue
            if entry_name.rstrip("/") == name:
                parsed = replace(parsed, kind=await self._dir_kind(parsed.kind, path))
                return _info_from_parsed(parsed, path=path, name=name)
        raise RemoteNotFoundError(path)

    async def stat(self, path: str) -> RemoteFileInfo:
        return await self._stat_entry(path)

    async def mkdir(self, path: str, mode: int | None = None) -> None:
        if mode is not None:
            mask = mode & 0o7777
            result = await self._run(f"mkdir -m {oct(mask)} -p {escape_sh(path)}")
        else:
            result = await self._run(f"mkdir -p {escape_sh(path)}")
        if not result.ok:
            raise RemoteFilesError(f"mkdir {path}: {_err_text(result)}")

    async def rename(self, source: str, destination: str) -> None:
        result = await self._run(f"mv {escape_sh(source)} {escape_sh(destination)}")
        if not result.ok:
            text = _err_text(result)
            if "No such file" in text:
                raise RemoteNotFoundError(source)
            raise RemoteFilesError(f"mv {source}: {text}")

    async def remove(self, path: str, recursive: bool = False) -> None:
        info = await self.stat(path)
        if info.kind == FileKind.DIRECTORY and not recursive:
            raise RemotePermissionError(f"{path} is a directory; delete recursively?")
        if info.kind == FileKind.DIRECTORY or not info.is_file:
            result = await self._run(f"rm -rf {escape_sh(path)}")
        else:
            result = await self._run(f"rm -f {escape_sh(path)}")
        if not result.ok:
            raise RemoteFilesError(f"rm {path}: {_err_text(result)}")

    async def chmod(self, path: str, mode: int) -> None:
        result = await self._run(f"chmod {oct(mode & 0o7777)} {escape_sh(path)}")
        if not result.ok:
            raise RemoteFilesError(f"chmod {path}: {_err_text(result)}")

    async def chown(
        self,
        path: str,
        owner: str | None = None,
        group: str | None = None,
    ) -> None:
        target = ""
        if owner is not None or group is not None:
            target = f"{owner or ''}:{group or ''}"
        result = await self._run(f"chown {escape_sh(target)} {escape_sh(path)}")
        if not result.ok:
            text = _err_text(result)
            if "No such file" in text:
                raise RemoteNotFoundError(path)
            raise RemoteFilesError(f"chown {path}: {text}")

    async def upload(
        self,
        local: Path,
        remote: str,
        options: TransferOptions,
        progress: ProgressCallback | None = None,
    ) -> None:
        del progress
        local = Path(local)
        if self._scp is None:
            raise UnsupportedByBackendError("No SCP transfer provider was configured")
        temp: str | None = None
        if options.atomic and local.is_file():
            temp = f"{remote}{options.temp_suffix}-{secrets.token_hex(4)}"
        target = temp or remote
        try:
            section = getattr(self._runner, "transfer_section", None)
            if section is None:
                await self._scp.upload(local, target, preserve=options.preserve_mtime)
            else:
                async with section():
                    await self._scp.upload(local, target, preserve=options.preserve_mtime)
        except (OSError, asyncssh.Error) as exc:
            raise RemoteFilesError(f"scp upload failed: {exc}") from exc
        if temp is not None:
            try:
                result = await self._run(
                    f"rm -f {escape_sh(remote)}; mv {escape_sh(temp)} {escape_sh(remote)}"
                )
                if not result.ok:
                    text = _err_text(result)
                    if "No such file" in text:
                        raise RemoteNotFoundError(remote)
                    raise RemoteFilesError(f"mv {temp}: {text}")
            except RemoteFilesError:
                await self._run(f"rm -f {escape_sh(temp)}")
                raise

    async def download(
        self,
        remote: str,
        local: Path,
        options: TransferOptions,
        progress: ProgressCallback | None = None,
    ) -> None:
        del progress
        local = Path(local)
        if self._scp is None:
            raise UnsupportedByBackendError("No SCP transfer provider was configured")
        temp: str | None = None
        if options.atomic and not local.is_dir():
            temp = str(local.parent / f"{local.name}{options.temp_suffix}-{secrets.token_hex(4)}")
        target = str(temp or local)
        try:
            section = getattr(self._runner, "transfer_section", None)
            if section is None:
                await self._scp.download(remote, target, preserve=options.preserve_mtime)
            else:
                async with section():
                    await self._scp.download(remote, target, preserve=options.preserve_mtime)
        except (OSError, asyncssh.Error) as exc:
            raise RemoteFilesError(f"scp download failed: {exc}") from exc
        if temp is not None:
            try:
                os.replace(temp, local)
            except OSError as exc:
                with suppress(OSError):
                    os.remove(temp)
                raise RemoteFilesError(f"scp download failed: {exc}") from exc

    async def read_file(self, path: str, max_bytes: int = 10 * 1024 * 1024) -> bytes:
        if self._scp is None:
            raise UnsupportedByBackendError("No SCP transfer provider was configured")
        temp = Path(tempfile.gettempdir()) / f"remfiles-read-{secrets.token_hex(8)}"
        try:
            await self.download(path, temp, TransferOptions())
            data = temp.read_bytes()
        except (OSError, asyncssh.Error) as exc:
            raise RemoteFilesError(f"scp read failed: {exc}") from exc
        finally:
            with suppress(OSError):
                temp.unlink()
        if len(data) > max_bytes:
            raise RemoteFilesError(f"{path} exceeds the {max_bytes}-byte read limit")
        return data

    async def write_file_atomic(self, path: str, data: bytes, mode: int | None = None) -> None:
        if self._scp is None:
            raise UnsupportedByBackendError("No SCP transfer provider was configured")
        temp = Path(tempfile.gettempdir()) / f"remfiles-write-{secrets.token_hex(8)}"
        temp_path: str
        try:
            temp.write_bytes(data)
            temp_path = f"{path}{TransferOptions().temp_suffix}-{secrets.token_hex(4)}"
            await self.upload(temp, temp_path, TransferOptions(atomic=False))
            steps = f"chmod {oct(mode & 0o7777)} {escape_sh(temp_path)}; " if mode is not None else ""
            result = await self._run(f"{steps}mv -f {escape_sh(temp_path)} {escape_sh(path)}")
            if not result.ok:
                text = _err_text(result)
                if "No such file" in text:
                    raise RemoteNotFoundError(path)
                raise RemoteFilesError(f"mv {temp_path}: {text}")
        except RemoteFilesError:
            with suppress(OSError, asyncssh.Error):
                await self._run(f"rm -f {escape_sh(temp_path)}")
            raise
        finally:
            with suppress(OSError):
                temp.unlink()


__all__ = [
    "BUSYBOX_STAT_FMT",
    "GNU_STAT_FMT",
    "PROBE_BUSYBOX",
    "PROBE_GNU",
    "PROBE_LS",
    "ParsedStat",
    "ScpShellBackend",
    "build_ls_command",
    "build_ls_la_command",
    "build_readlink_command",
    "build_stat_command",
    "build_test_dir_command",
    "parse_busybox_stat_line",
    "parse_gnu_stat_line",
    "parse_ls_la_line",
]
