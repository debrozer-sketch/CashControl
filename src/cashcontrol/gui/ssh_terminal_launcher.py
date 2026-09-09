"""Integration of the built-in SSH terminal (vendored as builtin_terminal/).

The terminal is launched as a SEPARATE process (pythonw + builtin_terminal/
main.py) — the same pattern as the external KiTTY/WinSCP tools — instead of
being embedded into the CashControl event loop. This gives the terminal its
own QApplication, qasync event loop and top-level window, so its parsing/paint
floods and the app's SSH pings/collectors can no longer stall each other.

Connection parameters are passed via CLI arguments; the password is piped via
stdin (first line), so it never appears in the process list.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from cashcontrol.infrastructure.audit_logger import audit_log
from cashcontrol.infrastructure.path_resolver import get_app_root

logger = logging.getLogger("cashcontrol.gui.ssh_terminal")

_CREATE_NO_WINDOW = 0x08000000


def builtin_terminal_root() -> Path:
    """App-root resolved location of the vendored terminal (dev == repo root)."""
    return get_app_root() / "builtin_terminal"


def should_use_builtin_ssh(client_path: str | None) -> bool:
    """True if no external SSH client is configured or its file is missing.

    Matches the intended UX: an unset path or a stale path that no longer
    points to a real file both fall back to the built-in terminal.
    """
    if not client_path or not client_path.strip():
        return True
    return not Path(client_path).exists()


def terminal_python() -> str:
    """Interpreter for the child process: pythonw when available.

    The packaged app runs under runtime/python/pythonw.exe; in dev python.exe
    is used — switch to its pythonw sibling to avoid a flash of console window.
    """
    exe = sys.executable
    if Path(exe).name.lower() == "python.exe":
        w = Path(exe).with_name("pythonw.exe")
        if w.is_file():
            return str(w)
    return exe


def build_terminal_command(host: str, port: int, login: str, password_stdin: bool) -> list[str]:
    """Command to spawn the terminal subprocess (pure, testable)."""
    return [
        terminal_python(),
        str(builtin_terminal_root() / "main.py"),
        "--host",
        str(host),
        "--port",
        str(port),
        "--login",
        str(login),
        *(["--password-stdin"] if password_stdin else []),
    ]


def launch_builtin_terminal(
    host: str,
    port: int,
    login: str,
    password: str | None,
    parent=None,
    ) -> subprocess.Popen | None:
    """Open the built-in SSH terminal as a separate process and auto-connect.

    `parent` is kept for API compatibility; the terminal is an independent
    top-level window, so no Qt parenting is applied.
    """
    main_py = builtin_terminal_root() / "main.py"
    if not main_py.is_file():
        logger.warning("Built-in SSH terminal not found at %s", main_py)
        return None

    use_password = password is not None
    cmd = build_terminal_command(host, port, login, use_password)

    log_dir = main_py.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    err_handle = (log_dir / "ssh_terminal_child_stderr.log").open("ab")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(main_py.parent),
            creationflags=_CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=err_handle,
            stdin=subprocess.PIPE if use_password else None,
        )
    except Exception as e:  # pragma: no cover - defensive, subprocess spawn
        err_handle.close()
        logger.exception("Built-in SSH terminal launch failed: %s", e)
        return None

    if use_password and proc.stdin is not None:
        try:
            proc.stdin.write((password + "\n").encode("utf-8"))
            proc.stdin.close()
        except OSError as e:
            logger.warning("Failed to pass password to terminal process: %s", e)
            return None

    audit_log(action_type="tool", action_name="ssh_client", target=host, result="success")
    logger.info("Opened built-in SSH terminal for %s:%s as %s", host, port, login)
    return proc
