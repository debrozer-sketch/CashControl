"""Панель журнала: строка окрашена по уровню и называет источник.

Панель — вторая половина ``feedback.notify``: всплывашка живёт несколько
секунд, журнал остаётся. Если строки в нём неотличимы друг от друга, то
«в журнале фиксируется всё» выполняется только количественно, а разбираться
в случившемся по-прежнему нечем.

Тесты живут здесь, а не в ``tests/test_feedback.py``: тот модуль проверяет
журнал и склейку без Qt, и добавление сюда виджета заставило бы его
пропускать целиком там, где PySide6 не поставился.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidgetItem

from cashcontrol.gui import feedback
from cashcontrol.gui.notification_manager import Level, Notification
from cashcontrol.gui.status_bar import CashStatusBar
from cashcontrol.gui.theme_helper import color

# Палитра, а не сравнение с «любым не чёрным цветом»: строка должна быть
# окрашена тем же тоном, что и всплывашка того же уровня, иначе окраска
# журнала разойдётся с окраской полоски при первой же правке палитры.
_TINTED = {
    Level.ERROR: "error",
    Level.WARNING: "warning",
    Level.SUCCESS: "success",
}


def _entry(level: Level, message: str = "проверка", title: str = "") -> Notification:
    return Notification(
        id=1,
        timestamp=datetime.now(),
        level=level,
        message=message,
        title=title,
    )


@pytest.fixture
def bar(qapp):
    panel = CashStatusBar()
    yield panel
    panel.deleteLater()


@pytest.mark.parametrize(
    ("level", "tone"),
    sorted(_TINTED.items(), key=lambda pair: pair[0].value),
)
def test_row_is_tinted_with_the_level_tone(bar, level, tone):
    bar.add_notification(_entry(level))

    item = bar._notif_list.item(0)
    assert item is not None
    assert item.foreground().color().name() == QColor(color(tone)).name()


def test_info_row_keeps_the_theme_color(bar):
    """У ``info`` нет своего тона, и красить его нечем.

    ``text_primary`` в палитре зависит от темы, поэтому записанный в строку
    цвет пережил бы смену темы: в тёмном оформлении остался бы светлый
    текст. Строка без явного цвета берёт его у виджета, а тот
    перекрашивается вместе с приложением.
    """
    bar.add_notification(_entry(Level.INFO))

    assert bar._notif_list.item(0).data(Qt.ItemDataRole.ForegroundRole) is None


def test_title_names_the_source_before_the_message(bar):
    """Заголовок виден в строке: без него записи инструментов неразличимы.

    «Экспортировано строк: 5» из db_viewer и из консоли SQL — одна и та же
    строка, и в журнале не остаётся следа, откуда она пришла.
    """
    bar.add_notification(_entry(Level.INFO, message="Экспортировано строк: 5", title="Экспорт"))

    assert bar._notif_list.item(0).text() == "Экспорт — Экспортировано строк: 5"


def test_row_without_title_stays_the_bare_message(bar):
    """Заголовка нет у большинства вызовов, и он не выдумывается."""
    bar.add_notification(_entry(Level.INFO, message="сбор данных"))

    assert bar._notif_list.item(0).text() == "сбор данных"


def test_clear_is_asked_and_the_journal_survives_a_refusal(bar, monkeypatch):
    """Очистка спрашивает и при отказе ничего не трогает.

    Надпись проверяется отдельно от поведения: ``destructive`` дал бы
    «Удалить», а стираются записи журнала, и обещать удаление там нечего.
    """
    bar._switch_tab(1)
    bar.add_notification(_entry(Level.INFO))
    asked: list[dict] = []
    monkeypatch.setattr(feedback, "confirm", lambda *a, **kw: asked.append(kw) or False)

    bar._on_clear()

    assert len(asked) == 1
    assert asked[0].get("yes_text") == "Очистить"
    assert bar._notif_list.count() == 1


def test_confirmed_clear_wipes_only_the_open_tab(bar, monkeypatch):
    """Чистится та вкладка, которую видно, и её источник тоже."""
    bar._switch_tab(1)
    bar.add_notification(_entry(Level.INFO))
    bar._history_list.addItem(QListWidgetItem("история"))
    cleared: list[str] = []

    class _Manager:
        def clear(self) -> None:
            cleared.append("notifications")

    monkeypatch.setattr(feedback, "confirm", lambda *a, **kw: True)
    monkeypatch.setattr(
        "cashcontrol.gui.notification_manager.get_notification_manager",
        lambda: _Manager(),
    )

    bar._on_clear()

    assert bar._notif_list.count() == 0
    assert cleared == ["notifications"]
    assert bar._history_list.count() == 1
