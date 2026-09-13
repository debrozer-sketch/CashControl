"""Facade over a RemoteFsBackend exposing high-level and safe operations."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from cashcontrol.builtin.file_manager.models import (
    ConflictAction,
    OperationCancelledError,
    OverwritePolicy,
    RemoteFileInfo,
    RemoteFilesError,
    RemoteNotFoundError,
    RemotePermissionError,
    TransferOptions,
    TransferProgress,
    TransferResult,
    TransferStatus,
    basename_remote,
    has_traversal,
    join_remote,
    normalize_remote,
    parent_remote,
    safe_join_local,
)

if TYPE_CHECKING:
    from cashcontrol.builtin.file_manager.models import ProgressCallback, RemoteFsBackend

ConfirmCallback = Callable[[list[str], bool], bool]


class ConflictInfo(BaseModel):
    """Describes a file that already exists at the transfer destination."""

    source: str
    destination: str
    source_size: int | None = None
    destination_size: int | None = None
    source_mtime: datetime | None = None
    destination_mtime: datetime | None = None


ConflictResolver = Callable[[ConflictInfo], tuple[ConflictAction, bool]]


class RemoteFileService:
    """High-level, safe operations layered on a single remote backend."""

    def __init__(
        self,
        backend: RemoteFsBackend,
        close_backend: bool = False,
        on_conflict: ConflictResolver | None = None,
    ) -> None:
        self._backend = backend
        self._close_backend = close_backend
        self._on_conflict = on_conflict

    @property
    def backend(self) -> RemoteFsBackend:
        return self._backend

    async def connect(self) -> None:
        await self._backend.connect()

    async def close(self) -> None:
        if self._close_backend:
            await self._backend.close()

    async def list_dir(self, path: str) -> list[RemoteFileInfo]:
        return await self._backend.list_dir(normalize_remote(path))

    async def stat(self, path: str) -> RemoteFileInfo:
        return await self._backend.stat(normalize_remote(path))

    async def mkdir(self, path: str, mode: int | None = None, create_parents: bool = False) -> None:
        path = self._normalize_guarded(path)
        if not create_parents:
            await self._backend.mkdir(path, mode)
            return
        parts = [part for part in path.split("/") if part]
        current: list[str] = []
        for part in parts:
            current.append(part)
            node = "/" + "/".join(current)
            node = node if node != "/" else "/"
            try:
                info = await self._backend.stat(node)
            except RemoteNotFoundError:
                await self._backend.mkdir(node, mode)
                continue
            if not info.is_dir:
                raise RemoteFilesError(f"{node} exists and is not a directory")

    async def rename(self, source: str, destination: str) -> None:
        source = self._normalize_guarded(source)
        destination = self._normalize_guarded(destination)
        await self._backend.rename(source, destination)

    async def chmod(self, path: str, mode: int) -> None:
        path = self._normalize_guarded(path)
        await self._backend.chmod(path, mode)

    async def chown(
        self,
        path: str,
        owner: str | None = None,
        group: str | None = None,
    ) -> None:
        path = self._normalize_guarded(path)
        if owner is None and group is None:
            return
        await self._backend.chown(path, owner, group)

    async def read_file(self, path: str, max_bytes: int = 10 * 1024 * 1024) -> bytes:
        path = self._normalize_guarded(path)
        return await self._backend.read_file(path, max_bytes)

    async def write_file_atomic(self, path: str, data: bytes, mode: int | None = None) -> None:
        path = self._normalize_guarded(path)
        return await self._backend.write_file_atomic(path, data, mode)

    @staticmethod
    def _guard(path: str) -> None:
        if has_traversal(path):
            raise RemotePermissionError(f"Path traversal is not allowed: {path}")

    @classmethod
    def _normalize_guarded(cls, path: str) -> str:
        cls._guard(path)
        return normalize_remote(path)

    async def _stat_optional(self, path: str) -> RemoteFileInfo | None:
        try:
            return await self._backend.stat(path)
        except RemoteNotFoundError:
            return None

    def _resolve_conflict(
        self,
        conflict: ConflictInfo,
        options: TransferOptions,
        on_conflict: ConflictResolver | None,
    ) -> str:
        if options.overwrite_policy is OverwritePolicy.ASK:
            resolver = on_conflict or self._on_conflict
            if resolver is not None:
                action, _ = resolver(conflict)
                return str(action)
            return "skip"
        return auto_resolve(conflict, options)

    async def upload(
        self,
        local_paths: list[Path],
        remote_dir: str,
        options: TransferOptions,
        on_conflict: ConflictResolver | None = None,
        progress: ProgressCallback | None = None,
    ) -> TransferResult:
        """Upload files/directories into a remote directory, applying conflict policy."""
        remote_dir = self._normalize_guarded(remote_dir)
        result = TransferResult(operation="upload")
        for local in local_paths:
            local = Path(local)
            if not local.exists():
                result.errors.append(f"{local}: no such local path")
                result.failed_files += 1
                continue
            target = join_remote(remote_dir, local.name)
            existing = await self._stat_optional(target)
            if existing is not None:
                conflict = ConflictInfo(
                    source=local.name,
                    destination=target,
                    source_size=local.stat().st_size if local.is_file() else None,
                    destination_size=existing.size,
                    destination_mtime=existing.modified_at,
                )
                decision = self._resolve_conflict(conflict, options, on_conflict)
                if decision == "skip":
                    result.skipped_files += 1
                    continue
                if decision == "rename":
                    target = renamed_destination(target)
            try:
                await self._backend.upload(local, target, options, progress=progress)
                result.transferred_files += 1
            except OperationCancelledError:
                result.success = False
                raise
            except RemoteFilesError as exc:
                result.errors.append(str(exc))
                result.failed_files += 1
        result.success = result.failed_files == 0
        return result

    async def download(
        self,
        remote_paths: list[str],
        local_dir: Path,
        options: TransferOptions,
        on_conflict: ConflictResolver | None = None,
        progress: ProgressCallback | None = None,
    ) -> TransferResult:
        """Download remote paths into a local directory, applying conflict policy."""
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)
        result = TransferResult(operation="download")
        for remote in remote_paths:
            remote = self._normalize_guarded(remote)
            name = basename_remote(remote)
            if name == "/":
                result.errors.append("Cannot download the remote root directory")
                result.failed_files += 1
                continue
            try:
                local_target = safe_join_local(local_dir, name)
            except ValueError as exc:
                result.errors.append(str(exc))
                result.failed_files += 1
                continue
            remote_info = await self._stat_optional(remote)
            if remote_info is not None and local_target.exists():
                if remote_info.is_dir:
                    decision = self._resolve_conflict(
                        ConflictInfo(
                            source=remote,
                            destination=str(local_target),
                            source_mtime=remote_info.modified_at,
                            destination_mtime=None,
                        ),
                        options,
                        on_conflict,
                    )
                    if decision == "skip":
                        result.skipped_files += 1
                        continue
                    if decision == "rename":
                        local_target = renamed_destination(str(local_target))
                else:
                    conflict = ConflictInfo(
                        source=remote,
                        destination=str(local_target),
                        source_size=remote_info.size,
                        destination_size=local_target.stat().st_size if local_target.is_file() else None,
                        source_mtime=remote_info.modified_at,
                        destination_mtime=_mtime_of(local_target),
                    )
                    decision = self._resolve_conflict(conflict, options, on_conflict)
                    if decision == "skip":
                        result.skipped_files += 1
                        continue
                    if decision == "rename":
                        local_target = renamed_destination(str(local_target))
            try:
                if remote_info is not None and remote_info.is_dir:
                    local_target.mkdir(parents=True, exist_ok=True)
                await self._backend.download(remote, local_target, options, progress=progress)
                result.transferred_files += 1
            except OperationCancelledError:
                result.success = False
                raise
            except RemoteFilesError as exc:
                result.errors.append(str(exc))
                result.failed_files += 1
        result.success = result.failed_files == 0
        return result

    async def remove(
        self,
        paths: list[str],
        recursive: bool = False,
        on_confirm: ConfirmCallback | None = None,
    ) -> TransferResult:
        """Delete remote paths; directories require ``recursive`` confirmation."""
        normalized = [self._normalize_guarded(p) for p in paths]
        result = TransferResult(operation="delete")
        if recursive and on_confirm is not None and not on_confirm(normalized, recursive):
            result.skipped_files = len(normalized)
            return result
        for path in normalized:
            trying_recursive = recursive
            try:
                while True:
                    try:
                        await self._backend.remove(path, recursive=trying_recursive)
                        result.transferred_files += 1
                        break
                    except RemotePermissionError as exc:
                        if not trying_recursive and on_confirm is not None and on_confirm([path], True):
                            trying_recursive = True
                            continue
                        result.errors.append(str(exc))
                        result.failed_files += 1
                        break
            except OperationCancelledError:
                result.success = False
                raise
            except RemoteFilesError as exc:
                result.errors.append(str(exc))
                result.failed_files += 1
        result.success = result.failed_files == 0
        return result


def _mtime_of(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def auto_resolve(conflict: ConflictInfo, options: TransferOptions) -> ConflictAction:
    """Resolve a conflict without user interaction (ASK raises a ValueError)."""
    policy = options.overwrite_policy
    if policy is OverwritePolicy.OVERWRITE:
        return "overwrite"
    if policy is OverwritePolicy.SKIP:
        return "skip"
    if policy is OverwritePolicy.RENAME:
        return "rename"
    if policy is OverwritePolicy.OVERWRITE_IF_NEWER:
        if conflict.source_mtime is None:
            return "overwrite"
        if conflict.destination_mtime is None:
            return "overwrite"
        return "overwrite" if conflict.source_mtime > conflict.destination_mtime else "skip"
    raise ValueError("OverwritePolicy.ASK requires an interactive conflict resolver")


_RENAME_SUFFIX_RE = re.compile(r"\s\(([1-9]\d*)\)(?=(\.[^()\s]*)?$)")


def _strip_rename_suffix(name: str) -> str | None:
    """If ``name`` carries a trailing `` (N)`` (N>0, optional extension), return
    the original name it was derived from by removing the outermost suffix."""
    matches = list(_RENAME_SUFFIX_RE.finditer(name))
    if not matches:
        return None
    match = matches[-1]
    extension = match.group(2) or ""
    return name[: match.start()] + extension


def renamed_destination(destination: str) -> str:
    """Produce a WinSCP-style ``name (1).ext`` variant of a remote path.

    Names that already carry a `` (N)`` suffix are treated as copies and are
    renamed back to the original they were derived from.
    """
    parent = parent_remote(destination)
    name = basename_remote(destination)
    original = _strip_rename_suffix(name)
    if original is not None:
        return join_remote(parent, original)
    if "." in name and not name.startswith("."):
        stem, suffix = name.rsplit(".", 1)
        candidate = f"{stem} (1).{suffix}"
    else:
        candidate = f"{name} (1)"
    return join_remote(parent, candidate)


__all__ = ["ConfirmCallback", "ConflictInfo", "RemoteFileService", "auto_resolve", "renamed_destination"]


# --- merged from transfer.py ---


"""Asynchronous transfer/delete queue shared by GUI and automation."""


JobRunner = Callable[["TransferJob"], Awaitable[TransferResult]]
JobHandler = Callable[["TransferJob"], None]


class TransferJob(BaseModel):
    """A queued operation with live progress and its final result."""

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    progress: TransferProgress
    result: TransferResult | None = None


class TransferQueue:
    """Runs a fixed number of enqueued jobs concurrently with cancel/retry."""

    def __init__(self, concurrency: int = 1) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.concurrency = concurrency
        self._jobs: dict[str, TransferJob] = {}
        self._runners: dict[str, JobRunner] = {}
        self._pending: deque[str] = deque()
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._workers: list[asyncio.Task] = []
        self._handlers: list[JobHandler] = []
        self._started = False

    # ── lifecycle ───────────────────────────────────────
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._workers = [asyncio.create_task(self._worker()) for _ in range(self.concurrency)]

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    # ── scheduling ──────────────────────────────────────
    def enqueue(self, operation: str, source: str, destination: str, runner: JobRunner) -> str:
        job_id = uuid.uuid4().hex
        job = TransferJob(
            job_id=job_id,
            progress=TransferProgress(
                job_id=job_id,
                operation=operation,
                source=source,
                destination=destination,
            ),
        )
        self._jobs[job.job_id] = job
        self._runners[job.job_id] = runner
        self._cancel_events[job.job_id] = asyncio.Event()
        self._pending.append(job.job_id)
        self._notify(job)
        return job.job_id

    async def _worker(self) -> None:
        while self._started:
            job_id = await self._next_job_id()
            if job_id is None:
                return
            await self._process(job_id)

    async def _next_job_id(self) -> str | None:
        while True:
            if not self._started:
                return None
            if not self._pending:
                await asyncio.sleep(0.02)
                continue
            while self._pending:
                candidate = self._pending.popleft()
                event = self._cancel_events.get(candidate)
                if event is None:
                    continue
                if event.is_set():
                    job = self._jobs.get(candidate)
                    if job is not None:
                        job.progress.status = TransferStatus.CANCELLED
                        self._notify(job)
                    continue
                return candidate

    async def _process(self, job_id: str) -> None:
        runner = self._runners.get(job_id)
        job = self._jobs.get(job_id)
        if runner is None or job is None:
            return
        cancel_event = self._cancel_events[job_id]
        job.progress.status = TransferStatus.RUNNING
        self._notify(job)
        try:
            result = await runner(job)
            job.result = result
            job.progress.transferred_bytes = result.transferred_bytes
            if cancel_event.is_set():
                job.progress.status = TransferStatus.CANCELLED
            else:
                job.progress.status = TransferStatus.COMPLETED
        except OperationCancelledError as exc:
            job.progress.status = TransferStatus.CANCELLED
            job.progress.error = str(exc)
        except asyncio.CancelledError:
            job.progress.status = TransferStatus.CANCELLED
            self._notify(job)
            raise
        except RemoteFilesError as exc:
            job.progress.status = TransferStatus.FAILED
            job.progress.error = str(exc)
        except Exception as exc:
            job.progress.status = TransferStatus.FAILED
            job.progress.error = str(exc)
        self._notify(job)

    # ── control ─────────────────────────────────────────
    def cancel(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False
        event = self._cancel_events[job_id]
        event.set()
        job = self._jobs[job_id]
        if job.progress.status is TransferStatus.WAITING:
            job.progress.status = TransferStatus.CANCELLED
            self._notify(job)
        return True

    def cancel_all(self) -> int:
        count = 0
        for job_id in list(self._jobs):
            if self.cancel(job_id):
                count += 1
        return count

    def retry(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.progress.status not in {
            TransferStatus.FAILED,
            TransferStatus.CANCELLED,
        }:
            return False
        job.progress.status = TransferStatus.WAITING
        job.progress.error = None
        job.result = None
        self._cancel_events[job_id].clear()
        self._pending.append(job_id)
        self._notify(job)
        return True

    def remove_job(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False
        self._cancel_events.pop(job_id, None)
        self._runners.pop(job_id, None)
        self._jobs.pop(job_id)
        self._pending = deque(job for job in self._pending if job != job_id)
        return True

    def clear(self) -> int:
        count = len(self._jobs)
        for job_id in list(self._jobs):
            self.remove_job(job_id)
        return count

    # ── observation ─────────────────────────────────────
    def subscribe(self, handler: JobHandler) -> None:
        self._handlers.append(handler)

    def unsubscribe(self, handler: JobHandler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)

    def _notify(self, job: TransferJob) -> None:
        for handler in tuple(self._handlers):
            try:
                handler(job)
            except Exception:
                continue

    def jobs(self) -> list[TransferJob]:
        return [self._jobs[job_id] for job_id in self._jobs]

    def get(self, job_id: str) -> TransferJob | None:
        return self._jobs.get(job_id)


__all__ = ["JobHandler", "JobRunner", "TransferJob", "TransferQueue"]
