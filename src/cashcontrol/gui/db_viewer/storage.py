"""CashControl DB viewer: storage."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QStyle,
)
from qfluentwidgets import (
    FluentIcon,
    InfoBar,
    InfoBarPosition,
)


class _DbError(Exception):
    pass


def _data_dir():
    base = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) \
        else Path(__file__).resolve().parents[3]
    try:
        d = base / 'data'
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        return Path(tempfile.gettempdir()) / 'cashcontrol'


def _load_json(name, default):
    try:
        with open(_data_dir() / name, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(name, obj):
    try:
        with open(_data_dir() / name, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _icon(name):
    try:
        ic = getattr(FluentIcon, name, None)
        if ic is not None:
            return ic.icon()
    except Exception:
        pass
    return QApplication.style().standardIcon(QStyle.SP_FileIcon)


def _toast(widget, kind, text):
    fn = getattr(InfoBar, kind, None)
    if fn:
        fn(title='', content=text, parent=widget.window(),
           position=InfoBarPosition.TOP_RIGHT, duration=4000)


class _Busy:
    def __init__(self, progress):
        self._n, self._p = 0, progress

    def start(self):
        self._n += 1
        self._p.show()

    def stop(self):
        self._n = max(0, self._n - 1)
        if self._n == 0:
            self._p.hide()


