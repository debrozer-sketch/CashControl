"""Data models and path helpers shared by all Remote Files components."""

from __future__ import annotations

import enum
import shlex
import stat as _stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime  # noqa: TC003
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import BaseModel, Field


def normalize_remote(path: str) -> str:
    """Normalize a remote path to an absolute form ``/a/b`` (root is ``/``).

    Relative input is resolved against the root, ``.`` components are dropped
    and ``..`` components are resolved syntactically (never below the root).
    """
    path = path.strip()
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    parts = [part for part in path.split("/") if part and part != "/"]
    resolved: list[str] = []
    for part in parts:
        if part == ".":
            continue
        if part == "..":
            if resolved:
                resolved.pop()
            continue
        resolved.append(part)
    return "/" if not resolved else "/" + "/".join(resolved)


def join_remote(base: str, name: str) -> str:
    """Join a directory and a single entry name into one remote path."""
    return normalize_remote(base.rstrip("/") + "/" + name.lstrip("/"))


def parent_remote(path: str) -> str:
    """Return the parent directory of a remote path (``/`` for the root)."""
    norm = normalize_remote(path)
    if norm == "/":
        return "/"
    parts = PurePosixPath(norm).parts
    if len(parts) <= 2:
        return "/"
    return "/" + "/".join(parts[1:-1])


def basename_remote(path: str) -> str:
    """Return the final component of a remote path."""
    name = PurePosixPath(normalize_remote(path)).name
    return name or "/"


def has_traversal(path: str) -> bool:
    """Return True when a remote path contains a ``..`` component."""
    return any(part == ".." for part in path.split("/"))


def safe_join_local(local_dir: Path, remote_name: str) -> Path:
    """Join a remote entry name onto a local directory preventing escapes."""
    if not remote_name or remote_name in {".", ".."}:
        raise ValueError(f"Unsafe remote name: {remote_name!r}")
    if "/" in remote_name or "\\" in remote_name:
        raise ValueError(f"Unsafe remote name: {remote_name!r}")
    return local_dir / remote_name


def escape_sh(path: str) -> str:
    """Shell-quote a path for safe use inside a remote command line."""
    return shlex.quote(path)


def human_size(num: int | float | None) -> str:
    """Render a byte count in a human friendly form ('' for None)."""
    if num is None:
        return ""
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{size:.0f} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"


class FileKind(enum.StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


class OverwritePolicy(enum.StrEnum):
    ASK = "ask"
    OVERWRITE = "overwrite"
    SKIP = "skip"
    RENAME = "rename"
    OVERWRITE_IF_NEWER = "overwrite_if_newer"


class TransferStatus(enum.StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RemoteFileInfo(BaseModel):
    """Metadata about a single remote filesystem entry."""

    path: str
    name: str
    kind: FileKind = FileKind.FILE
    size: int | None = None
    modified_at: datetime | None = None
    mode: int | None = None
    owner: str | None = None
    group: str | None = None
    link_target: str | None = None
    hidden: bool = False
    readable: bool | None = None
    writable: bool | None = None

    @property
    def is_dir(self) -> bool:
        return self.kind is FileKind.DIRECTORY

    @property
    def is_file(self) -> bool:
        return self.kind is FileKind.FILE

    @property
    def is_symlink(self) -> bool:
        return self.kind is FileKind.SYMLINK

    @property
    def mode_str(self) -> str:
        if self.mode is None:
            return "---------"
        return _stat.filemode(self.mode)

    @property
    def size_formatted(self) -> str:
        return human_size(self.size) if self.size is not None else ""


class TransferOptions(BaseModel):
    """User-configurable behaviour for transfers and deletions."""

    recursive: bool = True
    overwrite_policy: OverwritePolicy = OverwritePolicy.ASK
    preserve_mtime: bool = True
    preserve_permissions: bool = False
    follow_symlinks: bool = False
    atomic: bool = True
    temp_suffix: str = ".remfiles-part"


class TransferProgress(BaseModel):
    """Live progress snapshot of a single transfer/delete job."""

    job_id: str
    operation: str
    source: str
    destination: str
    current_path: str | None = None
    status: TransferStatus = TransferStatus.WAITING
    transferred_bytes: int = 0
    total_bytes: int | None = None
    total_transferred_bytes: int = 0
    total_size: int | None = None
    speed_bps: float = 0.0
    elapsed_seconds: float = 0.0
    eta_seconds: float | None = None
    error: str | None = None


class TransferResult(BaseModel):
    """Summary of files handled by a transfer/delete operation."""

    operation: str
    success: bool = True
    transferred_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    transferred_bytes: int = 0
    errors: list[str] = Field(default_factory=list)


ConflictAction = Literal["overwrite", "skip", "rename", "abort"]

__all__ = [
    "ConflictAction",
    "FileKind",
    "OverwritePolicy",
    "RemoteFileInfo",
    "TransferOptions",
    "TransferProgress",
    "TransferResult",
    "TransferStatus",
    "basename_remote",
    "escape_sh",
    "has_traversal",
    "human_size",
    "join_remote",
    "normalize_remote",
    "parent_remote",
    "safe_join_local",
]


# --- merged from errors.py ---


"""Typed exceptions for the Remote Files package."""


class RemoteFilesError(Exception):
    """Base class for all Remote Files errors."""


class RemoteConnectionError(RemoteFilesError):
    """Could not reach the remote host (timeout, network, refusal)."""


class RemoteAuthError(RemoteFilesError):
    """Authentication failed (bad password/key, forbidden user)."""


class HostKeyMismatchError(RemoteFilesError):
    """Host key differs from the one recorded on first contact (TOFU)."""


class RemotePermissionError(RemoteFilesError):
    """Operation rejected by the remote side or by our own safety guard."""


class RemoteNotFoundError(RemoteFilesError):
    """Path does not exist on the remote side."""


class OperationCancelledError(RemoteFilesError):
    """Transfer/operation was cancelled by the user or scheduler."""


class UnsupportedByBackendError(RemoteFilesError):
    """The selected backend does not support the requested operation."""


# --- merged from backend.py ---


"""Backend contracts: shell runner, SCP provider and the remote FS interface."""


# (source_path, destination_path, bytes_copied, bytes_total) — backend callback.
ProgressCallback = Callable[[str, str, int, int], None]


@dataclass(slots=True)
class ShellResult:
    stdout: bytes
    stderr: bytes
    exit_code: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")


class ShellRunner(Protocol):
    """Executes primitive commands on the remote shell (used by SCP backend)."""

    async def run(self, command: str, timeout: float | None = None) -> ShellResult: ...


class ScpTransferProvider(Protocol):
    """Encapsulates the SCP-like transfer of a single file/directory."""

    async def upload(self, local: str | Path, remote: str, preserve: bool = True) -> None: ...
    async def download(self, remote: str, local: str | Path, preserve: bool = True) -> None: ...


class RemoteFsBackend(Protocol):
    """Interface every remote backend must implement (SFTP and shell fallback)."""

    name: str

    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    async def list_dir(self, path: str) -> list[RemoteFileInfo]: ...
    async def stat(self, path: str) -> RemoteFileInfo: ...
    async def mkdir(self, path: str, mode: int | None = None) -> None: ...
    async def rename(self, source: str, destination: str) -> None: ...
    async def remove(self, path: str, recursive: bool = False) -> None: ...
    async def chmod(self, path: str, mode: int) -> None: ...
    async def chown(
        self,
        path: str,
        owner: str | None = None,
        group: str | None = None,
    ) -> None: ...

    async def upload(
        self,
        local: Path,
        remote: str,
        options: TransferOptions,
        progress: ProgressCallback | None = None,
    ) -> None: ...
    async def download(
        self,
        remote: str,
        local: Path,
        options: TransferOptions,
        progress: ProgressCallback | None = None,
    ) -> None: ...

    async def read_file(self, path: str, max_bytes: int = 10 * 1024 * 1024) -> bytes: ...
    async def write_file_atomic(self, path: str, data: bytes, mode: int | None = None) -> None: ...


__all__ = [
    "ProgressCallback",
    "RemoteFsBackend",
    "ScpTransferProvider",
    "ShellResult",
    "ShellRunner",
]
