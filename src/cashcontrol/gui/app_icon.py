"""App icon helpers shared by the main window and built-in software windows."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from PySide6.QtGui import QIcon

from cashcontrol.infrastructure.path_resolver import get_app_root

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtWidgets import QWidget


@lru_cache(maxsize=1)
def app_icon_path() -> Path:
    root = get_app_root()
    for candidate in (
        root / "icon.ico",
        root / "src" / "cashcontrol" / "gui" / "resources" / "icon.ico",
    ):
        if candidate.is_file():
            return candidate
    return root / "icon.ico"


def app_icon() -> QIcon:
    return QIcon(str(app_icon_path()))


def apply_window_icon(window: QWidget) -> None:
    icon = app_icon()
    if not icon.isNull():
        window.setWindowIcon(icon)
