"""Lazy module loading + optional runtime override from the modules/ directory.

In an installed build, selected GUI modules may be replaced by external files
under {app}/modules/** (field hotfix without rebuilding the exe). In dev mode
get_class() simply imports the regular package module.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import _is_production

logger = get_logger()

# Префиксы модулей, которые разрешено переопределять из modules/.
_HOT_PACKAGE_PREFIXES = frozenset({
    "cashcontrol.gui.toolbar",
    "cashcontrol.gui.vnc_preview",
    "cashcontrol.gui.db_viewer",
    "cashcontrol.gui.dialogs",
    "cashcontrol.gui.widgets",
})


def is_module_managed(qualified_name: str) -> bool:
    return any(
        qualified_name == prefix or qualified_name.startswith(prefix + ".")
        for prefix in _HOT_PACKAGE_PREFIXES
    )


class _ModulesFinder(importlib.abc.MetaPathFinder):
    def __init__(self, modules_dir: Path) -> None:
        self._modules_dir = modules_dir

    def find_spec(self, fullname, path, target=None):
        if not fullname.startswith("cashcontrol."):
            return None
        if not is_module_managed(fullname):
            return None

        relative = fullname[len("cashcontrol."):]
        rel_parts = relative.split(".")

        file_path = self._modules_dir.joinpath(*rel_parts).with_suffix(".py")
        if file_path.exists():
            return importlib.util.spec_from_file_location(fullname, file_path)

        init_path = self._modules_dir.joinpath(*rel_parts) / "__init__.py"
        if init_path.exists():
            return importlib.util.spec_from_file_location(fullname, init_path)

        return None


_modules_finder: _ModulesFinder | None = None


def install() -> None:
    """Install the hot-reload finder (idempotent). Must run before any
    managed GUI module is imported."""
    global _modules_finder
    if not _is_production():
        return
    if _modules_finder is not None:
        return

    from cashcontrol.infrastructure.path_resolver import get_app_root

    modules_dir = get_app_root() / "modules"
    if not modules_dir.exists():
        logger.warning(f"modules/ directory not found at {modules_dir}")
        return

    _modules_finder = _ModulesFinder(modules_dir)
    sys.meta_path.insert(0, _modules_finder)
    logger.info(f"Installed hot module finder: {modules_dir}")


_ensure_finder = install


def load_module(qualified_name: str) -> object | None:
    install()
    try:
        return importlib.import_module(qualified_name)
    except ImportError:
        logger.exception(f"Failed to load module: {qualified_name}")
        return None


def get_class(qualified_name: str, class_name: str) -> type:
    module = load_module(qualified_name)
    if module is None:
        rel = qualified_name
        if rel.startswith("cashcontrol."):
            rel = rel[len("cashcontrol."):]
        raise ImportError(
            f"Cannot load module '{qualified_name}' — "
            f"check that modules/{rel.replace('.', '/')}.py exists"
        )
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(
            f"Class '{class_name}' not found in module '{qualified_name}'"
        )
    return cls


if _is_production():
    try:
        install()
    except Exception:
        logger.exception("Failed to install hot module finder on import")
