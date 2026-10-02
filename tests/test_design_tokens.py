"""Токены типографики и размеров.

Цвета в проекте именованы по смыслу, а кегли и отступы писались руками в
восьми значениях (9/11/12/13/14/15/16/20px) без токенов. Из-за этого
подписи одного назначения различались размером, и любая правка требовала
обхода всех мест.

Здесь проверяется, что токены существуют, покрывают все размеры, которые
реально встречаются в коде, и что их использование не даёт завести новое
значение руками.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from cashcontrol.gui import theme_helper

SRC = Path(__file__).resolve().parent.parent / "src" / "cashcontrol"

# Размеры, встречавшиеся в QSS виджетов до появления токенов. Значение 15px
# сюда не входит: это h2 внутри HTML-справки (help_css.py), у которой своя
# связная шкала h1/h2/h3 и уже есть токены цветов.
SIZES_SEEN_IN_CODE = {9, 11, 12, 13, 14, 16, 20}

# Модули с собственной типографикой: собирают QSS или шкалу HTML-справки.
# help_content.py собирает ту же HTML-страницу справки, что и help_css.py,
# поэтому кегли в нём подчинены шкале h1/h2/h3, а не токенам виджетов.
_SCALE_OWNERS = {
    "theme_engine.py",
    "help_css.py",
    "help_content.py",
    "theme_helper.py",
}

# Токены, которые вставляются в строку. Проверяется всё дерево пакета, а не
# только ``gui``: обрезанный вызов одинаково тих в любом модуле.
TOKEN_CALLS = ("font_size(", "control_size(", "label_width(")

# Цветовые токены и обёртки вокруг них. Отдельным списком, а не дописыванием к
# общему: у них другой механизм отказа и другое место в QSS.
#
# Потерянный ``f`` на вызове цвета даёт не обрезанное CSS-свойство, а
# ``{_tc('bg_secondary')}`` текстом в таблице стилей. Qt разбирает значение
# как строку, не находит в ней ни одного допустимого цвета и отбрасывает
# объявление целиком — без строки в выводе, как и обрезанный ``font-size``.
# Сторож на обрезанные свойства (``TRUNCATED_PROPERTIES``) такой случай по
# построению не видит: режется не первая буква свойства, а ничего.
#
# Список собран разбором дерева, а не чтением: сначала найдены вызовы,
# которые реально стоят внутри f-строк (``_tc`` — 117 мест, ``_thc`` — 1,
# ``color`` — 1, ``get_panel_bg`` — 2). ``colors`` и ``styled`` дописаны
# потому, что это публичные обёртки того же назначения из ``theme_helper``:
# сегодня они не используются, и их появление в обычной строке должно
# ловиться тем же сторожем, а не отдельной правкой.
COLOR_TOKEN_CALLS = ("_tc(", "_thc(", "color(", "colors(", "styled(", "get_panel_bg(")

# CSS-свойства, которые теряют первую букву вместе с ``f``-префиксом.
TRUNCATED_PROPERTIES = ("ont-family", "ont-size", "ont-weight", "ont-style")


def test_every_size_used_in_code_has_a_token():
    """Новое значение без токена — повторение той же проблемы."""
    assert set(theme_helper.FONT_SIZE.values()) >= SIZES_SEEN_IN_CODE, (
        "размер, встречающийся в коде, не покрыт токеном"
    )


def test_font_size_roles_are_named():
    assert set(theme_helper.FONT_SIZE) == {
        "micro",
        "hint",
        "body",
        "section",
        "value",
        "title",
        "display",
    }


def test_font_size_is_monotonic():
    """Роли должны идти по возрастанию, иначе имена врут."""
    values = [theme_helper.FONT_SIZE[k] for k in ("micro", "hint", "body", "section", "value", "title", "display")]
    assert values == sorted(values), f"порядок ролей нарушен: {values}"


def test_unknown_role_falls_back_to_body():
    assert theme_helper.font_size("nope") == theme_helper.FONT_SIZE["body"]


def test_control_and_label_tokens_exist():
    assert theme_helper.control_size("row") > 0
    assert theme_helper.label_width("settings") > 0
    assert theme_helper.control_size("nope") == theme_helper.CONTROL_SIZE["row"]
    assert theme_helper.label_width("nope") == theme_helper.LABEL_WIDTH["settings"]


@pytest.mark.parametrize("token", ["micro", "hint", "body"])
def test_tokens_are_used_in_core(token):
    """Токен должен реально применяться, а не просто существовать."""
    core = SRC / "gui"
    used = False
    for path in core.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "font_size(" in text and f"'{token}'" in text:
            used = True
            break
    assert used, f"токен '{token}' не используется ни в одном файле ядра"


def test_no_new_font_size_literals_in_widget_styles():
    """Кегль в QSS виджета берётся из токена, а не вписывается руками.

    Раньше таких мест было 36, и они расползались по восьми значениям.
    Собственная типографика разрешена только у модулей, которые её и
    собирают: тема и шкала HTML-справки.
    """
    pattern = re.compile(r"font-size:\s*(\d+)px")
    offenders: list[str] = []
    for path in sorted((SRC / "gui").rglob("*.py")):
        if path.name in _SCALE_OWNERS:
            continue
        text = path.read_text(encoding="utf-8")
        for number in pattern.findall(text):
            offenders.append(f"{path.relative_to(SRC.parent)}: font-size: {number}px")
    assert not offenders, (
        "кегли в QSS виджетов должны идти через font_size(...):\n  "
        + "\n  ".join(offenders)
    )


# ── сторож на обрезанные строки ──────────────────────────────────────
#
# ``"ff"`` -> ``""`` в прошлой правке чинил двоение буквы ``f``, но срезал
# и первую букву в строках, начинающихся с ``"font-``. Результат не был
# виден ни в одном сообщении: Qt молча отбрасывает объявление с
# неизвестным свойством, и кегль просто не применяется.


def _docstrings(tree: ast.AST) -> set[int]:
    """``id()`` узлов-докстрингов: пример в тексте писать можно.

    Отдельно, потому что докстринг — это тоже ``ast.Constant`` со строкой,
    и без этого списка пример в ``theme_helper.font_size`` считался бы
    дефектом.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            ids.add(id(body[0].value))
    return ids


def _string_literals(tree: ast.Module):
    """Строковые литералы дерева, кроме докстрингов.

    Обход один на оба сторожа: внутри f-строки ``ast`` хранит и текстовые
    куски, поэтому склейка ``f"..." "..."`` не прячет обрезанный литерал
    во втором куске.
    """
    skip = _docstrings(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
        ):
            yield node


def _plain_token_calls(names: tuple[str, ...]) -> list[str]:
    """Литералы, где вызов токена остался текстом, а не вызовом."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _string_literals(tree):
            hit = sorted(name for name in names if name in node.value)
            if hit:
                offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno} {hit}")
    return offenders


def test_token_call_written_as_plain_text():
    """Вызов токена в обычной строке — это текст, а не вызов.

    По узлам ``ast.Call`` искать бесполезно: в обычной строке
    ``font_size('body')`` не создаёт узел вызова, поэтому дефект и не
    виден в дереве. Смотрим текст литерала.

    Докстринги исключены: в ``theme_helper.font_size`` пример usage
    написан как раз обычным текстом, и это правильно.
    """
    offenders = _plain_token_calls(TOKEN_CALLS)
    assert not offenders, (
        "вызов токена должен быть f-строкой, иначе он остаётся текстом:\n  "
        + "\n  ".join(offenders)
    )


def test_color_token_call_written_as_plain_text():
    """Тот же дефект на цвете: ``{_tc('bg_secondary')}`` уходит в QSS текстом.

    Отдельная функция, а не ещё один элемент в общий список: у цветового
    токена другой отказ и другое место в таблице стилей (см.
    ``COLOR_TOKEN_CALLS``), и сваливать его в тот же параметр значило бы
    получить один падающий тест вместо двух с понятными именами.
    """
    offenders = _plain_token_calls(COLOR_TOKEN_CALLS)
    assert not offenders, (
        "вызов цветового токена должен быть f-строкой, иначе в QSS уходит "
        "текст в фигурных скобках, а Qt молча отбрасывает объявление:\n  "
        + "\n  ".join(offenders)
    )


def _cut_properties(value: str) -> list[str]:
    """Свойства, потерявшие первую букву, — в любом месте литерала.

    Разбор объявлений по ``;``, а не поиск подстроки: ``font-size`` внутри
    слова содержит ``ont-size``, и подстрока ловила бы исправные строки.
    Проверки одного только начала литерала мало: при склейке
    ``f"..." "..."`` соседние куски сливаются в один ``Constant``, и
    обрезанное свойство оказывается не в начале, а после ``;``
    предыдущего объявления.
    """
    return [
        part.lstrip()
        for part in value.split(";")
        if part.lstrip().startswith(TRUNCATED_PROPERTIES)
    ]


def test_no_literal_starts_with_a_cut_css_property():
    """Литерал с обрезанным CSS-свойством — это не то, что писали.

    Обрезанное свойство ищется в любом объявлении литерала, а не в
    начале: см. ``_cut_properties``.
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _string_literals(tree):
            cut = _cut_properties(node.value)
            if cut:
                offenders.append(
                    f"{path.relative_to(SRC.parent)}:{node.lineno} {cut[0][:48]}"
                )

    assert not offenders, (
        "CSS-свойство потеряло первую букву вместе с f-префиксом:\n  "
        + "\n  ".join(offenders)
    )
