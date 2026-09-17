"""Build portable CashControl distribution for Linux.

Target layout (portable tarball):
    CashControl/
    ├── run.sh                 launcher (bash, relative paths)
    ├── CashControl.desktop    .desktop file for the desktop
    ├── icon.png               128x128 PNG icon
    ├── version.txt
    ├── docs/  data/  logs/  commands/  collectors/  cash_types/  detection/
    └── runtime/
        ├── bin/python         system python symlink
        ├── lib/               site-packages (PySide6, deps)
        └── app/cashcontrol/   app source code

Usage: uv run python scripts/build_linux.py [--output DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_PKG = REPO_ROOT / "src" / "cashcontrol"
VENV_SP_FALLBACK = REPO_ROOT / ".venv" / "lib" / "python3.12" / "site-packages"
DEFAULT_OUT = REPO_ROOT / "dist" / "CashControl"
DEFAULT_TARBALL = REPO_ROOT / "dist" / "CashControl-linux-x86_64.tar.gz"

SKIP_PKGS = {
    "pip", "setuptools", "wheel", "pkg_resources", "__pycache__",
}
BIN_EXTS = {".so", ".pyd", ".dll"}
COPY_EXTS = {".py", ".pyw", ".json", ".png", ".svg", ".qss", ".txt", ".toml"}

HOT_FILES = [
    ("gui", ["toolbar.py"]),
    ("builtin/db_viewer", [
        "__init__.py",
        "constants.py", "formatting.py", "storage.py", "workers.py", "sql.py",
        "data_grid.py", "data_panel.py", "csv_import.py",
        "sql_console.py", "tables_panel.py", "widget.py",
    ]),
    ("builtin/vnc", ["vnc_preview.py"]),
    ("builtin/file_manager", [
        "__init__.py",
        "models.py", "backends.py", "service.py", "cli.py",
        "gui/__init__.py", "gui/dialogs.py", "gui/runtime.py",
        "gui/session.py", "gui/widgets.py", "gui/window.py",
    ]),
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


def log(msg: str) -> None:
    print(f"[build_linux] {msg}")


def _venv_sp() -> Path:
    """Resolve site-packages directory from the local venv."""
    if VENV_SP_FALLBACK.exists():
        return VENV_SP_FALLBACK
    # Fallback: pip install into current venv
    import importlib.util
    spec = importlib.util.find_spec("PySide6")
    if spec and spec.origin:
        return Path(spec.origin).parent.parent
    raise FileNotFoundError("Cannot find site-packages. Run: uv sync")


def sync_version() -> str:
    script = REPO_ROOT / "scripts" / "sync_version.py"
    if script.exists():
        subprocess.run([sys.executable, str(script)], check=True, cwd=REPO_ROOT)
    version = (REPO_ROOT / "version.txt").read_text(encoding="utf-8").strip()
    return version


def clean_out(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)


def find_system_python() -> Path:
    """Find system python3 binary."""
    candidates = [
        Path("/usr/bin/python3.12"),
        Path("/usr/bin/python3.11"),
        Path("/usr/bin/python3"),
    ]
    for p in candidates:
        if p.exists():
            return p
    # Check PATH
    result = shutil.which("python3")
    if result:
        return Path(result)
    raise FileNotFoundError("No python3 found in system or PATH")


def install_runtime_python(out: Path, sys_python: Path) -> None:
    """Create runtime/bin/python symlink to system python."""
    py_dir = out / "runtime" / "bin"
    py_dir.mkdir(parents=True)
    # Symlink to system python
    target = sys_python.resolve()
    symlink = py_dir / "python"
    if symlink.exists() or symlink.is_symlink():
        symlink.unlink()
    symlink.symlink_to(target)
    log(f"python symlink: {symlink} -> {target}")


def _has_binaries(path: Path) -> bool:
    if path.is_file():
        return path.suffix.lower() in BIN_EXTS
    return any(item.suffix.lower() in BIN_EXTS for item in path.rglob("*"))


def install_deps(out: Path) -> tuple[list[str], list[str]]:
    """Copy deps from venv site-packages into runtime/lib/."""
    sp = _venv_sp()
    lib_dir = out / "runtime" / "lib"
    lib_dir.mkdir(parents=True)
    binaries: list[str] = []
    pure: list[str] = []

    for entry in sorted(sp.iterdir()):
        name = entry.name
        if name.lower() in SKIP_PKGS or name.endswith(".dist-info"):
            continue
        if _has_binaries(entry):
            dest = lib_dir / name
            if entry.is_dir():
                shutil.copytree(entry, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(entry, dest)
            binaries.append(name)
        else:
            dest = lib_dir / name
            if entry.is_dir():
                shutil.copytree(entry, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(entry, dest)
            pure.append(name)

    log(f"binary pkgs: {len(binaries)}, pure pkgs: {len(pure)}")
    return binaries, pure


def _rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def prune_runtime(out: Path) -> None:
    """Drop Qt modules and dev artifacts the app never loads."""
    lib = out / "runtime" / "lib"
    for pkg in lib.iterdir():
        if not pkg.is_dir():
            continue
        for cache in list(pkg.rglob("__pycache__")):
            _rmtree(cache)
        for tests in list(pkg.rglob("tests")):
            if tests.is_dir():
                _rmtree(tests)

    pyside = lib / "PySide6"
    if not pyside.is_dir():
        return

    KEEP_QT_LIBS = {"Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Network", "Qt6Svg",
                    "Qt6Concurrent", "Qt6OpenGL", "Qt6Xml", "Qt6SvgWidgets"}
    KEEP_QT_MODULES = {"QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtSvg",
                       "QtXml", "QtSvgWidgets"}
    KEEP_PLUGINS = {"platforms", "imageformats", "iconengines", "styles"}

    for d in ("qml", "metatypes", "include", "doc", "glue", "scripts",
              "__pycache__"):
        _rmtree(pyside / d)
    for f in list(pyside.glob("*.so*")):
        name = f.stem
        if name.endswith(".abi3"):
            continue
        if name not in KEEP_QT_LIBS:
            f.unlink()

    for d in list(pyside.rglob("plugins")):
        if d.is_dir():
            for sub in list(d.iterdir()):
                if sub.is_dir() and sub.name not in KEEP_PLUGINS:
                    _rmtree(sub)

    log("runtime pruned")


def _app_ignore(directory: str, names: list[str]) -> list[str]:
    """Exclude __pycache__ and dev artifacts from built-in terminal."""
    src = Path(directory)
    ignored = {n for n in names if n == "__pycache__"}
    if src.name == "terminal":
        ignored |= {n for n in names if n in {"README.md", "requirements.txt",
                                               "run.bat", "run.sh", "logs"}}
    if src.name == "data" and "app" in names:
        ignored.add("app")
    return sorted(ignored)


def copy_app_code(out: Path) -> None:
    app_pkg = out / "runtime" / "app" / "cashcontrol"
    shutil.copytree(SRC_PKG, app_pkg, ignore=_app_ignore)
    log(f"app code -> {app_pkg}")


def build_modules_overlay(out: Path) -> None:
    """Build modules/ for hot-reload."""
    modules = out / "modules"
    for rel_dir, files in HOT_FILES:
        target = modules / rel_dir
        target.mkdir(parents=True, exist_ok=True)
        src_dir = SRC_PKG / rel_dir
        for fname in files:
            f = src_dir / fname
            if not f.exists():
                continue
            dst = target / fname
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
    layouts_src = SRC_PKG / "gui" / "widgets" / "keyboard_layouts"
    if layouts_src.exists():
        dst = modules / "gui" / "widgets" / "keyboard_layouts"
        dst.mkdir(parents=True, exist_ok=True)
        for f in layouts_src.glob("*.json"):
            shutil.copy2(f, dst / f.name)
    log("modules/ overlay built")


def _soft_ignore(_d, names):
    """Exclude KiTTY user data from dist."""
    return {n for n in names if n in {"SshHostKeys", "Sessions", "Proxies",
                                       "reinstall", "kitty.ini", "PUTTY.RND"}}


def copy_user_content(out: Path) -> None:
    shutil.copy2(REPO_ROOT / "version.txt", out / "version.txt")
    # Try to copy icon (PNG preferred on Linux, fallback to ICO)
    icon_src = SRC_PKG / "gui" / "resources" / "icon.png"
    icon_ico = SRC_PKG / "gui" / "resources" / "icon.ico"
    if icon_src.exists():
        shutil.copy2(icon_src, out / "icon.png")
    elif icon_ico.exists():
        shutil.copy2(icon_ico, out / "icon.png")
    docs_src = REPO_ROOT / "docs"
    if docs_src.exists():
        shutil.copytree(docs_src, out / "docs")
    for d in ("commands", "collectors", "cash_types", "detection"):
        src = REPO_ROOT / d
        if src.exists():
            shutil.copytree(src, out / "defaults" / d)
    soft_src = REPO_ROOT / "soft"
    if soft_src.exists():
        shutil.copytree(soft_src, out / "soft", ignore=_soft_ignore)
    for d in ("data", "logs"):
        (out / d).mkdir(exist_ok=True)
    log("root content copied")


def write_launcher_sh(out: Path) -> None:
    """Write run.sh launcher."""
    (out / "run.sh").write_text(
        '#!/bin/bash\n'
        'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'exec "$DIR/runtime/bin/python" \\\n'
        '    "$DIR/runtime/app/cashcontrol/main.py" \\\n'
        '    "$@"\n',
        encoding="utf-8",
    )
    # Make executable
    import os
    os.chmod(str(out / "run.sh"), 0o755)
    log("launcher written: run.sh")


def write_desktop(out: Path, version: str) -> None:
    """Write .desktop file."""
    (out / "CashControl.desktop").write_text(
        f'[Desktop Entry]\n'
        f'Name=CashControl\n'
        f'Comment=POS terminal management for SetRetail\n'
        f'Exec={out}/run.sh\n'
        f'Icon={out}/icon.png\n'
        f'Type=Application\n'
        f'Categories=Utility;\n'
        f'Keywords=SSH;POS;cashier;\n'
        f'X-KDE-StartupNotify=false\n',
        encoding="utf-8",
    )
    log(f"desktop file written: CashControl.desktop")


def purge_user_data(out: Path) -> None:
    """Remove user data artifacts."""
    for d in ("data", "logs"):
        target = out / d
        if target.is_dir():
            for f in target.iterdir():
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink()
            log(f"purged {d}/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--tarball", type=Path, default=DEFAULT_TARBALL,
                        help="Path to output tarball (default: dist/CashControl-linux-x86_64.tar.gz)")
    args = parser.parse_args()

    version = sync_version()
    log(f"building CashControl v{version} (Linux x86_64)")

    # Find system Python
    sys_python = find_system_python()
    log(f"using system python: {sys_python}")

    clean_out(args.output)
    install_runtime_python(args.output, sys_python)
    install_deps(args.output)
    prune_runtime(args.output)
    copy_app_code(args.output)
    build_modules_overlay(args.output)
    copy_user_content(args.output)
    write_launcher_sh(args.output)
    write_desktop(args.output, version)
    purge_user_data(args.output)
    log(f"layout ready: {args.output}")

    # Create tarball
    with tarfile.open(str(args.tarball), "w:gz") as tf:
        tf.add(str(args.output), arcname="CashControl")
    size_mb = args.tarball.stat().st_size / (1024 * 1024)
    log(f"TARBALL DONE: {args.tarball} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
