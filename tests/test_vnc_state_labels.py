"""Обработка состояний встроенного VNC в панели сессии.

Регрессия, которую закрывает файл: обработчик начинался с ветки
``if state == "connected"``, которая выставляла только флаг
``_vnc_was_open``. Всё остальное разбиралось в ``elif``-цепочке ниже,
поэтому ветка ``elif state == "connected"`` становилась недостижимой:
подпись оставалась с текстом «Подключение к <ip>», кнопки не
переключались на «отключить», полноэкранный режим не включался. Само
соединение при этом работало.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


class _Panel:
    """Минимальная замена панели: приватные атрибуты с теми же именами."""

    def __init__(self) -> None:
        from PySide6.QtWidgets import QLabel, QPushButton

        self._btn_vnc_connect = QPushButton()
        self._btn_vnc_disconnect = QPushButton()
        self._btn_vnc_fullscreen = QPushButton()
        self._vnc_status_label = QLabel()
        self._vnc_was_open = False


def _apply(panel, state, message=""):
    from cashcontrol.gui.cash_session_widget import CashSessionWidget

    CashSessionWidget._on_vnc_state_changed(panel, state, message)


def test_connected_updates_status_and_buttons(qapp):
    p = _Panel()
    _apply(p, "connected", "● подключено")

    assert p._vnc_was_open is True
    assert p._vnc_status_label.text() == "подключено"
    assert p._btn_vnc_connect.isVisible() is False
    assert p._btn_vnc_disconnect.isVisible() is True
    assert p._btn_vnc_fullscreen.isEnabled() is True


def test_connected_branch_is_not_dead_code(qapp):
    """Две ветки с одинаковым условием означают потерю обработки."""
    import inspect

    from cashcontrol.gui.cash_session_widget import CashSessionWidget

    source = inspect.getsource(CashSessionWidget._on_vnc_state_changed)
    assert source.count('== "connected"') == 1, (
        "условие connected встречается дважды: первая ветка съедает значение, "
        "вторая недостижима"
    )


def test_connecting_keeps_message(qapp):
    p = _Panel()
    _apply(p, "connecting", "⏳ Подключение к 10.0.0.1…")

    assert p._vnc_status_label.text() == "⏳ Подключение к 10.0.0.1…"
    assert p._btn_vnc_connect.isEnabled() is False
    assert p._btn_vnc_disconnect.isVisible() is False
    assert p._btn_vnc_fullscreen.isEnabled() is False


def test_idle_clears_status_and_restores_connect(qapp):
    p = _Panel()
    _apply(p, "connected")
    _apply(p, "idle", "Нажмите «Подключить»")

    assert p._vnc_was_open is False
    assert p._vnc_status_label.text() == ""
    assert p._btn_vnc_connect.isVisible() is True
    assert p._btn_vnc_connect.isEnabled() is True
    assert p._btn_vnc_disconnect.isVisible() is False


def test_error_shows_error_text(qapp):
    p = _Panel()
    _apply(p, "error", "⚠ отказано")

    assert p._vnc_status_label.text() == "ошибка"
    assert p._btn_vnc_connect.isEnabled() is True
    assert p._btn_vnc_disconnect.isVisible() is False


@pytest.mark.parametrize(
    "state,text",
    [
        ("connecting", "Подключение к 1.2.3.4…"),
        ("connected", "подключено"),
        ("error", "ошибка"),
        ("idle", ""),
    ],
)
def test_every_state_reaches_its_label(qapp, state, text):
    p = _Panel()
    _apply(p, state, "Подключение к 1.2.3.4…")
    assert p._vnc_status_label.text() == text, state
