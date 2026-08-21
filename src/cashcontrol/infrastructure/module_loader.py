from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path

from cashcontrol.infrastructure.audit_logger import get_logger

logger = get_logger()


def _find_prefixes_file() -> Path | None:
    candidates: list[Path] = []

    candidates.append(Path(__file__).resolve().parent / "hot_prefixes.json")

    try:
        from cashcontrol.infrastructure.path_resolver import get_app_root
        root = get_app_root()
        for sub in ("src", "."):
            candidates.append(root / sub / "cashcontrol" / "infrastructure" / "hot_prefixes.json")
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "cashcontrol" / "infrastructure" / "hot_prefixes.json")

    try:
        from __compiled__ import containing_dir
        candidates.append(Path(containing_dir).resolve() / "hot_prefixes.json")
    except (ImportError, AttributeError):
        pass

    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate

    return candidates[0] if candidates else None


_HOT_PREFIXES_FILE = _find_prefixes_file()


def _load_hot_prefixes() -> tuple[frozenset[str], frozenset[str]]:
    path = _HOT_PREFIXES_FILE
    if path and path.exists():
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            pkg = frozenset(data.get("hot_package_prefixes", []))
            fs = frozenset(data.get("hot_fs_prefixes", []))
            if not pkg:
                logger.error(
                    f"hot_prefixes.json at {path} is malformed — "
                    f"'hot_package_prefixes' is empty or missing. "
                    f"Hot-reloadable GUI modules will be UNAVAILABLE in this session."
                )
            elif not fs:
                logger.error(
                    f"hot_prefixes.json at {path} is malformed — "
                    f"'hot_fs_prefixes' is empty or missing. "
                    f"All updates will be classified as 'cold'."
                )
            else:
                return pkg, fs
        except Exception as e:
            logger.error(
                f"Failed to load hot_prefixes.json from {path}: {e}. "
                f"Hot-reloadable GUI modules will be UNAVAILABLE in this session."
            )
    else:
        logger.error(
            f"hot_prefixes.json not found (checked {path}). "
            f"Hot-reloadable GUI modules will be UNAVAILABLE in this session."
        )

    return (
        frozenset(),
        frozenset({"commands/", "styles/", "modules/"}),
    )


_HOT_PACKAGE_PREFIXES, _HOT_FS_PREFIXES = _load_hot_prefixes()


def is_module_managed(qualified_name: str) -> bool:
    for prefix in _HOT_PACKAGE_PREFIXES:
        if qualified_name == prefix or qualified_name.startswith(prefix + "."):
            return True
    return False


def is_hot_fs_path(rel_path: str) -> bool:
    rel = rel_path.replace("\\", "/")
    for prefix in _HOT_FS_PREFIXES:
        if rel.startswith(prefix):
            return True
    return False


def _is_production() -> bool:
    if getattr(sys, "frozen", False):
        return True
    try:
        import __compiled__
        return True
    except ImportError:
        pass
    if sys.executable.lower().endswith(".exe"):
        exe_dir = Path(sys.executable).parent
        marker = exe_dir / "cashcontrol" / "infrastructure" / "hot_prefixes.json"
        if marker.exists():
            return True
    return False


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


def _ensure_finder() -> None:
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


def get_modules_dir() -> Path | None:
    if not _is_production():
        return None
    from cashcontrol.infrastructure.path_resolver import get_app_root
    modules_dir = get_app_root() / "modules"
    if modules_dir.exists():
        return modules_dir
    return None


def load_module(qualified_name: str) -> object | None:
    _ensure_finder()
    try:
        return importlib.import_module(qualified_name)
    except ImportError:
        logger.exception(f"Failed to load module: {qualified_name}")
        return None


def reload_module(qualified_name: str) -> bool:
    module = sys.modules.get(qualified_name)
    if module is None:
        logger.debug(f"Module {qualified_name} not loaded, cannot reload")
        return False
    try:
        importlib.reload(module)
        logger.info(f"Hot reloaded: {qualified_name}")
        return True
    except Exception:
        logger.exception(f"Hot reload failed for {qualified_name}")
        return False


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
