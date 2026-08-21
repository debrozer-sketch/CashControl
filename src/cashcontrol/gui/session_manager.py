from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager
from cashcontrol.infrastructure.path_resolver import get_sessions_file

if TYPE_CHECKING:
    from cashcontrol.gui.cash_session_widget import CashSessionWidget

logger = get_logger()


class SessionManager(QObject):
    ping_status_changed = Signal(str, str)
    session_added = Signal(str)
    session_removed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = ConfigManager()
        self._sessions: dict[str, CashSessionWidget] = {}
        self._vnc_procs: dict[str, subprocess.Popen] = {}
        self._ping_tasks: dict[str, asyncio.Task] = {}
        self._ping_statuses: dict[str, str] = {}
        self._active_ip: str | None = None

    # ── Active session ───────────────────────────────────────

    @property
    def active_ip(self) -> str | None:
        return self._active_ip

    @active_ip.setter
    def active_ip(self, ip: str | None) -> None:
        self._active_ip = ip

    # ── Session management ───────────────────────────────────

    def add_session(self, ip: str, widget: CashSessionWidget) -> None:
        self._sessions[ip] = widget
        self.session_added.emit(ip)

    def remove_session(self, ip: str) -> CashSessionWidget | None:
        widget = self._sessions.pop(ip, None)
        if widget:
            self.session_removed.emit(ip)
        return widget

    def get_session(self, ip: str) -> CashSessionWidget | None:
        return self._sessions.get(ip)

    def get_all_ips(self) -> list[str]:
        return list(self._sessions.keys())

    def has_session(self, ip: str) -> bool:
        return ip in self._sessions

    def session_count(self) -> int:
        return len(self._sessions)

    # ── Ping loop ────────────────────────────────────────────

    def start_ping(self, ip: str) -> None:
        if ip in self._ping_tasks:
            return
        task = asyncio.ensure_future(self._ping_loop(ip))
        self._ping_tasks[ip] = task

    def stop_ping(self, ip: str | None = None) -> None:
        if ip is None:
            return
        task = self._ping_tasks.pop(ip, None)
        if task and not task.done():
            task.cancel()

    def stop_all_pings(self) -> None:
        for ip in list(self._ping_tasks):
            self.stop_ping(ip)

    def set_ping_status(self, ip: str, status: str) -> None:
        self._ping_statuses[ip] = status
        self.ping_status_changed.emit(ip, status)

    def get_ping_status(self, ip: str) -> str | None:
        return self._ping_statuses.get(ip)

    @staticmethod
    async def _wait_task_done(task: asyncio.Task) -> None:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def _ping_loop(self, ip: str) -> None:
        interval = self._config.settings.connection.ping_interval
        try:
            while True:
                status = await self._do_ping(ip)
                self._ping_statuses[ip] = status
                self.ping_status_changed.emit(ip, status)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Ping loop ended for {ip}: {e}")

    async def _do_ping(self, ip: str) -> str:
        import socket

        def _tcp_ping(host: str) -> float | None:
            t0 = time.monotonic()
            try:
                sock = socket.create_connection((host, 22), timeout=1.5)
                sock.close()
                return (time.monotonic() - t0) * 1000
            except OSError:
                return None

        try:
            loop = asyncio.get_event_loop()
            elapsed = await loop.run_in_executor(None, _tcp_ping, ip)
            if elapsed is None:
                return "timeout"
            if elapsed < 300:
                return "ok"
            return "slow"
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"Ping error for {ip}: {e}")
            return "timeout"

    # ── VNC processes ────────────────────────────────────────

    def register_vnc(self, ip: str, proc: subprocess.Popen) -> None:
        self._vnc_procs[ip] = proc

    def kill_vnc(self, ip: str) -> None:
        proc = self._vnc_procs.pop(ip, None)
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                logger.info(f"VNC process terminated for {ip} (pid={proc.pid})")
        except Exception as e:
            logger.warning(f"Error terminating VNC for {ip}: {e}")

    def kill_all_vnc(self) -> None:
        for ip in list(self._vnc_procs.keys()):
            self.kill_vnc(ip)

    def move_vnc(self, old_ip: str, new_ip: str) -> None:
        if old_ip in self._vnc_procs:
            self._vnc_procs[new_ip] = self._vnc_procs.pop(old_ip)

    # ── Session persistence ──────────────────────────────────

    def save_sessions(self) -> None:
        sessions_file = get_sessions_file()
        ips = list(self._sessions.keys())
        try:
            sessions_file.write_text(json.dumps(ips, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    def restore_sessions(self) -> list[str]:
        sessions_file = get_sessions_file()
        if not sessions_file.exists():
            logger.debug("No sessions file found, skipping restore")
            return []
        try:
            data = json.loads(sessions_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            return [ip.strip() for ip in data if isinstance(ip, str) and ip.strip()]
        except Exception as e:
            logger.error(f"Failed to restore sessions: {e}")
            return []

    # ── Cleanup ──────────────────────────────────────────────

    def cleanup(self) -> None:
        self.kill_all_vnc()
