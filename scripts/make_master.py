"""
make_master.py — Build master image and generate manifest.json for CashControl updates.

Usage:
    python scripts/make_master.py --output \\\\server\\share\\CashControl
    python scripts/make_master.py --output \\\\server\\share\\CashControl --manifest-only

Classification (hot vs cold):
    - commands/, styles/, modules/ → hot
    - everything else → cold

Modes:
    --manifest-only      Recalculate manifest.json, don't copy files.
    --modules-only       Copy only hot module files to output/modules/ and
                         recalculate manifest. Does NOT touch version.txt
                         or core files. For fast hot-fix releases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

# ── Single source of truth: hot_prefixes.json ──
_HOT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "src" / "cashcontrol" / "infrastructure" / "hot_prefixes.json"
_HOT_FS_PREFIXES: frozenset[str] = frozenset()
if _HOT_CONFIG_PATH.exists():
    _data = json.loads(_HOT_CONFIG_PATH.read_text(encoding="utf-8"))
    _HOT_FS_PREFIXES = frozenset(_data.get("hot_fs_prefixes", []))
else:
    print(f"WARNING: {_HOT_CONFIG_PATH} not found — all files classified as cold")


def _load_hot_package_prefixes() -> list[str]:
    """Load hot package prefixes from hot_prefixes.json."""
    if _HOT_CONFIG_PATH.exists():
        data = json.loads(_HOT_CONFIG_PATH.read_text(encoding="utf-8"))
        return data.get("hot_package_prefixes", [])
    return []


_HOT_PACKAGE_PREFIXES = _load_hot_package_prefixes()
_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def _collect_module_files(module_name: str) -> list[tuple[Path, str]]:
    """Given a module name, return [(source_path, target_rel_path), ...].

    target_rel_path is relative to modules/ inside the output directory.
    For example: ('gui/toolbar.py', 'gui/dialogs/settings/__init__.py')
    """
    rel = module_name[len("cashcontrol."):]  # 'gui.toolbar', 'gui.dialogs.settings'
    rel_path = rel.replace(".", "/")  # 'gui/toolbar', 'gui/dialogs/settings'
    base = _SRC_ROOT / "cashcontrol" / rel_path

    results: list[tuple[Path, str]] = []

    py_path = base.with_suffix(".py")
    if py_path.is_file():
        # Single-file module: cashcontrol.gui.toolbar -> gui/toolbar.py
        results.append((py_path, f"{rel_path}.py"))

    init_path = base / "__init__.py"
    if init_path.exists():
        # Package module: cashcontrol.gui.dialogs.settings -> gui/dialogs/settings/*.py
        for py_file in sorted(base.rglob("*.py")):
            rel = py_file.relative_to(base)
            target = f"{rel_path}/{rel.as_posix()}"
            results.append((py_file, target))

    if not results:
        print(f"  WARNING: source not found for {module_name} (tried {py_path} and {base}/)")

    return results


def _copy_modules(output_dir: Path) -> int:
    """Copy hot module files from src/ to output_dir/modules/.

    Returns number of files copied.
    """
    modules_target = output_dir / "modules"
    if not modules_target.exists():
        print(f"ERROR: {modules_target} does not exist in the output directory.")
        print("Run make_master.bat (full copy) at least once first.")
        sys.exit(1)

    count = 0
    for module_name in _HOT_PACKAGE_PREFIXES:
        files = _collect_module_files(module_name)
        for source, rel_target in files:
            dest = modules_target / rel_target
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            count += 1
            print(f"  {source.name} -> {dest.relative_to(output_dir).as_posix()}")

    return count


def _classify(rel_path: str) -> str:
    """Classify a relative path as 'hot' or 'cold'."""
    rel = rel_path.replace("\\", "/")
    for prefix in _HOT_FS_PREFIXES:
        if rel.startswith(prefix):
            return "hot"
    return "cold"


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file.
    Must produce the same result as cc-updater/hash.go:computeSHA256.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_manifest(output_dir: Path) -> dict:
    """Walk output_dir and build manifest data."""
    version_file = output_dir / "version.txt"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "unknown"

    manifest_version = version
    manifest_description = f"CashControl {version}"

    files = []
    # Collect all files, sorted for reproducibility
    all_files = sorted(output_dir.rglob("*"))

    for fpath in all_files:
        if not fpath.is_file():
            continue
        rel = fpath.relative_to(output_dir).as_posix()

        # Skip manifest itself, .pending_update, and temp files
        if rel == "manifest.json":
            continue
        if rel.startswith("."):
            continue
        if rel.endswith(".tmp"):
            continue
        if rel.startswith("logs/"):
            continue

        file_size = fpath.stat().st_size
        file_sha = sha256_file(fpath)
        reload_type = _classify(rel)

        files.append({
            "path": rel,
            "sha256": file_sha,
            "size": file_size,
            "reload": reload_type,
        })

    return {
        "version": manifest_version,
        "description": manifest_description,
        "files": files,
    }


def write_manifest(manifest: dict, output_dir: Path) -> None:
    """Write manifest.json to output_dir."""
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Manifest written: {manifest_path} ({len(manifest['files'])} files)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build CashControl master image and/or manifest"
    )
    parser.add_argument(
        "--output", required=True,
        help="Target directory (master image path)",
    )
    parser.add_argument(
        "--manifest-only", action="store_true",
        help="Only recalculate manifest, don't copy files",
    )
    parser.add_argument(
        "--source", default=None,
        help="Source directory to copy from (default: dist/CashControl)",
    )
    parser.add_argument(
        "--modules-only", action="store_true",
        help="Copy only hot module files (toolbar, dialogs, widgets) to "
             "output/modules/ and recalculate manifest. Does NOT touch "
             "version.txt or core files.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()

    if args.modules_only:
        # ── modules-only mode: copy only hot modules, recalculate manifest ──
        print(f"Modules-only mode — target: {output_dir}")
        copied = _copy_modules(output_dir)
        print(f"Copied {copied} module files")
    elif not args.manifest_only:
        source_dir = Path(args.source).resolve() if args.source else Path("dist/CashControl").resolve()
        if not source_dir.exists():
            print(f"ERROR: Source directory not found: {source_dir}")
            sys.exit(1)

        print(f"Copying from: {source_dir}")
        print(f"Copying to:   {output_dir}")

        # Remove existing target
        if output_dir.exists():
            shutil.rmtree(output_dir)
            print("Removed existing target directory")

        # Copy all files
        shutil.copytree(source_dir, output_dir, symlinks=False, ignore_dangling_symlinks=True)
        print(f"Copied {sum(1 for _ in output_dir.rglob('*') if _.is_file())} files")

    # Build and write manifest
    manifest = build_manifest(output_dir)
    write_manifest(manifest, output_dir)

    # Summary
    hot_count = sum(1 for f in manifest["files"] if f["reload"] == "hot")
    cold_count = sum(1 for f in manifest["files"] if f["reload"] == "cold")
    print(f"Hot files:  {hot_count}")
    print(f"Cold files: {cold_count}")
    print("Done.")


if __name__ == "__main__":
    main()