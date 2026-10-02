"""Пункты меню настроек не должны наползать друг на друга.

Регрессия: у ``QListWidget::item`` в QSS были заданы ``min-height: 34px`` и
``margin: 2px 4px``. Qt не учитывает margin из таблицы стилей при раскладке
списка: строка выделяется по sizeHint делегата, а рисуется выше, поэтому
пункты накапливали смещение и наползали. Размер перенесён в setSizeHint.
"""

from __future__ import annotations

import pytest

from cashcontrol.gui.dialogs.settings.settings_dialog import (
    _MENU_ITEM_HEIGHT,
    _PAGES,
    SettingsDialog,
)


@pytest.fixture
def dialog(qtbot):
    dlg = SettingsDialog()
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    return dlg


def test_pages_and_items_match(dialog):
    assert dialog._menu.count() == len(_PAGES)


def test_items_do_not_overlap(dialog):
    """Главный симптом: соседние пункты не должны перекрываться."""
    menu = dialog._menu
    rects = [menu.visualItemRect(menu.item(i)) for i in range(menu.count())]

    for i in range(1, len(rects)):
        assert rects[i].top() >= rects[i - 1].bottom(), (
            f"пункт {i} наползает на {i - 1}: "
            f"top={rects[i].top()} < bottom={rects[i - 1].bottom()}"
        )


def test_painted_height_matches_allocated_height(dialog):
    """Высота отрисовки обязана совпадать с sizeHint, иначе QSS разъезжается."""
    menu = dialog._menu
    for i in range(menu.count()):
        visual = menu.visualItemRect(menu.item(i)).height()
        hint = menu.sizeHintForRow(i)
        assert visual == hint, (
            f"пункт {i}: отрисовано {visual}px, выделено {hint}px. "
            "Так и наползают пункты: Qt верстает по sizeHint, а рисует по QSS."
        )


def test_item_height_is_explicit(dialog):
    for i in range(dialog._menu.count()):
        assert dialog._menu.sizeHintForRow(i) == _MENU_ITEM_HEIGHT


def test_no_min_height_or_margin_in_item_stylesheet(dialog):
    """Причина регрессии: min-height и margin в QSS пункта списка."""
    qss = dialog._menu.styleSheet()
    assert "min-height" not in qss, "min-height в QSS ломает раскладку пунктов"
    assert "margin" not in qss, "margin в QSS не учитывается Qt при раскладке"
