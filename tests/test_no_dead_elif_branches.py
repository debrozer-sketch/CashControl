"""Запрет недостижимых веток в цепочках if/elif.

Ошибка уже была в коде: обработчик состояний VNC начинался с
``if state == "connected"``, выставлявшим один флаг, а ниже стояла
ветка ``elif state == "connected"`` с полноценной отрисовкой. Вторая
ветка не выполнялась никогда, из-за чего подпись зависала на тексте
«Подключение к <ip>», хотя соединение работало.

Проверка идёт по AST, поэтому не зависит от форматирования и не требует
запуска Qt.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


def _chain_conditions(node: ast.If) -> list[str]:
    """Условия всей цепочки if/elif, начинающейся в node."""
    out: list[str] = []
    current: ast.If | None = node
    while current is not None:
        out.append(ast.dump(ast.Expression(current.test)))
        orelse = current.orelse
        current = orelse[0] if len(orelse) == 1 and isinstance(orelse[0], ast.If) else None
    return out


def _files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_src_is_not_empty():
    assert _files(), "не найдено ни одного модуля в src/"


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_no_duplicate_condition_in_elif_chain(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        conditions = _chain_conditions(node)
        if len(conditions) != len(set(conditions)):
            seen: set[str] = set()
            duplicates = {c for c in conditions if c in seen or seen.add(c)}  # type: ignore[func-returns-value]
            problems.append(f"строка {node.lineno}: {len(duplicates)} повтор(ов) условия")
    assert not problems, "; ".join(problems)
