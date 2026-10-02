"""Изоляция пользовательских данных на время тестов.

Без этой защиты тесты писали в настоящий ``data/`` и ``logs/``:

- ``ConfigManager`` это синглтон с кэшируемым путём, поэтому подмена
  ``_resolve_path`` внутри отдельного теста не действовала, и настройки с
  паролями перезаписывались реальными значениями;
- ``get_logger()`` вызывается на уровне модулей при импорте, то есть ещё
  во время сбора тестов, когда фикстура ещё не отработала.

Поэтому подмена выполняется на уровне импорта этого файла: ``conftest``
загружается раньше, чем собираются тестовые модули, а значит раньше любого
импорта кода приложения.

После сессии временный каталог удаляется, а контрольная сумма настоящего
``settings.json`` сверяется: если тесты его всё же тронули, прогон
помечается проваленным.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_REPO_DATA = _REPO / "data"
_REPO_LOGS = _REPO / "logs"

# ── подмена на уровне импорта, до сбора тестов ──────────────────────────

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="cashcontrol_test_"))
_DATA_DIR = _TMP_ROOT / "data"
_LOGS_DIR = _TMP_ROOT / "logs"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Стартовые справочники без них часть кода ведёт себя иначе, чем в проде.
for _name in ("usb_id_mapping.json", "port_mapping.json"):
    _src = _REPO_DATA / _name
    if _src.is_file():
        shutil.copy2(_src, _DATA_DIR / _name)


def _fake_data_dir() -> Path:
    return _DATA_DIR


def _fake_logs_dir() -> Path:
    return _LOGS_DIR


from cashcontrol.infrastructure import path_resolver as _pr  # noqa: E402

_pr.get_data_dir = _fake_data_dir
_pr.get_logs_dir = _fake_logs_dir

# Модули, которые импортировали функцию напрямую (from ... import get_data_dir)
for _mod_name in (
    "cashcontrol.infrastructure.config_manager",
    "cashcontrol.infrastructure.audit_logger",
    "cashcontrol.infrastructure.seed_defaults",
    "cashcontrol.core.info.collectors._usb_mapper",
    "cashcontrol.gui.session_manager",
):
    try:
        _mod = __import__(_mod_name, fromlist=["_"])
    except Exception:  # pragma: no cover - модуль может отсутствовать
        continue
    for _attr, _replacement in (
        ("get_data_dir", _fake_data_dir),
        ("get_logs_dir", _fake_logs_dir),
    ):
        if hasattr(_mod, _attr):
            setattr(_mod, _attr, _replacement)


def _guard_signature() -> str:
    for path in (_REPO_DATA / "settings.json",):
        if path.is_file():
            st = path.stat()
            return f"{st.st_mtime_ns}:{st.st_size}"
    return "missing"


_BEFORE = _guard_signature()


# ── фикстуры ───────────────────────────────────────────────────────────

@pytest.fixture
def data_dir() -> Path:
    """Изолированный каталог данных текущей сессии."""
    return _DATA_DIR


@pytest.fixture
def config_manager():
    """Свежий ConfigManager на изолированных данных."""
    from cashcontrol.infrastructure.config_manager import ConfigManager

    ConfigManager._instance = None
    try:
        yield ConfigManager()
    finally:
        ConfigManager._instance = None


# ── проверка сохранности реальных данных ───────────────────────────────

def pytest_sessionfinish(session, exitstatus):
    after = _guard_signature()
    if after != _BEFORE:
        session.exitstatus = 1
        print(
            "\n[GUARD] Тесты изменили настоящий data/settings.json: "
            f"было {_BEFORE}, стало {after}. "
            "Проверь conftest.py — изоляция не сработала."
        )


def pytest_unconfigure(config):
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)
