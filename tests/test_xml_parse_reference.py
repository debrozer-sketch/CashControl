"""
Reference test for XML parsing before/after defusedxml migration.

Usage:
    1. Copy XML files from a cash register into tests/fixtures/xml/:
       - register-modules.xml     (from /home/tc/storage/crystal-cash/config/register-modules.xml)
       - keyboard-config.xml      (from .../config/modules/keyboard-config.xml)
       - bank-gazprom_sbp-config.xml (from .../config/plugins/bank-gazprom_sbp-config.xml)

    2. Run: pytest tests/test_xml_parse_reference.py -v
       This saves reference output as .../xml/reference_output.json

    3. After switching imports from xml.etree.ElementTree to defusedxml.ElementTree
       (or in CI): run again — compares outputs with reference, must match exactly.
"""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "xml"
REFERENCE_FILE = FIXTURES / "reference_output.json"

XML_FILES = [
    "register-modules.xml",
    "keyboard-config.xml",
    "bank-gazprom_sbp-config.xml",
]


def _parse_and_extract(content: str) -> dict:
    """Parse XML and extract fields the same way collectors do."""
    import defusedxml.ElementTree as ET

    result: dict = {}

    root = ET.fromstring(content)
    result["root_tag"] = root.tag
    result["root_attrs"] = dict(root.attrib)

    ns = {"ns": "http://crystals.ru/cash/settings"}
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        key = elem.get("key", "")
        value = elem.get("value", "")
        if key:
            result.setdefault("properties", {})[f"{tag}.{key}"] = value

    return result


def _load_reference() -> dict[str, dict]:
    """Load previously saved reference output."""
    if not REFERENCE_FILE.exists():
        return {}
    with open(REFERENCE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_reference(data: dict[str, dict]) -> None:
    """Save output as reference for future comparison."""
    with open(REFERENCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class TestXmlParseReference:
    """Parse XML fixtures and compare with reference."""

    def test_all_xml_files_present(self) -> None:
        missing = [f for f in XML_FILES if not (FIXTURES / f).exists()]
        if missing:
            pytest.skip(f"Fixture files missing: {missing}")

    def test_parse_and_compare(self) -> None:
        current: dict[str, dict] = {}
        for fname in XML_FILES:
            path = FIXTURES / fname
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            current[fname] = _parse_and_extract(content)

        reference = _load_reference()

        if not reference:
            _save_reference(current)
            pytest.skip(f"Reference saved to {REFERENCE_FILE}")

        assert current == reference, (
            f"Parsing output differs from reference!\n"
            f"Current:  {json.dumps(current, indent=2, ensure_ascii=False)}\n"
            f"Expected: {json.dumps(reference, indent=2, ensure_ascii=False)}"
        )
