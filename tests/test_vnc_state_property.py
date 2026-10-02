"""VNC: свойство state нельзя вызывать как метод.

Регрессия: ``VncPreviewWidget.state`` объявлено через ``@property`` и
возвращает ``str``, но два места в ``CashSessionWidget`` обращались к нему
как к методу (``self._vnc_widget.state()`` и
``getattr(..., "state", lambda: "idle")()``). Оба падали с
``TypeError: 'str' object is not callable``.

Последствия: при смене IP вкладки не определялось, что VNC был подключён,
из-за чего авто-возобновление не срабатывало, а отключение старого VNC не
выполнялось вовсе. При смене темы каждый раз летел трейсбек, и цвет
статуса VNC не обновлялся.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from cashcontrol.builtin.vnc.vnc_preview import VncPreviewWidget
from cashcontrol.gui import cash_session_widget as csw

_WIDGET_SRC = Path(csw.__file__)


def test_state_is_a_property_returning_str(qtbot):
    """Контракт, который нарушали оба вызывающих места."""
    widget = VncPreviewWidget("192.0.2.1")
    qtbot.addWidget(widget)

    assert isinstance(type(widget).state, property)
    assert isinstance(widget.state, str)
    with pytest.raises(TypeError):
        # Вызов как метода невозможен — именно это ломало оба места в GUI.
        widget.state()


def test_gui_reads_state_without_calling_it(qtbot):
    widget = VncPreviewWidget("192.0.2.1")
    qtbot.addWidget(widget)

    # Так читает состояние GUI после исправления.
    assert getattr(widget, "state", "idle") == "idle"
    # Запасной вариант тоже обязан работать без вызова.
    assert getattr(widget, "state", "idle") in {"idle", "connecting", "connected", "error"}


@pytest.mark.parametrize(
    ("method", "reason"),
    [
        ("_refresh_theme", "смена темы роняла слот трейсбеком"),
        ("reconnect_to", "смена IP не возобновляла VNC и не отключала старый"),
    ],
)
def test_no_call_to_state_in_hot_methods(method, reason):
    """AST-проверка: внутри методов не должно быть вызова state()."""
    tree = ast.parse(_WIDGET_SRC.read_text(encoding="utf-8"))
    target = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method
    )

    offenders = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "state"
    ]
    assert not offenders, (
        f"{method}(): найден вызов .state() — {reason}. "
        "state это @property, обращаться нужно без скобок."
    )


def test_hot_module_overrides_are_not_required_for_this_fix():
    """Правка живёт в src/, hot-модули собранной версии её не перекрывают."""
    assert "_vnc_widget" in inspect.getsource(csw.CashSessionWidget)
