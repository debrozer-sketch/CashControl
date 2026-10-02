"""Detection strategies for TypeDetector (docs/design §3).

Each strategy receives the rule dict, an SSH session and a file cache
(path -> content) so that already-fetched files are not re-read.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

_ROOT_ATTRS = ("moduleType", "type", "cashType", "registerType", "cashRegisterType")


def _iter_values(root: ET.Element) -> list[str]:
    values: list[str] = []
    for elem in root.iter():
        values.extend(elem.attrib.values())
        values.append(elem.tag)
        if elem.text:
            values.append(elem.text)
    return values


async def xml_keywords(
    rule: dict[str, Any], session: CashSession, cache: dict[str, str]
) -> str | None:
    """Legacy behaviour: scan XML at `path` for known type keywords."""
    path = rule.get("path")
    if not path:
        return None
    text = await _read_file(session, path, cache)
    if not text:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        logger.warning(f"XML parse error for {path}: {e}")
        return None

    candidates: list[str] = []
    for attr in _ROOT_ATTRS:
        value = root.get(attr)
        if value:
            candidates.append(value)
    candidates.extend(_iter_values(root))

    from cashcontrol.core.cash_types.registry import get_cash_type_registry

    registry = get_cash_type_registry()
    for candidate in candidates:
        resolved = registry.resolve(candidate)
        if resolved:
            return resolved
        resolved = registry.match_substring(candidate)
        if resolved:
            return resolved
    return None


async def regex_file(
    rule: dict[str, Any], session: CashSession, cache: dict[str, str]
) -> str | None:
    path = rule.get("path")
    pattern = rule.get("pattern")
    if not path or not pattern:
        return None
    text = await _read_file(session, path, cache)
    if text is None:
        return None
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return None
    raw = match.groupdict().get("type") or next(
        (g for g in match.groups() if g), match.group(0)
    )
    return _map_value(rule, raw)


async def shell(
    rule: dict[str, Any], session: CashSession, cache: dict[str, str]
) -> str | None:
    command = rule.get("command")
    if not command or not session.ssh_connected:
        return None
    result = await session.ssh.execute(command)
    if not result.success or not result.stdout.strip():
        return None
    raw = result.stdout.strip().splitlines()[0].strip()
    return _map_value(rule, raw)


STRATEGIES = {
    "xml_keywords": xml_keywords,
    "regex_file": regex_file,
    "shell": shell,
}


def _map_value(rule: dict[str, Any], raw: str) -> str | None:
    mapping: dict[str, str] = rule.get("map") or {}
    mapped = mapping.get(raw.strip()) or mapping.get(raw.strip().lower())
    target = mapped or raw
    from cashcontrol.core.cash_types.registry import get_cash_type_registry

    return get_cash_type_registry().resolve(target)


async def _read_file(
    session: CashSession, path: str, cache: dict[str, str]
) -> str | None:
    if path in cache:
        return cache[path]
    if not session.ssh_connected:
        return None
    result = await session.ssh.execute(f"cat {path}")
    if not result.success or not result.stdout.strip():
        return None
    cache[path] = result.stdout
    return result.stdout
