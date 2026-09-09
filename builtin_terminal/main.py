"""Точка входа вендоренного терминала: qasync-цикл + главное окно.

Терминал запускается ОТДЕЛЬНЫМ процессом (см. ssh_terminal_launcher.py):
собственный QApplication и event loop, потому что в общем цикле CashControl
он тормозил и тормозил приложение. Опциональные аргументы --host/--port/
--login/--password-stdin задают авто-подключение к кассе при старте.
Пароль передаётся первой строкой stdin (не в argv), чтобы не светиться
в списке процессов.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication

import qasync

_RUNTIME_ROOT = Path(__file__).resolve().parent
if str(_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_ROOT))

from ui.main_window import MainWindow

_LOG = logging.getLogger("ssh_term.main")

_FMT = "%(asctime)s %(name)s %(levelname)s: %(message)s"
_DATEFMT = "%H:%M:%S"


def _setup_logging() -> str | None:
    """Настроить лог: консоль (dev) или файл logs/ssh_terminal_<дата>.log.

    Под pythonw (нет консоли) logging.basicConfig пишет в DEVNULL — падение
    входа в терминал. Возвращает путь к файлу лога либо None (консоль).
    """
    root = logging.getLogger()
    tty = sys.stdout is not None and bool(getattr(sys.stdout, "isatty", lambda: False)())
    if tty:
        logging.basicConfig(level=logging.INFO, format=_FMT, datefmt=_DATEFMT)
        logging.getLogger("asyncssh").setLevel(logging.WARNING)
        return None
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"ssh_terminal_{date.today().isoformat()}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("asyncssh").setLevel(logging.WARNING)
    return str(path)


def _read_password_from_stdin() -> str | None:
    """Первая строка stdin = пароль (показывается в процессе как pipe)."""
    if sys.stdin is None:
        return None
    line = sys.stdin.readline()
    if not line:
        return None
    return line.rstrip("\r\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ssh_terminal",
        description="CashControl built-in SSH terminal (standalone process)",
    )
    parser.add_argument("--host", help="auto-connect SSH host")
    parser.add_argument("--port", type=int, default=22, help="SSH port")
    parser.add_argument("--login", help="SSH username")
    parser.add_argument("--name", help="profile/tab name")
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read password from the first stdin line (hidden from process list)",
    )
    args = parser.parse_args()

    log_path = _setup_logging()
    if log_path:
        _LOG.info("logging to %s", log_path)

    password = None
    if args.password_stdin:
        password = _read_password_from_stdin()
        _LOG.info("password via stdin: %s", "received" if password is not None else "empty")

    app = QApplication(sys.argv)
    app.setApplicationName("SshTerminal")
    app.setOrganizationName("SshTerminalPrototype")

    loop = qasync.QEventLoop(app)
    asyncio_loop = qasync.get_event_loop() if hasattr(qasync, "get_event_loop") else loop
    # qasync.QEventLoop() не делает asyncio.set_event_loop(self): без этого
    # ensure_future в session.start() планируется в голом ProactorEventLoop,
    # который никогда не запускается -> "зависшее подключение" без единого лога.
    asyncio.set_event_loop(asyncio_loop)
    with asyncio_loop:
        window = MainWindow()
        window.show()
        if args.host:
            from data.profiles import HostProfile

            profile = HostProfile(
                name=args.name or f"{args.login}@{args.host}",
                host=args.host,
                username=args.login,
                port=args.port,
                password=password,
            )
            window.new_connection(profile)
            _LOG.info("auto-connect started for %s:%s as %s", args.host, args.port, args.login)
        asyncio_loop.run_forever()

    return 0


if __name__ == "__main__":
    sys.exit(main())