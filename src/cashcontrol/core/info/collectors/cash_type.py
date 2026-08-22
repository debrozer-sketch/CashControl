"""
Cash type collector — determines cash register type from register-modules.xml.

Reads /home/tc/storage/crystal-cash/config/register-modules.xml and extracts
the cash type (pos, touch, sco, sco3) from the XML root attributes.

The type is stored in session.cash_type for use by other collectors
that need to filter by cash type.

Types:
    pos    — standard POS terminal (full keyboard, customer display, etc.)
    touch  — touch-screen POS
    sco    — self-checkout (SCO)
    sco3   — SCO v3 (newer, uses PostgreSQL DB for hardware config)
    unknown — could not determine
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

XML_PATH = "/home/tc/storage/crystal-cash/config/register-modules.xml"

# Map XML moduleType values to our internal type names
# The actual attribute name and values may vary — we try multiple approaches
_TYPE_KEYWORDS: dict[str, str] = {
    "pos": "pos",
    "touch": "touch",
    "sco3": "sco3",
    "sco_v3": "sco3",
    "scov3": "sco3",
    "sco": "sco",
    "selfcheckout": "sco",
    "self_checkout": "sco",
}


def _detect_type_from_xml(xml_text: str) -> str | None:
    """
    Parse register-modules.xml and determine cash type.

    Tries:
      1. Root attribute 'moduleType'
      2. Root attribute 'type'
      3. Root attribute 'cashType'
      4. Element <module type="..."> with name containing keywords
      5. Any attribute value containing known keywords

    Returns normalised type string or None.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"XML parse error in register-modules.xml: {e}")
        return None

    # Try common attribute names on root element
    for attr in ("moduleType", "type", "cashType", "registerType", "cashRegisterType"):
        val = root.get(attr, "")
        if val:
            normalised = _normalise_type(val)
            if normalised:
                return normalised

    # Scan all elements and attributes for type keywords
    for elem in root.iter():
        for _attr_name, attr_val in elem.attrib.items():
            normalised = _normalise_type(attr_val)
            if normalised:
                return normalised
        # Also check element tag / text
        normalised = _normalise_type(elem.tag)
        if normalised:
            return normalised

    return None


def _normalise_type(value: str) -> str | None:
    """Map raw string to canonical cash type."""
    v = value.strip().lower()
    # Direct lookup
    if v in _TYPE_KEYWORDS:
        return _TYPE_KEYWORDS[v]
    # Substring match
    for keyword, canonical in _TYPE_KEYWORDS.items():
        if keyword in v:
            return canonical
    return None


class CashTypeCollector:
    """
    Determines cash register type from register-modules.xml.

    Result is stored both in the returned dict and in session.cash_type
    so that subsequent collectors can access it without re-reading the file.
    """

    async def collect(self, session: CashSession) -> dict[str, str | None]:
        """
        Collect cash type information.

        Args:
            session: Connected CashSession

        Returns:
            Dict with:
                cash_type: "pos" | "touch" | "sco" | "sco3" | "unknown"
                sw_version: productVersion attribute from the same XML (reuse the read)
                sw_path:    canonical software base path
        """
        info: dict[str, str | None] = {
            "cash_type": None,
            "sw_version": None,
            "sw_path": "/home/tc/storage/crystal-cash",
        }

        # If already set (e.g. by widget pre-connect), return cached value
        existing = getattr(session, "cash_type", None)
        if existing and existing != "unknown":
            info["cash_type"] = existing
            logger.debug(f"cash_type already set for {session.host}: {existing}")
            # Still try to read sw_version if not available
            try:
                result = await session.ssh.execute(f"cat {XML_PATH}")
                if result.success and result.stdout.strip():
                    import xml.etree.ElementTree as _ET
                    root = _ET.fromstring(result.stdout)
                    pv = root.get("productVersion")
                    if pv:
                        info["sw_version"] = pv.strip()
            except Exception:
                pass
            return info

        try:
            result = await session.ssh.execute(f"cat {XML_PATH}")
            if not result.success or not result.stdout.strip():
                logger.warning(
                    f"Cannot read {XML_PATH} on {session.host}: {result.stderr}"
                )
                info["cash_type"] = "unknown"
                return info

            xml_text = result.stdout

            # Extract productVersion (used by software collector too)
            try:
                root = ET.fromstring(xml_text)
                pv = root.get("productVersion")
                if pv:
                    info["sw_version"] = pv.strip()
            except ET.ParseError:
                pass

            # Detect type
            detected = _detect_type_from_xml(xml_text)
            info["cash_type"] = detected or "unknown"

            # Store in session for other collectors
            session.cash_type = info["cash_type"]

            logger.info(
                f"Cash type on {session.host}: {info['cash_type']} "
                f"(version: {info['sw_version']})"
            )

        except Exception as e:
            logger.error(f"Failed to collect cash type from {session.host}: {e}")
            info["cash_type"] = "unknown"

        return info