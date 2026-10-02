"""Панель вкладок следует теме.

Три файла `styles/fluent_tabs*.qss` содержали цвета вкладок, зашитые
светлыми: ``#f0f0f0``, ``#e0e0e0``, ``#ffffff``. Подключался только
``fluent_tabs.qss``, и он навешивался на сам виджет, поэтому перебивал
общий QSS темы. В тёмной теме панель вкладок оставалась светлой —
на самом широком и заметном элементе окна.

Варианты ``fluent_tabs_dark.qss`` и ``fluent_tabs_light.qss`` были
написаны, но не подключались нигде.

ThemeEngine уже красит ``TabBar`` для обеих тем через токены, поэтому
собственный stylesheet на виджете не нужен вовсе.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

from cashcontrol.gui import theme_helper
from cashcontrol.gui.theme_engine import ThemeEngine


def _qss(dark: bool, monkeypatch) -> str:
    monkeypatch.setattr(theme_helper, "is_dark", lambda: dark)
    return ThemeEngine()._build_qss(theme_helper.color)


def _block(qss: str, selector: str) -> str:
    """Выдернуть правило вместе с содержимым до следующей закрывающей скобки."""
    start = qss.find(selector)
    if start < 0:
        return ""
    end = qss.find("}", start)
    return qss[start : end + 1]


@pytest.mark.parametrize("dark", [False, True])
def test_theme_styles_tab_bar(dark, monkeypatch):
    qss = _qss(dark, monkeypatch)
    assert "TabBar::tab" in qss, "тема должна красить вкладки сама"


def test_tab_colors_differ_between_themes(monkeypatch):
    light = _qss(False, monkeypatch)
    dark = _qss(True, monkeypatch)
    assert _block(light, "TabBar {") != _block(dark, "TabBar {"), (
        "вкладки в тёмной теме не должны оставаться светлыми"
    )
    assert _block(light, "TabBar::tab {") != _block(dark, "TabBar::tab {")


@pytest.mark.parametrize("dark", [False, True])
def test_tab_colors_come_from_palette(dark, monkeypatch):
    """Цвета вкладок обязаны идти через палитру, иначе они снова разъедутся.

    Собранный QSS содержит hex — токены разворачиваются в него на лету,
    поэтому проверяем происхождение: значение должно совпадать с одним из
    токенов палитры. Какой именно — не важно, важно, что он не зашит руками.
    """
    qss = _qss(dark, monkeypatch)
    palette = {v for pair in theme_helper._COLORS.values() for v in pair}

    for selector in ("TabBar {", "TabBar::tab {", "TabBar::tab:selected {"):
        block = _block(qss, selector)
        assert block, f"нет правила {selector}"
        for hex_color in re.findall(r"#[0-9a-fA-F]{3,8}", block):
            assert hex_color.lower() in {p.lower() for p in palette}, (
                f"цвет {hex_color} в {selector} не из палитры"
            )


def test_tab_manager_has_no_widget_level_stylesheet(qapp, monkeypatch):
    """Свой stylesheet на виджете перебивает общий QSS темы."""
    from cashcontrol.gui.tab_manager import TabManager

    manager = TabManager()
    try:
        sheet = manager.styleSheet()
        assert "TabBar" not in sheet, (
            "панель вкладок не должна краситься в обход темы"
        )
    finally:
        manager.deleteLater()


def test_no_frozen_tab_stylesheet_files_exist():
    """Мёртвые файлы с зашитыми цветами — источник повторной ошибки."""
    from cashcontrol.infrastructure.path_resolver import get_app_root

    root = get_app_root()
    candidates = [
        root / "cashcontrol" / "gui" / "styles",
        root / "gui" / "styles",
        root / "src" / "cashcontrol" / "gui" / "styles",
    ]
    folder = next((d for d in candidates if d.is_dir()), None)
    if folder is None:
        pytest.skip("каталог styles не найден")
    leftovers = [p.name for p in folder.glob("fluent_tabs*.qss")]
    assert not leftovers, f"цвета вкладок должны задаваться токенами темы, а не файлами: {leftovers}"
