from __future__ import annotations

import json
import shutil
from pathlib import Path


CONFIG_PATH = Path("scripts") / ".patcher_config.json"


def load_config() -> dict:
    if CONFIG_PATH.is_file():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def save_config(**kwargs) -> None:
    existing = load_config()
    existing.update(kwargs)
    CONFIG_PATH.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def get_network_path(override: str | None = None) -> str:
    if override:
        return override
    cfg = load_config()
    path = cfg.get("network_path", "")
    if not path:
        print(
            "fatal: network path not configured — run:\n"
            "  python -m scripts.cc_patcher config --network-path PATH",
            file=__import__("sys").stderr,
        )
        __import__("sys").exit(1)
    return path


def check_path_available(path: str) -> bool:
    return Path(path).is_dir()


def publish_patch(patch_path: Path, version: str, network_path: str) -> None:
    dest = Path(network_path) / "patches" / version
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(patch_path, dest / patch_path.name)
    print(f"Published {patch_path.name} -> {dest}")


def publish_release(
    version: str,
    prev_version: str | None,
    upgrade_patch: Path | None,
    network_path: str,
) -> None:
    base = Path(network_path)

    release_dir = base / "releases" / version
    release_dir.mkdir(parents=True, exist_ok=True)

    if upgrade_patch:
        shutil.copy2(upgrade_patch, release_dir / upgrade_patch.name)
        print(f"Published {upgrade_patch.name} -> {release_dir}")

    exe_src = Path("dist") / "CashControl" / "CashControl.exe"
    if exe_src.is_file():
        shutil.copy2(exe_src, release_dir / "cashcontrol.exe")
        print(f"Published cashcontrol.exe -> {release_dir}")
    else:
        print(
            "warning: dist/CashControl/CashControl.exe not found — skipped",
            file=__import__("sys").stderr,
        )

    installer = Path("dist") / f"CashControl_Setup_{version}.exe"
    if installer.is_file():
        shutil.copy2(installer, release_dir / installer.name)
        print(f"Published {installer.name} -> {release_dir}")

    latest = {"version": version}
    (base / "releases" / "latest.json").write_text(
        json.dumps(latest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Updated releases/latest.json -> version {version}")

    patches_dir = base / "patches" / version
    patches_dir.mkdir(parents=True, exist_ok=True)
    print(f"Created patches/{version}/ directory")

    if prev_version:
        archive_dir = base / "patches" / "_archive" / prev_version
        src_patches = base / "patches" / prev_version
        if src_patches.is_dir():
            archive_dir.parent.mkdir(parents=True, exist_ok=True)
            if archive_dir.exists():
                shutil.rmtree(archive_dir)
            shutil.copytree(src_patches, archive_dir)
            shutil.rmtree(src_patches)
            print(f"Archived patches/{prev_version}/ -> patches/_archive/{prev_version}/")
