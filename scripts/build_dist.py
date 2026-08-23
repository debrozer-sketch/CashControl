"""Build portable CashControl distribution (layout per gap_report §8.2).

Target layout:
    CashControl/
    ├── CashControl.cmd          launcher (pythonw, relative paths)
    ├── version.txt
    ├── icon.ico
    ├── docs/  data/  logs/  commands/  collectors/  soft/  modules/
    └── runtime/
        ├── python/              embedded CPython + stdlib
        ├── lib/site-packages.zip   pure-python deps (single zip)
        ├── lib/<pkg>/           packages with binary extensions
        └── app/cashcontrol/     program code (.py files)

Usage: uv run python scripts/build_dist.py [--output DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_PKG = REPO_ROOT / "src" / "cashcontrol"
VENV_SP = REPO_ROOT / ".venv" / "Lib" / "site-packages"
CACHE_DIR = REPO_ROOT / ".build_cache"
DEFAULT_OUT = REPO_ROOT / "dist" / "CashControl"

PY_VERSION = "3.12.10"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"

SKIP_PKGS = {
    "pip", "setuptools", "wheel", "pkg_resources", "__pycache__",
    "_distutils_hack", "loguru", "win32_setctime",
}
BIN_EXTS = {".pyd", ".dll", ".so"}
COPY_EXTS = {".py", ".pyw", ".json", ".ico", ".png", ".svg", ".qss", ".txt", ".toml"}

HOT_FILES = [
    ("gui", ["toolbar.py", "vnc_preview.py", "db_viewer_widget.py"]),
    ("gui/dialogs", [
        "command_editor.py", "command_result_dialog.py", "logs_viewer.py",
        "help_dialog.py", "alias_editor.py", "add_cash_dialog.py",
    ]),
    ("gui/dialogs/settings", [
        "settings_dialog.py", "tab_connection.py", "tab_general.py",
        "tab_logs.py", "tab_programs.py",
    ]),
    ("gui/widgets", [
        "info_section_widget.py", "virtual_keyboard.py",
    ]),
]

PTH_CONTENT = """python312.zip
.
..\\lib
..\\lib\\site-packages.zip
..\\lib\\win32
..\\lib\\win32\\lib
..\\app
"""


def log(msg: str) -> None:
    print(f"[build_dist] {msg}")


def sync_version() -> str:
    script = REPO_ROOT / "scripts" / "sync_version.py"
    subprocess.run([sys.executable, str(script)], check=True, cwd=REPO_ROOT)
    version = (REPO_ROOT / "version.txt").read_text(encoding="utf-8").strip()
    return version


def clean_out(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)


def ensure_embedded_python(cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / f"python-{PY_VERSION}-embed-amd64.zip"
    if not zip_path.exists():
        log(f"downloading {EMBED_URL}")
        urllib.request.urlretrieve(EMBED_URL, zip_path)
    return zip_path


def install_runtime_python(out: Path) -> None:
    py_dir = out / "runtime" / "python"
    py_dir.mkdir(parents=True)
    with zipfile.ZipFile(ensure_embedded_python(CACHE_DIR)) as zf:
        zf.extractall(py_dir)
    pth_file = py_dir / f"python{PY_VERSION.rpartition('.')[0].replace('.', '')}._pth"
    pth_file.write_text(PTH_CONTENT, encoding="utf-8")
    log(f"embedded python -> {py_dir}")


def has_binaries(path: Path) -> bool:
    if path.is_file():
        return path.suffix.lower() in BIN_EXTS
    return any(item.suffix.lower() in BIN_EXTS for item in path.rglob("*"))


def install_deps(out: Path) -> tuple[list[str], list[str]]:
    lib_dir = out / "runtime" / "lib"
    lib_dir.mkdir(parents=True)
    zip_path = lib_dir / "site-packages.zip"
    binaries: list[str] = []
    pure: list[str] = []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(VENV_SP.iterdir()):
            name = entry.name
            if name.lower() in SKIP_PKGS or name.endswith(".dist-info"):
                continue
            if has_binaries(entry):
                dest = lib_dir / name
                if entry.is_dir():
                    shutil.copytree(entry, dest)
                else:
                    shutil.copy2(entry, dest)
                binaries.append(name)
            else:
                if entry.is_dir():
                    for f in entry.rglob("*"):
                        if f.is_file() and f.suffix != ".pyc":
                            zf.write(f, f.relative_to(VENV_SP))
                else:
                    zf.write(entry, name)
                pure.append(name)

    log(f"binary pkgs: {len(binaries)}, pure pkgs: {len(pure)}")
    return binaries, pure


def place_win32_dlls(out: Path) -> None:
    src = out / "runtime" / "lib" / "pywin32_system32"
    dst = out / "runtime" / "python"
    if not src.is_dir():
        return
    for f in src.glob("*.dll"):
        shutil.copy2(f, dst / f.name)


def copy_app_code(out: Path) -> None:
    app_pkg = out / "runtime" / "app" / "cashcontrol"

    def ignore(directory: str, names: list[str]) -> list[str]:
        return [n for n in names if n == "__pycache__"]

    shutil.copytree(SRC_PKG, app_pkg, ignore=ignore)
    log(f"app code -> {app_pkg}")


def build_modules_overlay(out: Path) -> None:
    modules = out / "modules"
    for rel_dir, files in HOT_FILES:
        target = modules / rel_dir
        target.mkdir(parents=True, exist_ok=True)
        src_dir = SRC_PKG / rel_dir
        for fname in files:
            f = src_dir / fname
            if f.exists():
                shutil.copy2(f, target / fname)
    layouts_src = SRC_PKG / "gui" / "widgets" / "keyboard_layouts"
    if layouts_src.exists():
        dst = modules / "gui" / "widgets" / "keyboard_layouts"
        dst.mkdir(parents=True, exist_ok=True)
        for f in layouts_src.glob("*.json"):
            shutil.copy2(f, dst / f.name)
    log("modules/ overlay built")


def copy_user_content(out: Path) -> None:
    (REPO_ROOT / "version.txt").read_bytes()
    shutil.copy2(REPO_ROOT / "version.txt", out / "version.txt")
    icon = SRC_PKG / "gui" / "resources" / "icon.ico"
    if icon.exists():
        shutil.copy2(icon, out / "icon.ico")
    for d in ("docs", "commands", "collectors", "soft"):
        src = REPO_ROOT / d
        if src.exists():
            shutil.copytree(src, out / d)
    for d in ("data", "logs"):
        (out / d).mkdir(exist_ok=True)
    log("root content copied")


LAUNCHER_CMD = """@echo off
start "" "%~dp0runtime\\python\\pythonw.exe" "%~dp0runtime\\app\\cashcontrol\\main.py"
"""


def write_launcher(out: Path) -> None:
    (out / "CashControl.cmd").write_text(LAUNCHER_CMD, encoding="utf-8")
    log("launcher written")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not VENV_SP.exists():
        print(f"ERROR: venv site-packages not found: {VENV_SP}", file=sys.stderr)
        return 1

    version = sync_version()
    log(f"building CashControl v{version}")
    clean_out(args.output)
    install_runtime_python(args.output)
    install_deps(args.output)
    place_win32_dlls(args.output)
    copy_app_code(args.output)
    build_modules_overlay(args.output)
    copy_user_content(args.output)
    write_launcher(args.output)
    log(f"DONE: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
