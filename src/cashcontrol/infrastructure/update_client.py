from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_app_root, get_soft_dir

if TYPE_CHECKING:
    from cashcontrol.infrastructure.hot_reload_manager import HotReloadManager

logger = get_logger()


@dataclass
class CheckResult:
    available: bool = False
    new_version: str = ""
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    hot_files: list[str] = field(default_factory=list)
    cold_files: list[str] = field(default_factory=list)
    cold_required: bool = False
    error: str = ""

    @classmethod
    def from_json(cls, raw: bytes) -> CheckResult:
        try:
            data = json.loads(raw)
            return cls(
                available=data.get("available", False),
                new_version=data.get("version", ""),
                updated=data.get("updated", []),
                removed=data.get("removed", []),
                hot_files=data.get("hot_files", []),
                cold_files=data.get("cold_files", []),
                cold_required=data.get("cold_required", False),
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to parse CheckResult JSON: {e}")
            return cls(error="invalid response from cc-updater")


class UpdateClient(QObject):
    check_started = Signal()
    check_finished = Signal()
    server_status_changed = Signal(bool)
    update_available = Signal(object)
    update_failed = Signal(str)
    restart_required = Signal(list)

    def __init__(
        self,
        network_path: str,
        hot_reload_manager: HotReloadManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = network_path
        self._exe = get_soft_dir() / "cc-updater.exe"
        self._target = str(get_app_root())
        self._hot_reload_mgr = hot_reload_manager
        self._running = False
        self._task: asyncio.Task | None = None

    def _exe_available(self) -> bool:
        if not self._exe.exists():
            logger.warning("cc-updater.exe not found, skipping updates")
            return False
        return True

    def _configured(self) -> bool:
        if not self._source or not str(self._source).strip():
            logger.debug("Update source (network path) is not configured, skipping")
            return False
        return True

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run_loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def check_now(self) -> None:
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._do_check())

    async def check(self) -> CheckResult:
        if not self._exe_available() or not self._configured():
            return CheckResult()
        try:
            out = await self._run(
                "--check",
                "--source", self._source,
                "--target", self._target,
            )
            return CheckResult.from_json(out)
        except TimeoutError:
            return CheckResult(error="update check timed out")
        except Exception:
            logger.exception("Update check failed")
            return CheckResult(error="unexpected error")

    async def apply_hot(self) -> bool:
        if not self._exe_available() or not self._configured():
            return False
        try:
            out = await self._run(
                "--apply",
                "--source", self._source,
                "--target", self._target,
                "--files", "hot",
            )
            result = json.loads(out)
            return result.get("success", False)
        except Exception:
            logger.exception("Hot update apply failed")
            return False

    async def apply_cold(self) -> bool:
        if not self._exe_available() or not self._configured():
            return False
        try:
            out = await self._run(
                "--apply",
                "--source", self._source,
                "--target", self._target,
                "--files", "cold",
                timeout=120.0,
            )
            result = json.loads(out)
            return result.get("success", False)
        except Exception:
            logger.exception("Cold update apply failed")
            return False

    def set_pending_cold(self) -> None:
        (get_app_root() / ".pending_update").write_text("cold")

    @staticmethod
    def has_pending_cold() -> bool:
        return (get_app_root() / ".pending_update").exists()

    @staticmethod
    def clear_pending() -> None:
        (get_app_root() / ".pending_update").unlink(missing_ok=True)

    async def _run_loop(self) -> None:
        while self._running:
            await asyncio.sleep(300)
            if self._running:
                await self._do_check()

    async def _run(self, *args: str, timeout: float = 20.0) -> bytes:
        proc = await asyncio.create_subprocess_exec(
            str(self._exe), *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise

        if stderr:
            logger.debug(f"cc-updater stderr: {stderr.decode(errors='replace')}")
        return stdout

    async def _do_check(self) -> None:
        if not self._exe_available() or not self._configured():
            return
        self.check_started.emit()
        try:
            out = await self._run(
                "--check",
                "--source", self._source,
                "--target", self._target,
            )
            result = CheckResult.from_json(out)
            self.server_status_changed.emit(not result.error)

            if result.available:
                if result.hot_files:
                    applied = await self.apply_hot()
                    if applied and self._hot_reload_mgr:
                        app_root = Path(self._target)
                        for f in result.hot_files:
                            self._hot_reload_mgr.reload_module(app_root / f)
                    if applied:
                        result.updated = result.hot_files
                        logger.info(f"Hot-updated {len(result.hot_files)} files")

                if result.cold_files:
                    self.set_pending_cold()
                    result.cold_required = True
                    self.restart_required.emit(result.cold_files)
                    logger.info(f"Cold update pending for {len(result.cold_files)} files")

                self.update_available.emit(result)
            self.check_finished.emit()
        except Exception as e:
            logger.exception("Update check failed")
            self.update_failed.emit(str(e))
            self.check_finished.emit()