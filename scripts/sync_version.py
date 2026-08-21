#!/usr/bin/env python3
"""Sync version from version.txt into pyproject.toml."""

import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
version = (_ROOT / "version.txt").read_text(encoding="utf-8").strip()

content = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
content = re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', content)
(_ROOT / "pyproject.toml").write_text(content, encoding="utf-8")
print(f"Synced version -> {version}")