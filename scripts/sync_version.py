#!/usr/bin/env python3
"""Sync version from version.txt into pyproject.toml and package __init__.py."""

import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
version = (_ROOT / "version.txt").read_text(encoding="utf-8").strip()

content = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
content = re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', content)
(_ROOT / "pyproject.toml").write_text(content, encoding="utf-8")

init_path = _ROOT / "src" / "cashcontrol" / "__init__.py"
init_content = init_path.read_text(encoding="utf-8")
init_content = re.sub(
    r'(?m)^__version__ = "[^"]+"', f'__version__ = "{version}"', init_content
)
init_path.write_text(init_content, encoding="utf-8")

print(f"Synced version -> {version}")
