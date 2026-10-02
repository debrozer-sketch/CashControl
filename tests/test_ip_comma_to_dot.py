"""Запятая в поле IP превращается в точку.

Пользователи с русской раскладкой набирают адрес как ``192,168,1,10``.
Замена происходит во время ввода, без участия пользователя, без потери позиции
курсора и без рекурсии по textChanged.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLineEdit

from cashcontrol.gui.ip_input import install_comma_to_dot, normalize_ip_text


@pytest.fixture
def edit(qtbot):
    e = QLineEdit()
    qtbot.addWidget(e)
    install_comma_to_dot(e)
    return e


def _type(edit: QLineEdit, text: str) -> None:
    """Эмулирует ввод с клавиатуры: textEdited срабатывает, setText — нет."""
    edit.setCursorPosition(0)
    for ch in text:
        edit.setText(edit.text() + ch)
        edit.textEdited.emit(edit.text())


# ── чистая функция ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("192,168,1,10", "192.168.1.10"),
        ("10,0,0,1", "10.0.0.1"),
        ("192.168.1.10", "192.168.1.10"),
        ("", ""),
        ("не ip", "не ip"),
    ],
)
def test_normalize(raw, expected):
    assert normalize_ip_text(raw) == expected


# ── поведение поля ─────────────────────────────────────────────────────

def test_typing_with_commas_produces_dots(edit):
    """Главный сценарий: пользователь набирает адрес с запятыми."""
    _type(edit, "192,168,1,10")
    assert edit.text() == "192.168.1.10"


def test_single_comma_replaced(edit):
    _type(edit, "10,0,0,1")
    assert edit.text() == "10.0.0,1".replace(",", ".")
    assert "," not in edit.text()


def test_typing_dots_untouched(edit):
    _type(edit, "172.18.105.97")
    assert edit.text() == "172.18.105.97"


def test_cursor_position_preserved(edit):
    edit.setText("192,168,1,10")
    edit.setCursorPosition(7)
    edit.textEdited.emit(edit.text())
    assert edit.cursorPosition() == 7
    assert edit.text() == "192.168.1.10"


def test_mixed_separators(edit):
    _type(edit, "172,18.105,97")
    assert edit.text() == "172.18.105.97"


def test_settext_does_not_recurse(edit):
    """Программная установка текста не должна вызывать нормализацию."""
    edit.setText("1,2,3,4")
    # textEdited при setText не приходит, но проверяем что и без вызова
    # обработчика значение осталось как задано программой
    assert edit.text() == "1,2,3,4"


# ── подключение в реальных местах ──────────────────────────────────────

def test_add_cash_dialog_installs_helper(qtbot):
    import inspect
    import textwrap

    from cashcontrol.gui.dialogs.add_cash_dialog import AddCashDialog

    src = textwrap.dedent(inspect.getsource(AddCashDialog._init_ui))
    assert "install_comma_to_dot" in src, (
        "диалог добавления кассы не подключил замену запятой"
    )


def test_tab_ip_edit_installs_helper():
    import inspect
    import textwrap

    from cashcontrol.gui.cash_session_widget import CashSessionWidget

    src = textwrap.dedent(inspect.getsource(CashSessionWidget.start_ip_edit))
    assert "install_comma_to_dot" in src, (
        "поле смены IP в вкладке не подключило замену запятой"
    )


def test_add_cash_dialog_normalizes_on_accept(qtbot):
    """Даже если запятая просочилась в обход нормализации, при добавлении
    она станет точкой, иначе жёсткая валидация отклонит адрес."""
    from cashcontrol.gui.dialogs.add_cash_dialog import AddCashDialog

    dlg = AddCashDialog()
    qtbot.addWidget(dlg)
    dlg._ip_input.setText("10,0,0,5")   # программная установка, без textEdited
    dlg._on_ok()

    assert "," not in dlg._ip_input.text(), "запятая не нормализована при добавлении"
    assert dlg.get_ip() == "10.0.0.5"
