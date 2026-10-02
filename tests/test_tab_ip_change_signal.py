"""Смена IP у вкладки должна обновлять активную кассу у подписчиков.

Регрессия из разбора после инцидента: у вкладки меняли IP на другой, и
`TabManager.change_tab_ip` обновлял `SessionManager.active_ip`, но не отправлял
сигнал `active_tab_changed`. Подписчики — строка состояния и панель уведомлений
— держали собственный адрес: свёрнутая строка продолжала писать «Активная
касса: <старый IP>», а `add_history_entry` отбрасывал записи новой кассы как
чужие (`status_bar.py:164`). То есть после смены IP журнал вкладки был пуст, а
подпись врала.

Сигнал шлётся только если переименованная вкладка была активной. Если активна
другая, ничего не изменилось, и лишний сигнал сбил бы подписчиков с толку.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

TAB_MANAGER = Path(__file__).resolve().parent.parent / "src" / "cashcontrol" / "gui" / "tab_manager.py"


def _function_source(name: str) -> str:
    tree = ast.parse(TAB_MANAGER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{TAB_MANAGER} : функция {name} не найдена")


def test_change_tab_ip_emits_active_tab_changed():
    """Сигнал обязан уходить, иначе подписчики остаются со старым адресом."""
    src = _function_source("change_tab_ip")
    assert "active_tab_changed.emit" in src, (
        "change_tab_ip не отправляет active_tab_changed: строка состояния "
        "продолжит называть активной старую кассу, а журнал отбросит записи "
        "новой"
    )


def test_active_ip_is_set_before_the_signal():
    """Сначала адрес, потом сигнал: подписчик читает уже новое значение."""
    src = _function_source("change_tab_ip")
    set_at = src.find("self._session_mgr.active_ip = new_ip")
    emit_at = src.find("active_tab_changed.emit")
    assert set_at != -1, "change_tab_ip не обновляет active_ip"
    assert emit_at != -1
    assert set_at < emit_at, (
        "сигнал ушёл раньше обновления active_ip: подписчик успеет прочитать "
        "старый адрес"
    )


def test_signal_is_sent_only_for_the_renamed_active_tab():
    """Активна другая вкладка — события не было, значит и сигнала быть не должно."""
    src = _function_source("change_tab_ip")
    was_active = src.find("was_active =")
    guarded = src.find("if was_active:")
    emit = src.find("active_tab_changed.emit")
    assert was_active != -1, "нет флага, что вкладка была активной"
    assert guarded != -1, "отправка сигнала не под защитой was_active"
    assert emit > guarded, (
        "сигнал отправляется всем подряд: неактивная вкладка объявила бы "
        "активной себя"
    )


def test_ping_moves_with_the_ip():
    """Прежняя проверка: задача пинга должна следовать за адресом."""
    src = _function_source("change_tab_ip")
    assert "self._start_ping(new_ip)" in src
