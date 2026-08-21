from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

# ── Cash types ────────────────────────────────────────────────────────────

MOVER_CASH_TYPES = ("pos", "touch", "sco3")
REINSTALL_CASH_TYPES = ("pos", "touch", "sco3")


# ── Environment ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _is_production() -> bool:
    """True when running from a compiled (Nuitka/frozen) build."""
    if getattr(sys, "frozen", False):
        return True
    try:
        import __compiled__  # noqa: F401  # Nuitka marker
        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def get_app_root() -> Path:
    if _is_production():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent.parent


# ── Base directories ──────────────────────────────────────────────────────

def get_data_dir() -> Path:
    d = get_app_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_logs_dir() -> Path:
    d = get_app_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_soft_dir() -> Path:
    d = get_app_root() / "soft"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_commands_dir() -> Path:
    d = get_app_root() / "commands"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_collectors_dir() -> Path:
    return get_app_root() / "collectors"


# ── Files ─────────────────────────────────────────────────────────────────

def get_sessions_file() -> Path:
    return get_data_dir() / "sessions.json"


def get_config_file() -> Path:
    return get_data_dir() / "settings.json"


def get_keystore_file() -> Path:
    return get_data_dir() / ".keystore"


def get_port_mapping_file() -> Path:
    return get_data_dir() / "port_mapping.json"


def get_usb_mapping_file() -> Path:
    return get_data_dir() / "usb_id_mapping.json"


# ── Mover ─────────────────────────────────────────────────────────────────

def get_mover_data_dir() -> Path:
    d = get_app_root() / "mover" / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_mover_files_dir() -> Path:
    d = get_app_root() / "mover" / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_mover_scenarios_dir() -> Path:
    d = get_app_root() / "mover" / "scenarios"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_mover_dirs() -> None:
    get_mover_data_dir()
    get_mover_files_dir()
    get_mover_scenarios_dir()


# ── Reinstall ─────────────────────────────────────────────────────────────

def get_reinstall_dir() -> Path:
    d = get_app_root() / "reinstall"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_reinstall_type_dir(cash_type: str) -> Path:
    d = get_reinstall_dir() / cash_type
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_reinstall_dirs() -> None:
    for ct in REINSTALL_CASH_TYPES:
        get_reinstall_type_dir(ct)
