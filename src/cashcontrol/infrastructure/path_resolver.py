from __future__ import annotations

import contextlib
import os
import sys
from functools import lru_cache
from pathlib import Path

# ── Environment ───────────────────────────────────────────────────────────

def _runtime_layout_root() -> Path | None:
    """Program root for the packaged runtime layout (gap_report §8.2):
    <root>/runtime/python/<python.exe>, with version.txt + runtime/ at <root>.
    Returns None outside such a layout."""
    exe_dir = Path(sys.executable).parent      # .../CashControl/runtime/python
    candidate = exe_dir.parent.parent          # .../CashControl
    if (candidate / "version.txt").exists() and (candidate / "runtime").exists():
        return candidate
    return None


_dll_dirs_done = False


def _add_runtime_dll_dirs(root: Path) -> None:
    """Make native deps (pywin32_system32, *.libs, ...) resolvable from runtime/lib."""
    global _dll_dirs_done
    if _dll_dirs_done:
        return
    _dll_dirs_done = True
    lib = root / "runtime" / "lib"
    if not lib.is_dir():
        return
    os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
    candidates = [lib, *(p for p in lib.iterdir() if p.is_dir())]
    for d in candidates:
        if hasattr(os, "add_dll_directory"):
            with contextlib.suppress(OSError):
                os.add_dll_directory(d)


@lru_cache(maxsize=1)
def _is_production() -> bool:
    """True for installed builds: Nuitka-compiled, frozen or packaged runtime layout."""
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
    if (exe_dir / "version.txt").exists() or (exe_dir / "modules").exists():
        return True
    return _runtime_layout_root() is not None


@lru_cache(maxsize=1)
def get_app_root() -> Path:
    root = _runtime_layout_root()
    if root is not None:
        _add_runtime_dll_dirs(root)
        return root
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
