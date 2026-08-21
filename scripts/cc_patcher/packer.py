from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path


RELOAD_RULES: dict[str, str] = {
    "commands": "hot",
    "styles": "hot",
    "collectors": "hot",
    "scenarios": "hot",
}


def _classify(path: str) -> str:
    for prefix, hint in RELOAD_RULES.items():
        if path.startswith(prefix + "/"):
            return hint
    return "hot"


def build_manifest(
    version: str,
    description: str,
    added: list[str],
    changed: list[str],
    deleted: list[str],
) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    files = []
    for p in sorted(set(added + changed)):
        files.append({"path": p, "reload_hint": _classify(p)})
    return {
        "id": timestamp,
        "created_at": now,
        "description": description,
        "for_version": version,
        "files": files,
        "files_deleted": sorted(deleted),
    }


def pack_patch(
    root: Path,
    manifest: dict,
    output_dir: Path,
) -> Path:
    version = manifest["for_version"]
    timestamp = manifest["id"]
    all_paths = set()
    for entry in manifest["files"]:
        all_paths.add(entry["path"])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for rel_path in sorted(all_paths):
            src = root / rel_path
            if src.is_file():
                zf.write(src, f"files/{rel_path}")
        zf.writestr(
            "deletions.json",
            json.dumps(manifest["files_deleted"], indent=2, ensure_ascii=False),
        )

    zip_hash = hashlib.sha256(buf.getvalue()).hexdigest()[:8]
    filename = f"{version}_{timestamp}_{zip_hash}.patch.zip"
    output_path = output_dir / filename
    output_path.write_bytes(buf.getvalue())
    return output_path


def pack_upgrade(
    root: Path,
    from_version: str,
    to_version: str,
    added: list[str],
    changed: list[str],
    deleted: list[str],
    output_dir: Path,
) -> Path:
    now = datetime.now().isoformat(timespec="seconds")
    files = []
    for p in sorted(set(added + changed)):
        files.append({"path": p, "reload_hint": _classify(p)})
    manifest = {
        "id": f"upgrade_from_{from_version}",
        "from_version": from_version,
        "to_version": to_version,
        "created_at": now,
        "files": files,
        "files_deleted": sorted(deleted),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for entry in manifest["files"]:
            src = root / entry["path"]
            if src.is_file():
                zf.write(src, f"files/{entry['path']}")
        zf.writestr(
            "deletions.json",
            json.dumps(manifest["files_deleted"], indent=2, ensure_ascii=False),
        )

    filename = f"upgrade_from_{from_version}.upgrade.zip"
    output_path = output_dir / filename
    output_path.write_bytes(buf.getvalue())
    return output_path
