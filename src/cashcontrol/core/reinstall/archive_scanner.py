"""
archive_scanner.py — Scans soft/reinstall/{type}/ for available POS software archives.

Each archive is a .tar file named as the version number: e.g. 10.4.24.0.tar
Archives are organized by cash type in subdirectories: pos/, sco3/, touch/.

Usage:
    from cashcontrol.core.reinstall.archive_scanner import ArchiveScanner

    scanner = ArchiveScanner()
    archives = scanner.scan_all()
    # {'pos': [ArchiveInfo(...), ...], 'sco3': [...], 'touch': [...]}

    pos_archives = scanner.scan_type('pos')
    # [ArchiveInfo(version='10.4.24.0', path=..., size=..., modified=...), ...]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.path_resolver import (
    REINSTALL_CASH_TYPES,
    ensure_reinstall_dirs,
    get_reinstall_type_dir,
)

if TYPE_CHECKING:
    from pathlib import Path

# Archive filename pattern: SR-{version}-{type}-{os_info}.tar
# Examples:
#   SR-10.4.24.0-pos-ubuntu22_v2.8.2.tar
#   SR-10.4.24.0-scov3-ubuntu22_v2.8.2.tar
#   SR-10.4.24.0-pos-tinycore8_8.2.12.tar
_ARCHIVE_RE = re.compile(
    r"^SR-"
    r"(\d+(?:\.\d+)+)"       # group 1: version (e.g. 10.4.24.0)
    r"-"
    r"(pos|scov3|touch)"      # group 2: cash type keyword
    r"-"
    r"(.+)"                    # group 3: OS info
    r"\.tar$",
    re.IGNORECASE,
)

# Also accept plain .tar files (any name) as a fallback
_PLAIN_TAR_RE = re.compile(r"^.+\.tar$", re.IGNORECASE)


@dataclass
class ArchiveInfo:
    """Information about a single POS software archive."""

    version: str
    """Software version extracted from filename, e.g. '10.4.24.0'."""

    path: Path
    """Full path to the .tar file."""

    cash_type: str
    """Cash type: 'pos', 'sco3', or 'touch'."""

    os_info: str = ""
    """OS information from filename, e.g. 'ubuntu22_v2.8.2'."""

    filename: str = ""
    """Original filename without extension."""

    size_bytes: int = 0
    """File size in bytes."""

    modified: datetime = field(default_factory=datetime.now)
    """Last modification time."""

    @property
    def size_mb(self) -> float:
        """File size in megabytes, rounded to 1 decimal."""
        return round(self.size_bytes / (1024 * 1024), 1)

    @property
    def version_tuple(self) -> tuple[int, ...]:
        """Version as tuple of ints for sorting. e.g. (10, 4, 24, 0)."""
        try:
            return tuple(int(x) for x in self.version.split("."))
        except ValueError:
            return (0,)

    @property
    def display_name(self) -> str:
        """Human-readable name for display in UI."""
        if self.os_info:
            return f"{self.version} ({self.os_info})"
        return self.version

    def __str__(self) -> str:
        return f"{self.display_name} — {self.size_mb} MB"


class ArchiveScanner:
    """Scans reinstall directories for available POS software archives."""

    def __init__(self) -> None:
        ensure_reinstall_dirs()

    def scan_type(self, cash_type: str) -> list[ArchiveInfo]:
        """
        Scan a single cash type directory for archives.

        Args:
            cash_type: 'pos', 'sco3', or 'touch'

        Returns:
            List of ArchiveInfo sorted by version descending (newest first).
        """
        if cash_type not in REINSTALL_CASH_TYPES:
            return []

        type_dir = get_reinstall_type_dir(cash_type)
        archives: list[ArchiveInfo] = []

        for tar_file in type_dir.iterdir():
            if not tar_file.is_file():
                continue
            if not tar_file.name.lower().endswith(".tar"):
                continue

            match = _ARCHIVE_RE.match(tar_file.name)
            if match:
                version = match.group(1)
                os_info = match.group(3)
            else:
                # Fallback: accept any .tar, use filename as version
                version = tar_file.stem
                os_info = ""

            stat = tar_file.stat()
            archives.append(
                ArchiveInfo(
                    version=version,
                    path=tar_file,
                    cash_type=cash_type,
                    os_info=os_info,
                    filename=tar_file.stem,
                    size_bytes=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                )
            )

        # Sort by version descending (newest first)
        archives.sort(key=lambda a: a.version_tuple, reverse=True)
        return archives

    def scan_all(self) -> dict[str, list[ArchiveInfo]]:
        """
        Scan all cash type directories.

        Returns:
            Dict mapping cash_type -> list of ArchiveInfo.
        """
        return {ct: self.scan_type(ct) for ct in REINSTALL_CASH_TYPES}

    def total_count(self) -> int:
        """Total number of archives across all types."""
        return sum(len(v) for v in self.scan_all().values())

    def find_archive(self, cash_type: str, version: str) -> ArchiveInfo | None:
        """Find a specific archive by type and version."""
        for archive in self.scan_type(cash_type):
            if archive.version == version:
                return archive
        return None

    def delete_archive(self, archive: ArchiveInfo) -> bool:
        """
        Delete an archive file.

        Returns:
            True if deleted successfully.
        """
        try:
            if archive.path.exists():
                archive.path.unlink()
                return True
        except OSError:
            pass
        return False