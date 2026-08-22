from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path


# ── Environment ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _is_production() -> bool:
    """True for installed builds: Nuitka-compiled or packaged runtime layout."""
    if getattr(sys, "frozen", False):
        return True
    if "__compiled__" in globals():  # Nuitka marker (per compiled module)
        return True
    try:
        import __compiled__  # noqa: F401  # Nuitka marker, importable variant
        return True
    except ImportError:
        pass
    exe_dir = Path(sys.executable).parent  # installed non-frozen layout
    return (exe_dir / "version.txt").exists() or (exe_dir / "modules").exists()


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
