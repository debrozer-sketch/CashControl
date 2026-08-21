from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOGGER: logging.Logger | None = None


def get_logger(name: str = "cashcontrol") -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    from cashcontrol.infrastructure.path_resolver import get_logs_dir
    log_dir = get_logs_dir()
    log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"

    _LOGGER = logging.getLogger(name)
    _LOGGER.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    ff = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    fh.setFormatter(ff)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sf = logging.Formatter("\x1b[32m%(asctime)s\x1b[0m | \x1b[1m%(levelname)-8s\x1b[0m | \x1b[1m%(message)s\x1b[0m")
    sh.setFormatter(sf)

    _LOGGER.addHandler(fh)
    _LOGGER.addHandler(sh)

    _LOGGER.info("Logger initialized")
    return _LOGGER


def setup_logger() -> logging.Logger:
    """Initialize application logging. Idempotent."""
    return get_logger()


_audit_logger: logging.Logger | None = None


def get_audit_logger() -> logging.Logger:
    global _audit_logger
    if _audit_logger is not None:
        return _audit_logger

    from cashcontrol.infrastructure.path_resolver import get_logs_dir
    log_dir = get_logs_dir()
    audit_file = log_dir / "audit.log"

    _audit_logger = logging.getLogger("audit")
    _audit_logger.setLevel(logging.INFO)

    fh = logging.FileHandler(audit_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    ff = logging.Formatter("%(asctime)s | %(message)s")
    fh.setFormatter(ff)
    _audit_logger.addHandler(fh)
    _audit_logger.propagate = False
    return _audit_logger


def audit_log(action_type: str, action_name: str, target: str = "", result: str = "", detail: str = "", **extra: Any) -> None:
    try:
        al = get_audit_logger()
        parts = [action_type, action_name]
        if target:
            parts.append(f"target={target}")
        if result:
            parts.append(f"result={result}")
        if detail:
            parts.append(f"detail={detail}")
        for k, v in extra.items():
            parts.append(f"{k}={v}")
        al.info(" | ".join(parts))
    except Exception:
        pass
