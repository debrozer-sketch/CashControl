"""CashControl DB viewer: storage."""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QApplication,
    QStyle,
)
from qfluentwidgets import FluentIcon

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_data_dir

logger = get_logger()


class _DbError(Exception):
    pass


def _data_dir():
    return get_data_dir()


def _load_json(name, default):
    try:
        with open(_data_dir() / name, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(name, obj):
    """Сохранить настройки окна.

    Отказ записи проглатывался целиком: пользователь закрывал настройки,
    думая, что они сохранены, а при следующем запуске всё возвращалось к
    прежнему виду без единого следа. Теперь причина попадает в журнал.
    """
    try:
        with open(_data_dir() / name, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    except Exception as exc:
        logger.warning("Настройки просмотра БД не сохранены (%s): %s", name, exc)


def _icon(name):
    try:
        ic = getattr(FluentIcon, name, None)
        if ic is not None:
            return ic.icon()
    except Exception as exc:
        logger.debug("Иконка %s недоступна, берётся системная: %s", name, exc)
    return QApplication.style().standardIcon(QStyle.SP_FileIcon)


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


