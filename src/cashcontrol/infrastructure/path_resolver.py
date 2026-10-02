from __future__ import annotations

import contextlib
import os
import platform
import sys
from functools import lru_cache
from pathlib import Path

# ── Environment ───────────────────────────────────────────────────────────

def _runtime_layout_root() -> Path | None:
    """Program root for the packaged runtime layout.

    Windows: <root>/runtime/python/<python.exe>, with version.txt + runtime/ at
    <root>.
    Linux:   <root>/runtime/bin/python (same version.txt + runtime/ layout).

    Returns None outside such a layout.
    """
    exe_dir = Path(sys.executable).parent
    # Windows layout: …/runtime/python/python.exe → parent.parent = root
    candidate = exe_dir.parent.parent
    if (candidate / "version.txt").exists() and (candidate / "runtime").exists():
        return candidate
    # Linux layout: …/runtime/bin/python → parent.parent = root
    if exe_dir.name == "bin":
        candidate = exe_dir.parent.parent
        if (candidate / "version.txt").exists() and (candidate / "runtime").exists():
            return candidate
    return None


_dll_dirs_done = False


def _add_runtime_dll_dirs(root: Path) -> None:
    """Make native deps (pywin32_system32, *.libs, …) resolvable on Windows."""
    global _dll_dirs_done
    if _dll_dirs_done:
        return
    if platform.system() != "Windows":
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


def find_soft_program(*candidates: str, directory: Path | None = None) -> Path | None:
    """Find an external client among the files shipped in ``soft/``.

    Candidates are tried in order. The match ignores case and tolerates a
    missing or an extra extension, so ``kitty`` also matches ``kitty.exe``.
    That keeps one set of names working on both Windows and Linux instead
    of hardcoding an extension per platform.

    ``directory`` exists for tests; production callers omit it and get
    :func:`get_soft_dir`.
    """
    folder = Path(directory) if directory is not None else get_soft_dir()
    if not folder.is_dir():
        return None
    try:
        files = {p.name.lower(): p for p in folder.iterdir() if p.is_file()}
    except OSError:
        return None
    for name in candidates:
        stem = name.rpartition(".")[0] or name
        for variant in (name, stem + ".exe", stem):
            hit = files.get(variant.lower())
            if hit is not None:
                return hit
    return None


def get_commands_dir() -> Path:
    d = get_app_root() / "commands"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_collectors_dir() -> Path:
    return get_app_root() / "collectors"


def get_cash_types_dir() -> Path:
    d = get_app_root() / "cash_types"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_detection_dir() -> Path:
    return get_app_root() / "detection"


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


def open_in_explorer(path: Path | str) -> bool:
    """Открыть файл или папку в Проводнике.

    Используется после сбора архива, чтобы результат сразу был под рукой.
    Основной путь — os.startfile. Под pythonw.exe он доступен, но если
    вызов не сработал, остаётся запасной вариант через сам Проводник.

    Returns:
        True, если путь передан оболочке.
    """
    target = str(path)
    try:
        if sys.platform == "win32":
            try:
                os.startfile(target)
                return True
            except OSError:
                import subprocess

                subprocess.Popen(
                    ["explorer", target],
                    shell=False,
                    creationflags=0x08000000,
                )
                return True
        import subprocess

        subprocess.Popen(["xdg-open", target])
        return True
    except Exception as exc:
        from cashcontrol.infrastructure.audit_logger import get_logger

        get_logger().warning("Не удалось открыть %s: %s", target, exc)
        return False
