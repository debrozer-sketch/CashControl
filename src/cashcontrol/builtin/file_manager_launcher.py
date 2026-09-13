"""Integration of the built-in Remote Files manager (file_manager package).

Unlike the vendored SSH terminal, the file manager runs IN-PROCESS as a
separate top-level window.  It spins up its own asyncio loop on a worker
thread (see ``remote_files.gui.runtime.AsyncExecutor``), so SSH I/O never
contends with the application's qasync loop.

Fallback contract matches the other built-in tools: the external WinSCP is
used only when a client path is explicitly configured and the executable
exists; otherwise (or when the path is stale) the built-in manager opens.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cashcontrol.infrastructure.audit_logger import audit_log

logger = logging.getLogger("cashcontrol.builtin.file_manager")


def should_use_builtin_files(winscp_path: str | None) -> bool:
    """True when no external WinSCP is configured or its file is missing."""
    if not winscp_path or not winscp_path.strip():
        return True
    return not Path(winscp_path).expanduser().is_file()


def builtin_file_manager_root() -> Path:
    """Location of the in-process file manager package."""
    return Path(__file__).resolve().parent / "file_manager"


def file_manager_available() -> bool:
    """True when the built-in package is present in this distribution."""
    return (builtin_file_manager_root() / "gui" / "window.py").is_file()


def open_file_manager(
    host: str,
    port: int,
    login: str,
    password: str | None,
    start_dir: str = "/",
    protocol: str = "auto",
    parent: Any = None,
) -> Any | None:
    """Open (or raise) the built-in file manager window for a host.

    One window is reused per host/port pair; it stays top-level and
    independent of the main CashControl window.
    """
    from cashcontrol.builtin.file_manager.gui.window import RemoteFilesWindow
    from cashcontrol.gui.app_icon import apply_window_icon

    key = (host, int(port or 22))
    win = _windows.get(key)
    if win is None:
        win = RemoteFilesWindow(
            parent=parent,
            host=host,
            port=port,
            username=login,
            password=password,
            start_dir=start_dir,
            protocol=protocol,
        )
        apply_window_icon(win)
        _windows[key] = win
        win.destroyed.connect(lambda _key=key: _windows.pop(_key, None))

    win.show()
    win.raise_()
    win.activateWindow()

    audit_log(action_type="tool", action_name="file_manager", target=host, result="success")
    logger.info("Opened built-in file manager for %s:%s as %s", host, port, login)
    return win


_windows: dict[tuple[str, int], Any] = {}
