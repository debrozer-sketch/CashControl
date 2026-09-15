"""Seed shipped default content into the live per-version directories.

The installer/portable build carries example commands, collectors, cash types
and detection rules under ``<app>/defaults/`` and never ships the live
``commands/``, ``collectors/``, ``cash_types/`` and ``detection/`` folders
anymore. That is what keeps user data (custom commands, own collectors,
settings-backed files) from being overwritten on every update.

``seed_defaults`` copies a default file into the matching live directory only
when it is missing, so files the user created or edited are never replaced:
    - fresh install  -> every example lands in the live folder;
    - version update -> existing user files stay, newly shipped examples appear.
"""

from __future__ import annotations

import logging
import shutil

from cashcontrol.infrastructure.path_resolver import get_app_root

logger = logging.getLogger("cashcontrol.infrastructure")

# (defaults subdir, live subdir under the app root)
_DEFAULT_DIRS = (
    ("commands", "commands"),
    ("collectors", "collectors"),
    ("cash_types", "cash_types"),
    ("detection", "detection"),
)


def seed_defaults() -> int:
    """Copy missing files from ``<app>/defaults/*`` into live dirs.

    Returns the number of seeded files (0 when the build ships no defaults,
    e.g. running from the repository in development mode).
    """
    root = get_app_root()
    defaults = root / "defaults"
    if not defaults.is_dir():
        return 0

    seeded = 0
    for defaults_sub, live_sub in _DEFAULT_DIRS:
        src_dir = defaults / defaults_sub
        if not src_dir.is_dir():
            continue
        target_dir = root / live_sub
        target_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(src_dir.rglob("*")):
            if not f.is_file():
                continue
            dst = target_dir / f.relative_to(src_dir)
            if dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            seeded += 1
    if seeded:
        logger.info("Seeded %d default file(s) from defaults/ into live dirs", seeded)
    return seeded


__all__ = ["seed_defaults"]
