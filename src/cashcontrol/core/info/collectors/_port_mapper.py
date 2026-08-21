"""
Port mapper — maps device types to OS-specific port names.

Reads data/port_mapping.json and provides port names based on detected OS.

Usage:
    from cashcontrol.core.info.collectors._port_mapper import PortMapper

    mapper = PortMapper()
    port = mapper.get_port("fiscal_printer", "tinycore")
    # Returns: "ttyS0"
"""

from __future__ import annotations

import json
from typing import Any

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_port_mapping_file

logger = get_logger()


class PortMapper:
    """
    Maps device types to OS-specific serial port names.

    Loads port mapping from data/port_mapping.json on initialization.
    """

    def __init__(self) -> None:
        self._mapping: dict[str, dict[str, Any]] = {}
        self._load_mapping()

    def _load_mapping(self) -> None:
        """Load port mapping from JSON file."""
        mapping_file = get_port_mapping_file()

        if not mapping_file.exists():
            logger.warning(f"Port mapping file not found: {mapping_file}")
            return

        try:
            with open(mapping_file, encoding="utf-8") as f:
                self._mapping = json.load(f)
            logger.debug(f"Loaded port mapping for {len(self._mapping)} devices")

        except Exception as e:
            logger.error(f"Failed to load port mapping: {e}")
            self._mapping = {}

    def get_port(
        self, device_type: str, os_type: str, fallback: str | None = None
    ) -> str | None:
        """
        Get port name for device on specific OS.

        Args:
            device_type: Device type (e.g., "fiscal_printer", "scales")
            os_type: OS type ("tinycore" or "ubuntu")
            fallback: Fallback port if not found in mapping

        Returns:
            Port name (e.g., "ttyS0", "ttyUSB0") or fallback or None

        Example:
            port = mapper.get_port("fiscal_printer", "tinycore")
            # Returns: "ttyS0"
        """
        device_info = self._mapping.get(device_type)

        if not device_info:
            logger.debug(f"No mapping found for device: {device_type}")
            return fallback

        # Get OS-specific port
        if os_type.lower() == "tinycore":
            port = device_info.get("tinycore_port_name")
        elif os_type.lower() == "ubuntu":
            port = device_info.get("ubuntu_port_name")
        else:
            logger.warning(f"Unknown OS type: {os_type}")
            port = None

        if not port:
            # Try generic device_path
            port = device_info.get("device_path")

        if not port:
            logger.debug(
                f"No port found for {device_type} on {os_type}, using fallback"
            )
            return fallback

        return port

    def get_device_info(self, device_type: str) -> dict[str, Any] | None:
        """
        Get full device mapping info.

        Args:
            device_type: Device type

        Returns:
            Device mapping dict or None
        """
        return self._mapping.get(device_type)

    def get_all_devices(self) -> list[str]:
        """Get list of all mapped device types."""
        return list(self._mapping.keys())


# Singleton instance
_port_mapper_instance: PortMapper | None = None


def get_port_mapper() -> PortMapper:
    """
    Get singleton PortMapper instance.

    Returns:
        PortMapper instance
    """
    global _port_mapper_instance
    if _port_mapper_instance is None:
        _port_mapper_instance = PortMapper()
    return _port_mapper_instance