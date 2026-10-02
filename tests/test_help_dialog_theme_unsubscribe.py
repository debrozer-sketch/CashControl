"""Отписка от сигнала смены темы в окне справки.

Регрессия: ``HelpDialog.closeEvent`` вызывал ``.disconnect()`` на
результате ``Signal.connect()``, а это ``QMetaObject.Connection``, у которого
такого метода нет. Каждое закрытие окна справки давало ``AttributeError``,
из-за чего ``super().closeEvent()`` не доходил, и подписка на тему оставалась
на живом диалоге.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from cashcontrol.gui.dialogs.help_dialog import HelpDialog
from cashcontrol.gui.theme_engine import ThemeEngine


def test_connect_returns_object_without_disconnect():
    """Документирует ловушку: connect() возвращает не Signal."""
    class _Probe(QObject):
        changed = Signal(int)

    probe = _Probe()
    handle = probe.changed.connect(lambda _v: None)

    assert not hasattr(handle, "disconnect"), (
        "в этой версии PySide6 connect() вернул объект с disconnect(); "
        "тест правки нужно пересмотреть"
    )
    assert hasattr(probe.changed, "disconnect")


def test_close_does_not_raise(qtbot):
    """Главный сценарий: открыли справку и закрыли, без traceback."""
    dialog = HelpDialog()
    qtbot.addWidget(dialog)

    dialog.show()
    dialog.close()  # раньше здесь летел AttributeError


def test_close_unsubscribes_from_theme(qtbot, monkeypatch):
    """После закрытия смена темы не должна дёргать слот закрытого диалога.

    Подменяем слот ДО создания диалога: только так disconnect() в closeEvent
    находит по идентичности именно ту функцию, которую подписал конструктор.
    """
    calls: list[str] = []

    def _spy(self) -> None:
        calls.append("theme")

    monkeypatch.setattr(HelpDialog, "_refresh_theme", _spy)

    dialog = HelpDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    engine = ThemeEngine.instance()
    engine.theme_changed.emit("dark")
    assert calls, "до закрытия слот должен вызываться"

    dialog.close()
    calls.clear()
    engine.theme_changed.emit("light")

    assert calls == [], "закрытый диалог всё ещё подписан на смену темы"


def test_double_close_is_safe(qtbot):
    dialog = HelpDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.close()
    dialog.close()  # второй closeEvent уже без подписки


def test_close_without_initialised_subscription(qtbot):
    """closeEvent не должен падать, если подписки не было."""
    dialog = HelpDialog()
    qtbot.addWidget(dialog)

    dialog._theme_conn_signal = None
    dialog.close()  # getattr-ветка


def test_dialog_keeps_signal_reference_not_connection(qtbot):
    dialog = HelpDialog()
    qtbot.addWidget(dialog)

    assert isinstance(dialog._theme_conn_signal, type(ThemeEngine.instance().theme_changed))
    assert not hasattr(dialog._theme_conn_signal, "pid")
