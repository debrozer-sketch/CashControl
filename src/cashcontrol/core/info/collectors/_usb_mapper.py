"""
USB device mapper — loads usb_id_mapping.json and provides lookup helpers.

Used by barcode_scanner, scales and customer_display collectors to:
  1. Map a raw device path (e.g. /dev/usbSV05e0P1701) to a human name
     (e.g. "Zebra DS2208/DS9308 COM")
  2. Verify physical connection by scanning /sys/bus/usb/devices via SSH
     and comparing vendor:product IDs against expected ones.

usb_id_mapping.json format:
{
    "Device Name": {
        "usb_ids":     ["vvvv:pppp", ...],  // vendor:product hex pairs
        "device_paths": ["/dev/usbSVvvvvPpppp", ...],  // config file paths
        "type": "scanner" | "scale" | "customer_display"
    },
    ...
}
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_usb_mapping_file

if TYPE_CHECKING:
    from pathlib import Path

    from cashcontrol.core.session import CashSession

logger = get_logger()

# Singleton cache
_mapping_cache: dict | None = None
_mapping_path_used: Path | None = None


def load_usb_mapping(device_type: str | None = None) -> dict[str, dict]:
    """
    Load and optionally filter usb_id_mapping.json.

    Args:
        device_type: If given, return only entries with matching "type" field.
                     E.g. "scanner", "scale", "customer_display".

    Returns:
        Dict of {device_name: info_dict}
    """
    global _mapping_cache, _mapping_path_used

    mapping_file = get_usb_mapping_file()

    # Reload if file changed or not loaded yet
    if _mapping_cache is None or _mapping_path_used != mapping_file:
        if mapping_file.exists():
            try:
                _mapping_cache = json.loads(
                    mapping_file.read_text(encoding="utf-8")
                )
                _mapping_path_used = mapping_file
                logger.debug(
                    f"Loaded USB mapping: {len(_mapping_cache)} entries"
                )
            except Exception as e:
                logger.error(f"Failed to load USB mapping: {e}")
                _mapping_cache = {}
        else:
            logger.warning(f"USB mapping file not found: {mapping_file}")
            _mapping_cache = {}

    if device_type is None:
        # Filter out _schema meta-entry
        return {k: v for k, v in _mapping_cache.items() if not k.startswith("_")}  # type: ignore[union-attr]

    return {
        name: info
        for name, info in _mapping_cache.items()  # type: ignore[union-attr]
        if not name.startswith("_") and isinstance(info, dict) and info.get("type") == device_type
    }


def invalidate_cache() -> None:
    """Force reload of mapping on next call (useful after hot update)."""
    global _mapping_cache
    _mapping_cache = None


def lookup_device_by_path(
    port_value: str, mapping: dict[str, dict]
) -> tuple[str, dict | None]:
    """
    Find device name and info by raw port path from config file.

    Args:
        port_value: Raw path from XML/INI, e.g. "/dev/usbSV05e0P1701"
        mapping:    Filtered mapping dict (from load_usb_mapping)

    Returns:
        (device_name, device_info) if found, else (friendly_fallback, None)

    Friendly fallback:
        /dev/ttyS1  → COM2
        /dev/ttyUSB0 → USB0
        anything else → port_value as-is
    """
    # Exact match in device_paths
    for name, info in mapping.items():
        if isinstance(info, dict):
            paths = info.get("device_paths", [])
            if port_value in paths:
                return name, info

    # Fallback: serial port → COM name
    if port_value.startswith("/dev/ttyS"):
        try:
            num = int(port_value.split("ttyS")[1])
            return f"COM{num + 1}", None
        except (ValueError, IndexError):
            pass

    if port_value.startswith("/dev/ttyUSB"):
        try:
            num = int(port_value.split("ttyUSB")[1])
            return f"USB{num}", None
        except (ValueError, IndexError):
            pass

    # Return port as-is
    return port_value, None


async def check_usb_connected(
    session: CashSession, device_info: dict | None
) -> bool | None:
    """
    Check if USB device is physically connected via /sys/bus/usb/devices.

    Args:
        session:     Connected CashSession (SSH)
        device_info: Device info dict with "usb_ids" list, or None

    Returns:
        True  — device found in USB tree
        False — device NOT found (configured but not connected)
        None  — cannot determine (no usb_ids, SSH error, etc.)
    """
    if not device_info:
        return None

    expected_ids: list[str] = device_info.get("usb_ids", [])
    if not expected_ids:
        return None

    try:
        cmd = (
            'for dev in /sys/bus/usb/devices/*; do '
            '[ -f "$dev/idVendor" -a -f "$dev/idProduct" ] && '
            'echo "$(cat $dev/idVendor):$(cat $dev/idProduct)"; '
            'done'
        )
        result = await session.ssh.execute(cmd)
        if not result.success:
            return None

        # Build set of found vendor:product IDs (lowercase, no 0x prefix)
        found_ids: set[str] = set()
        for line in result.stdout.splitlines():
            line = line.strip().lower()
            if ":" in line:
                found_ids.add(line)

        # Compare against expected
        for expected in expected_ids:
            # Normalise: "05e0:1701" or "SV05e0P1701" → "05e0:1701"
            normalised = _normalise_usb_id(expected)
            if normalised and normalised in found_ids:
                return True

        return False

    except Exception as e:
        logger.debug(f"USB check failed on {session.host}: {e}")
        return None


def _normalise_usb_id(raw: str) -> str | None:
    """
    Convert various USB ID formats to lowercase "vvvv:pppp".

    Handles:
        "05e0:1701"         → "05e0:1701"
        "SVe851P1002"       → "e851:1002"
        "/dev/usbSV05e0P1701" → "05e0:1701"
    """
    raw = raw.strip().lower()

    # Already in vendor:product format
    if re.match(r"^[0-9a-f]{4}:[0-9a-f]{4}$", raw):
        return raw

    # SVxxxxPyyyy or /dev/usbSVxxxxPyyyy
    m = re.search(r"sv([0-9a-f]{4})p([0-9a-f]{4})", raw)
    if m:
        return f"{m.group(1)}:{m.group(2)}"

    return None


def format_port_as_com(port_value: str) -> str:
    """
    Convert Linux serial port path to Windows COM name for display.

    /dev/ttyS0  → COM1
    /dev/ttyS1  → COM2
    /dev/ttyUSB0 → USB (ttyUSB0)
    /dev/usbSV... → USB
    anything else → returned as-is
    """
    if port_value.startswith("/dev/ttyS"):
        try:
            num = int(port_value.split("ttyS")[1])
            return f"COM{num + 1}"
        except (ValueError, IndexError):
            pass
    if "/usb" in port_value.lower() or port_value.startswith("/dev/usbS"):
        return "USB"
    if port_value.startswith("/dev/ttyUSB"):
        return f"USB ({port_value.split('/')[-1]})"
    return port_value