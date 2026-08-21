from __future__ import annotations

import hashlib
from pathlib import Path  # noqa: TC003


SCAN_DIRS = ["commands", "styles", "collectors", "scenarios"]


def scan(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for dirname in SCAN_DIRS:
        d = root / dirname
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            rel_str = str(rel.as_posix())
            files[rel_str] = f"sha256:{_sha256(p)}"
    return files


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()
