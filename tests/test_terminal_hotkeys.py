"""Горячие клавиши встроенного SSH-терминала.

Терминал запускается отдельным процессом и пишет stderr в файл, поэтому
любое исключение при разборе хоткея выглядит снаружи как «кнопка SSH
ничего не делает».

Коммит linux-port ввёл ``_to_key_combo()`` и наполнил её флагом,
складываемым с ``0``. Shiboken-флаги не поддерживают ``|`` с ``int``,
поэтому конструктор ``QKeyCombination`` падал на первом же модификаторе —
то есть на всех хоткеях сразу, включая Ctrl+N при создании окна.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QKeySequence, QShortcut

_TERMINAL = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "cashcontrol"
    / "builtin"
    / "terminal"
)


@pytest.fixture(scope="module")
def to_key_combo(qapp):
    if str(_TERMINAL) not in sys.path:
        sys.path.insert(0, str(_TERMINAL))
    from ui.main_window import _to_key_combo

    return lambda spec: QKeySequence(_to_key_combo(spec)).toString()


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("Ctrl+N", "Ctrl+N"),
        ("Ctrl+T", "Ctrl+T"),
        ("Ctrl+Alt+D", "Ctrl+Alt+D"),
        ("Ctrl+Space", "Ctrl+Space"),
        ("Shift+T", "Shift+T"),
    ],
)
def test_shortcut_resolves(to_key_combo, spec, expected):
    assert to_key_combo(spec) == expected


def test_no_modifier_is_valid(to_key_combo):
    assert to_key_combo("F5") == "F5"


@pytest.mark.parametrize("spec", ["Ctrl++", "Ctrl+=", "Ctrl+-"])
def test_punctuation_shortcuts_resolve(to_key_combo, spec):
    """Хоткеи шрифта указаны пользователю в подсказке и в меню."""
    assert to_key_combo(spec), f"{spec} не распознан"
    assert to_key_combo(spec) != to_key_combo("F5")


SHORTCUTS_REGISTERED_BY_INIT = [
    "Ctrl+N",
    "Ctrl+T",
    "Ctrl+W",
    "Ctrl+Tab",
    "Ctrl+Shift+Tab",
    "Ctrl++",
    "Ctrl+=",
    "Ctrl+-",
    "Ctrl+0",
    "Ctrl+Alt+M",
    "Ctrl+Alt+D",
]


def test_every_registered_shortcut_is_valid(to_key_combo):
    """Полный список из __init__, ни один не должен остаться пустым."""
    empty = [s for s in SHORTCUTS_REGISTERED_BY_INIT if not to_key_combo(s)]
    assert not empty, f"не распознаны: {empty}"


def test_main_window_constructs(qapp, to_key_combo):
    """Окно терминала должно собираться: раньше падало на первом хоткее."""
    import asyncio

    if str(_TERMINAL) not in sys.path:
        sys.path.insert(0, str(_TERMINAL))
    from ui.main_window import MainWindow

    # Предыдущие тесты могли закрыть глобальный цикл, поэтому свой цикл
    # ставится текущим и намеренно не закрывается: следующим тестам нужен
    # рабочий цикл, а не восстановление отсутствующего.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    window = MainWindow()

    try:
        registered = {s.key().toString() for s in window.findChildren(QShortcut)}
        assert registered, "хоткеи не зарегистрированы"
        missing = [s for s in SHORTCUTS_REGISTERED_BY_INIT if to_key_combo(s) not in registered]
        assert not missing, f"не зарегистрированы: {missing}"
    finally:
        window.deleteLater()
