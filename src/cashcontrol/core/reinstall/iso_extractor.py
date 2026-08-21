"""
iso_extractor.py — Extract POS software archives from ISO images.

Parses ISO filename to determine cash type and version, then extracts
crystals/crystal-cash.tar from the ISO and saves it as {version}.tar
in the appropriate soft/reinstall/{type}/ directory.

ISO naming convention:
    SR-{version}-{type}-{os_info}.iso

Examples:
    SR-10.4.24.0-pos-tinycore8_8.2.12.iso     → pos,   10.4.24.0
    SR-10.4.24.0-pos-ubuntu22_v2.8.2.iso       → pos,   10.4.24.0
    SR-10.4.24.0-scov3-ubuntu22_v2.8.2.iso     → sco3,  10.4.24.0
    SR-10.4.24.0-touch-ubuntu22_v2.8.2.iso     → touch, 10.4.24.0

Inside ISO:
    crystals/crystal-cash.tar  → always at this path, all types

Usage:
    from cashcontrol.core.reinstall.iso_extractor import ISOExtractor, parse_iso_name

    # Parse ISO filename
    info = parse_iso_name("SR-10.4.24.0-scov3-ubuntu22_v2.8.2.iso")
    # ISONameInfo(version='10.4.24.0', cash_type='sco3', os_info='ubuntu22_v2.8.2')

    # Extract archive from ISO
    extractor = ISOExtractor()
    result = extractor.extract(Path("path/to/image.iso"))
    # ExtractResult(success=True, output_path=..., version='10.4.24.0', cash_type='sco3')
"""

from __future__ import annotations

import contextlib
import re
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.path_resolver import get_reinstall_type_dir

if TYPE_CHECKING:
    from pathlib import Path

# ── ISO filename parsing ──────────────────────────────────────────────────────

# Pattern: SR-{version}-{type}-{os_stuff}.iso
# type: pos, scov3 (→sco3), touch
_ISO_NAME_RE = re.compile(
    r"^SR-"
    r"(\d+(?:\.\d+)+)"       # group 1: version (e.g. 10.4.24.0)
    r"-"
    r"(pos|scov3|touch)"     # group 2: cash type keyword
    r"-"
    r"(.+)"                   # group 3: OS info (e.g. ubuntu22_v2.8.2)
    r"\.iso$",
    re.IGNORECASE,
)

# Map ISO type keywords to our internal cash_type names
_TYPE_MAP = {
    "pos": "pos",
    "scov3": "sco3",
    "touch": "touch",
}

# Path inside ISO where the archive lives
# ISO9660 truncates long names: crystal-cash.tar → CRYSTAL0.TAR;1
_ISO_ARCHIVE_PATHS = [
    "/CRYSTALS/CRYSTAL0.TAR;1",       # ISO9660 truncated name (most common)
    "/CRYSTALS/CRYSTAL-CASH.TAR;1",   # ISO9660 if name fits
    "/CRYSTALS/CRYSTAL0.TAR",         # without version suffix
    "/CRYSTALS/CRYSTAL-CASH.TAR",     # without version suffix
]
# Joliet variants (if ISO has Joliet extensions)
_ISO_ARCHIVE_PATHS_JOLIET = [
    "/crystals/crystal-cash.tar",
    "/Crystals/crystal-cash.tar",
    "/CRYSTALS/crystal-cash.tar",
]


@dataclass
class ISONameInfo:
    """Parsed information from an ISO filename."""

    version: str
    """Software version, e.g. '10.4.24.0'."""

    cash_type: str
    """Normalized cash type: 'pos', 'sco3', or 'touch'."""

    os_info: str
    """OS information string, e.g. 'ubuntu22_v2.8.2'."""

    original_name: str = ""
    """Original ISO filename."""


@dataclass
class ExtractResult:
    """Result of ISO extraction."""

    success: bool
    """Whether extraction succeeded."""

    message: str
    """Human-readable status message."""

    output_path: Path | None = None
    """Path to the extracted .tar file (if success)."""

    version: str = ""
    """Extracted software version."""

    cash_type: str = ""
    """Cash type of the extracted archive."""


def parse_iso_name(filename: str) -> ISONameInfo | None:
    """
    Parse an ISO filename to extract version, cash type, and OS info.

    Args:
        filename: ISO filename (not full path), e.g. 'SR-10.4.24.0-pos-ubuntu22_v2.8.2.iso'

    Returns:
        ISONameInfo if the filename matches the expected pattern, None otherwise.
    """
    match = _ISO_NAME_RE.match(filename)
    if not match:
        return None

    version = match.group(1)
    raw_type = match.group(2).lower()
    os_info = match.group(3)

    # Remove .iso extension from os_info if somehow included
    if os_info.lower().endswith(".iso"):
        os_info = os_info[:-4]

    cash_type = _TYPE_MAP.get(raw_type)
    if not cash_type:
        return None

    return ISONameInfo(
        version=version,
        cash_type=cash_type,
        os_info=os_info,
        original_name=filename,
    )


class ISOExtractor:
    """Extracts POS software archive from ISO images using pycdlib."""

    def extract(
        self,
        iso_path: Path,
        *,
        cash_type_override: str | None = None,
        version_override: str | None = None,
        progress_callback: object | None = None,
    ) -> ExtractResult:
        """
        Extract crystal-cash.tar from an ISO image.

        1. Parse ISO filename → determine cash type and version
        2. Open ISO with pycdlib
        3. Extract crystals/crystal-cash.tar
        4. Save as soft/reinstall/{type}/{version}.tar

        Args:
            iso_path: Path to the ISO file.
            cash_type_override: Override cash type (skip filename parsing).
            version_override: Override version (skip filename parsing).
            progress_callback: Optional callable(bytes_written, total_bytes).

        Returns:
            ExtractResult with success status and details.
        """
        if not iso_path.exists():
            return ExtractResult(
                success=False,
                message=f"ISO файл не найден: {iso_path}",
            )

        # ── Step 1: Determine type and version ──
        info = parse_iso_name(iso_path.name)

        cash_type = cash_type_override or (info.cash_type if info else None)
        version = version_override or (info.version if info else None)

        if not cash_type:
            return ExtractResult(
                success=False,
                message=(
                    f"Не удалось определить тип кассы из имени файла: {iso_path.name}\n"
                    f"Ожидаемый формат: SR-ВЕРСИЯ-ТИП-ОС.iso\n"
                    f"Пример: SR-10.4.24.0-pos-ubuntu22_v2.8.2.iso"
                ),
            )

        if not version:
            return ExtractResult(
                success=False,
                message=f"Не удалось определить версию ПО из имени файла: {iso_path.name}",
            )

        # ── Step 2: Build output filename (ISO name with .tar extension) ──
        output_dir = get_reinstall_type_dir(cash_type)
        # SR-10.4.24.0-pos-ubuntu22_v2.8.2.iso → SR-10.4.24.0-pos-ubuntu22_v2.8.2.tar
        output_name = iso_path.stem + ".tar"
        output_path = output_dir / output_name

        if output_path.exists():
            return ExtractResult(
                success=False,
                message=f"Архив {output_name} уже существует в каталоге {cash_type}/",
                version=version,
                cash_type=cash_type,
            )

        # ── Step 3: Extract from ISO ──
        try:
            return self._extract_with_pycdlib(
                iso_path, output_path, cash_type, version, progress_callback
            )
        except ImportError:
            return ExtractResult(
                success=False,
                message=(
                    "Библиотека pycdlib не установлена.\n"
                    "Установите: pip install pycdlib"
                ),
            )
        except Exception as e:
            # Clean up partial file
            if output_path.exists():
                with contextlib.suppress(OSError):
                    output_path.unlink()
            return ExtractResult(
                success=False,
                message=f"Ошибка при извлечении: {e}",
                version=version,
                cash_type=cash_type,
            )

    def _extract_with_pycdlib(
        self,
        iso_path: Path,
        output_path: Path,
        cash_type: str,
        version: str,
        progress_callback: object | None,
    ) -> ExtractResult:
        """Extract using pycdlib library."""
        import pycdlib

        iso = pycdlib.PyCdlib()
        iso.open(str(iso_path))

        try:
            tmp_path = output_path.with_suffix(".tar.tmp")
            extracted = False

            # Detect if ISO has Joliet extensions
            has_joliet = iso.has_joliet()

            # Strategy 1: Try Joliet paths (if available — preserves original names)
            if has_joliet:
                for try_path in _ISO_ARCHIVE_PATHS_JOLIET:
                    try:
                        iso.get_file_from_iso(str(tmp_path), joliet_path=try_path)
                        extracted = True
                        break
                    except Exception:
                        if tmp_path.exists():
                            tmp_path.unlink()

            # Strategy 2: Try known ISO9660 paths
            if not extracted:
                for try_path in _ISO_ARCHIVE_PATHS:
                    try:
                        iso.get_file_from_iso(str(tmp_path), iso_path=try_path)
                        extracted = True
                        break
                    except Exception:
                        if tmp_path.exists():
                            tmp_path.unlink()

            # Strategy 3: Scan /CRYSTALS/ for the largest .TAR file
            if not extracted:
                found_path = self._find_largest_tar_in_crystals(iso, has_joliet)
                if found_path:
                    try:
                        if has_joliet and not found_path.startswith("/CRYSTALS"):
                            iso.get_file_from_iso(str(tmp_path), joliet_path=found_path)
                        else:
                            iso.get_file_from_iso(str(tmp_path), iso_path=found_path)
                        extracted = True
                    except Exception:
                        if tmp_path.exists():
                            tmp_path.unlink()

            if not extracted:
                return ExtractResult(
                    success=False,
                    message=(
                        "Файл crystal-cash.tar не найден внутри ISO.\n"
                        "Проверьте, что образ содержит папку crystals/ с архивом ПО."
                    ),
                    version=version,
                    cash_type=cash_type,
                )

            # Rename temp to final
            shutil.move(str(tmp_path), str(output_path))

            size_mb = round(output_path.stat().st_size / (1024 * 1024), 1)
            return ExtractResult(
                success=True,
                message=f"Архив {output_path.name} ({size_mb} MB) извлечён в {cash_type}/",
                output_path=output_path,
                version=version,
                cash_type=cash_type,
            )

        finally:
            iso.close()

    @staticmethod
    def _find_largest_tar_in_crystals(iso, has_joliet: bool) -> str | None:
        """
        Find the largest .tar file in /CRYSTALS/ directory.

        ISO9660 truncates 'crystal-cash.tar' to 'CRYSTAL0.TAR;1'.
        Instead of guessing the truncated name, we find the biggest .tar
        in the crystals directory — that's the POS software archive.
        """
        best_path: str | None = None
        best_size: int = 0

        # Try ISO9660 first (always available)
        try:
            for child in iso.list_children(iso_path="/CRYSTALS"):
                if child.is_dir():
                    continue
                name = child.file_identifier().decode("utf-8", errors="replace")
                # Check if it's a .TAR file (ISO9660: NAME.TAR;1)
                clean = name.split(";")[0].strip(".")
                if clean.upper().endswith(".TAR"):
                    size = child.data_length
                    if size > best_size:
                        best_size = size
                        best_path = f"/CRYSTALS/{name}"
        except Exception:
            # ожидаемо: Rock Ridge может отсутствовать
            pass

        # Try Joliet if available and nothing found
        if best_path is None and has_joliet:
            for joliet_dir in ("/crystals", "/Crystals", "/CRYSTALS"):
                try:
                    for child in iso.list_children(joliet_path=joliet_dir):
                        if child.is_dir():
                            continue
                        name = child.file_identifier().decode("utf-8", errors="replace")
                        if name.lower().endswith(".tar"):
                            size = child.data_length
                            if size > best_size:
                                best_size = size
                                best_path = f"{joliet_dir}/{name}"
                    if best_path:
                        break
                except Exception:
                    # ожидаемо: Joliet-каталог может не читаться, пробуем следующий
                    continue

        return best_path