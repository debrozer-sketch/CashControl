"""
OS info collector — detects operating system type and version.

Determines if cash register runs Tinycore Linux or Ubuntu.
This is critical for other collectors as they adapt behavior based on OS.

Usage:
    collector = OSInfoCollector()
    info = await collector.collect(session)
    # info = {"os_type": "tinycore", "os_version": "10.1", ...}
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()


class OSInfoCollector:
    """
    Collects operating system information.

    Detects OS type (Tinycore/Ubuntu), version, kernel, hostname.
    """

    async def _exec(self, session: CashSession, cmd: str) -> str | None:
        result = await session.ssh.execute(cmd)
        if result.success:
            return result.stdout.strip()
        return None

    async def _detect_os_type(self, session: CashSession, kernel: str | None) -> str:
        if kernel and "tinycore" in kernel.lower():
            return "tinycore"
        if await self._exec(session, "test -f /etc/sysconfig/tcedir && echo 'yes'") == "yes":
            return "tinycore"
        if await self._exec(session, "test -f /etc/lsb-release && echo 'yes'") == "yes":
            return "ubuntu"
        return "unknown"

    async def _detect_os_version(self, session: CashSession, os_type: str, kernel: str | None) -> str:
        if os_type == "tinycore":
            version = await self._exec(session, "cat /usr/share/doc/tc/release.txt 2>/dev/null")
            if version:
                return version
            if kernel:
                import re
                match = re.search(r'(\d+\.\d+)', kernel)
                if match:
                    return match.group(1)
            return "unknown"
        if os_type == "ubuntu":
            version = await self._exec(session, "grep DISTRIB_RELEASE /etc/lsb-release | cut -d= -f2")
            if version:
                return version
            return "unknown"
        version = await self._exec(session, "grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\"'")
        if version:
            return version
        return "unknown"

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        info: dict[str, str | None] = {
            "os_type": None,
            "os_version": None,
            "kernel": None,
            "hostname": None,
            "architecture": None,
        }

        try:
            info["kernel"] = await self._exec(session, "uname -r")
            info["architecture"] = await self._exec(session, "uname -m")
            info["hostname"] = await self._exec(session, "hostname")

            info["os_type"] = await self._detect_os_type(session, info["kernel"])
            info["os_version"] = await self._detect_os_version(session, info["os_type"], info["kernel"])

            session.os_type = info["os_type"]
            session.os_version = info["os_version"]
            session.hostname = info["hostname"]
            logger.info(f"Detected OS on {session.host}: {info['os_type']} {info['os_version']}")

        except Exception as e:
            logger.error(f"Failed to collect OS info from {session.host}: {e}")

        return info
