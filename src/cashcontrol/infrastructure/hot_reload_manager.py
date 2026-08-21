"""
hot_reload_manager.py — safe hot reload for external modules.

Two reload modes:
  hot  — importlib.reload() + QSS, no restart (only commands/, styles/)
  cold — requires app restart (inside EXE, Nuitka --onefile)

Usage:
    from cashcontrol.infrastructure.hot_reload_manager import HotReloadManager

    mgr = HotReloadManager(registry=mw.registry)
    result = mgr.reload_commands()     # only JSON commands
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_app_root

if TYPE_CHECKING:
    from cashcontrol.actions_registry import ActionsRegistry

logger = get_logger()


# ── File classification by reload type ──
# Single source of truth: module_loader
from cashcontrol.infrastructure.module_loader import is_hot_fs_path as _classify_path


# ── Operation result ─────────────
@dataclass
class ReloadResult:
    reloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cold_required: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        parts = []
        if self.reloaded:
            parts.append(f"reloaded {len(self.reloaded)}")
        if self.errors:
            parts.append(f"errors {len(self.errors)}")
        if self.cold_required:
            parts.append(f"restart required {len(self.cold_required)}")
        if self.skipped:
            parts.append(f"skipped {len(self.skipped)}")
        return "; ".join(parts) if parts else "no changes"


# ── Manager ──────────────────────
class HotReloadManager(QObject):
    """
    Safe hot reload for external Python modules.

    Signals:
        reload_done(ReloadResult)     — reload completed
        restart_required(list[str])   — cold files detected, restart needed
    """

    reload_done = Signal(object)        # ReloadResult
    restart_required = Signal(list)     # list[str] — paths that need restart

    def __init__(self, registry: ActionsRegistry | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._registry = registry
        self._app_root = get_app_root()
        # files_root: where commands/, styles/ live (same logic as update_client)
        _candidate = self._app_root / "cashcontrol"
        self._files_root = _candidate if _candidate.exists() else self._app_root
        _dev_candidate = self._app_root / "src" / "cashcontrol"
        if _dev_candidate.exists():
            self._files_root = _dev_candidate

    # ── Public API ────────────────

    def reload_all(self) -> ReloadResult:
        """
        Reload only external files (commands/, styles/).
        Core modules inside EXE — importlib.reload does not work,
        do not attempt.
        """
        result = ReloadResult()
        cmd_result = self.reload_commands()
        result.reloaded.extend(cmd_result.reloaded)
        result.errors.extend(cmd_result.errors)
        result.cold_required.extend(cmd_result.cold_required)

        if result.cold_required:
            self.restart_required.emit(result.cold_required)
        self.reload_done.emit(result)
        return result

    def reload_module(self, file_path: Path) -> ReloadResult:
        """Reload a single specific file."""
        result = ReloadResult()
        try:
            rel = str(file_path.relative_to(self._files_root)).replace("\\", "/")
        except ValueError:
            try:
                rel = str(file_path.relative_to(self._app_root)).replace("\\", "/")
                if rel.startswith("cashcontrol/"):
                    rel = rel[len("cashcontrol/"):]
            except ValueError:
                rel = file_path.name

        reload_type = _classify_path(rel)
        if reload_type == "cold":
            result.cold_required.append(rel)
            self.restart_required.emit(result.cold_required)
            self.reload_done.emit(result)
            return result

        # Find module name in sys.modules by __file__
        target_name = None
        for name, mod in list(sys.modules.items()):
            f = getattr(mod, "__file__", None)
            if f and Path(f).resolve() == file_path.resolve():
                target_name = name
                break

        if target_name is None:
            result.skipped.append(rel)
            logger.debug(f"[HotReload] Module not loaded, skip: {rel}")
            self.reload_done.emit(result)
            return result

        ok = self._reload_one(target_name, reload_type)
        if ok:
            result.reloaded.append(rel)
        else:
            result.errors.append(rel)
        self.reload_done.emit(result)
        return result

    def reload_commands(self) -> ReloadResult:
        """Rescan commands/ folder and update JSON commands in registry."""
        result = ReloadResult()
        if self._registry is None:
            result.skipped.append("commands (no registry)")
            return result
        try:
            prev_count = len([
                a for a in self._registry.get_all_actions()
                if a.category == "json"
            ])
            self._registry.reload_commands()
            new_count = len([
                a for a in self._registry.get_all_actions()
                if a.category == "json"
            ])
            result.reloaded.append(f"commands ({new_count} total, was {prev_count})")
            logger.info(f"[HotReload] Commands rescanned: {new_count} loaded")
        except Exception as e:
            result.errors.append(f"commands: {e}")
            logger.error(f"[HotReload] Commands reload error: {e}")
        return result

    # ── Internal methods ──────────

    def _reload_one(self, module_name: str, reload_type: str) -> bool:
        """Attempt to reload a single module using module_loader."""
        if reload_type == "hot":
            from cashcontrol.infrastructure.module_loader import reload_module
            return reload_module(module_name)
        return False