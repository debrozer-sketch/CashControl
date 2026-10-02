"""Запрет на возврат к разрозненным способам обратной связи.

Каждый тест ловит конкретный способ, которым проект возвращался к
старым путям: несуществующее значение enum, литералы времени жизни,
прямые вызовы InfoBar и QMessageBox мимо единого API.

Запрет касается всплывашек и модальных окон — того, что прерывает или
отвлекает оператора. Строка состояния окна под него не подпадает: это
элемент управления самого окна, который показывает его собственное
состояние, и в журнал панели по определению не пишет. Поэтому
``statusBar().showMessage`` в ``builtin/file_manager/gui/window.py``
остаётся и сторожем не проверяется.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "cashcontrol"
# Единственный файл, которому положено знать про Qt-обратную связь.
ALLOWED = {"feedback.py"}
# Девять мест, где нужен ответ пользователя: они остаются модальными.
#
# Раньше модальных окон было 31, из них девять с кнопкой выбора, а 22
# информационных. Информационные стали всплывашками; десятое решение или
# потерянное из девяти — регресс, и ловит его ``test_decision_count_matches_registered``.
#
# Плюс два решения сверх исходных девяти: подтверждение записи на кассе у
# проблемы и подтверждение удаления закладки в просмотре БД. Оба и правда
# требуют ответа: первое меняет данные на живой кассе, второе стирает
# файл безвозвратно. Молчаливое применение здесь недопустимо.
DECISION_CALLS = 11


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def _py_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if _rel(p) != "gui/feedback.py"]


def test_top_screen_does_not_exist_in_qfluentwidgets():
    """Причина 12 мёртвых мест: enum не содержит этого значения."""
    from qfluentwidgets import InfoBarPosition

    assert not hasattr(InfoBarPosition, "TOP_SCREEN")


def test_no_top_screen_in_code():
    offenders = [
        f"{_rel(p)}:{i}"
        for p in _py_files()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "TOP_SCREEN" in line and not line.lstrip().startswith("#")
    ]
    assert not offenders, f"TOP_SCREEN не существует в enum: {offenders}"


def test_no_duration_literals_outside_feedback():
    pattern = re.compile(r"duration\s*=\s*\d+")
    offenders = [
        f"{p.relative_to(SRC)}: {line.strip()}"
        for p in _py_files()
        for line in p.read_text(encoding="utf-8").splitlines()
        if pattern.search(line)
    ]
    assert not offenders, f"время жизни задаётся только уровнем: {offenders}"


def test_no_direct_infobar_or_qmessagebox():
    pattern = re.compile(r"\bInfoBar\.(success|error|warning|info)\(|\bQMessageBox\.(information|warning|critical|question)\(")
    offenders = [
        str(p.relative_to(SRC)) for p in _py_files()
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"только через feedback.notify: {offenders}"


def test_no_dialog_is_constructed_outside_feedback():
    """Модальное окно создаёт только ``feedback.confirm``.

    Разбор дерева, а не поиск подстроки: подстрока считала бы ``QMessageBox``
    в QSS-блоке ``theme_engine.py`` и упоминание старого ``QMessageBox`` в
    комментарии ``virtual_keyboard.py``, где оба остаются как объяснение
    прежнего поведения.

    Импорт проверяет ``test_no_qt_feedback_widgets_imported``, здесь ловится
    само создание окна — до него доходит и алиас, и ссылка, полученная из
    функции, и в обоих случаях импортного бана мало.
    """
    offenders = []
    for p in _py_files():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _attribute_chain(node.func)[-1:] in (
                ["MessageBox"],
                ["QMessageBox"],
            ):
                offenders.append(f"{_rel(p)}:{node.lineno}")
    assert not offenders, f"модальные окна только через confirm: {offenders}"


def test_no_qt_feedback_widgets_imported():
    """Qt-обратная связь импортируется только в ``gui/feedback.py``.

    Сравнение идёт по дереву модулей, а не по подстроке: grep пропускает
    ``InfoBar.new(`` и ``getattr(InfoBar, kind)`` из db_viewer — они не
    похожи на запрещённый вызов, но работают так же. Импорт виден в AST.

    Разбираются оба вида: ``from qfluentwidgets import InfoBar`` и
    ``import qfluentwidgets`` с последующим ``qfluentwidgets.InfoBar``.

    Модуль в проверке не значит ничего — ban общий. Раньше смотрели
    только на ``qfluentwidgets``, и ``from PySide6.QtWidgets import
    QMessageBox`` проходил: тот же обход, пришедший из Qt вместо
    обёртки. Проверяется и многоточечный доступ ``import PySide6`` с
    последующим ``PySide6.QtWidgets.QMessageBox``.
    """
    banned = {"InfoBar", "MessageBox", "QMessageBox"}
    offenders = []
    for p in _py_files():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        offenders += [f"{_rel(p)}:{n.lineno} {hit}" for n, hit in _banned_imports(tree, banned)]
        offenders += [f"{_rel(p)}:{n.lineno} {hit}" for n, hit in _banned_attr_imports(tree, banned)]
    assert not offenders, f"Qt-обратная связь живёт только в gui/feedback.py: {offenders}"


def _banned_imports(tree: ast.Module, banned: set[str]) -> list[tuple[ast.AST, str]]:
    """``from <любой модуль> import InfoBar`` и подобное.

    Модуль не проверяется намеренно: ``InfoBar`` из обёртки и
    ``QMessageBox`` из Qt — один и тот же запрещённый путь, и перечислять
    источники в бане значило бы забыть следующий.
    """
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = sorted({alias.name for alias in node.names} & banned)
            if names:
                where = node.module or "."
                hits.append((node, f"from-import {where} {names}"))
    return hits


def _banned_attr_imports(tree: ast.Module, banned: set[str]) -> list[tuple[ast.AST, str]]:
    """``import <любой модуль>`` с обращением ``<модуль>.InfoBar``.

    Обращение может быть в любом месте файла, поэтому атрибуты собраны по
    всему дереву, а не рядом с импортом. ``import PySide6.QtWidgets``
    связывает имя ``PySide6``, а пишется ``PySide6.QtWidgets.QMessageBox`` —
    поэтому раскрывается вся цепочка атрибутов, а не только последний.
    """
    roots = {
        (alias.asname or alias.name).split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    if not roots:
        return []

    used: dict[str, set[str]] = {root: set() for root in roots}
    for node in ast.walk(tree):
        chain = _attribute_chain(node)
        if chain and chain[0] in used:
            used[chain[0]].update(chain[1:])

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            root = (alias.asname or alias.name).split(".")[0]
            hit = sorted(used.get(root, set()) & banned)
            if hit:
                hits.append((node, f"import-attribute {alias.name}.{hit}"))
    return hits


def _attribute_chain(node: ast.AST) -> list[str]:
    """``PySide6.QtWidgets.QMessageBox`` -> ``['PySide6', 'QtWidgets', 'QMessageBox']``.

    Не цепочка — пустой список: у ``a.b()`` или ``f(x)`` атрибута впереди
    нет, и проверять нечего.
    """
    chain: list[str] = []
    while isinstance(node, ast.Attribute):
        chain.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        chain.append(node.id)
    else:
        return []
    chain.reverse()
    return chain


def test_no_private_toast_helper():
    offenders = [
        str(p.relative_to(SRC))
        for p in _py_files()
        if re.search(r"(?<![A-Za-z])_toast\(", p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"свой обход InfoBar больше не нужен: {offenders}"


def test_no_direct_manager_notify():
    offenders = [
        str(p.relative_to(SRC))
        for p in _py_files()
        if "get_notification_manager().notify(" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"запись и показ делает feedback.notify: {offenders}"


def test_the_obsolete_manager_notify_is_gone():
    """Устаревший вход удалён, а не просто не вызывается.

    Проверка на вызовы выше останется зелёной и после того, как метод вернётся:
    никто его звать не станет, и запрет по-прежнему будет выполнен. Смысл
    удаления в том, что возврата быть не может, поэтому проверяется сам
    метод.
    """
    from cashcontrol.gui.notification_manager import NotificationManager

    assert not hasattr(NotificationManager, "notify")


def _decision_sites() -> list[tuple[str, int]]:
    """Места вызова ``confirm`` по всему дереву: путь и строка.

    Ловятся две формы. Основная — ``feedback.confirm(...)``; вторая —
    ``confirm(...)`` после прямого импорта. В дереве нет ни одного такого
    вызова, но пропустить его молча нельзя: тогда число сошлось бы и при
    десяти решениях, одно из которых написано без префикса.

    Регулярка по тексту для этого не годится, и это не вопрос вкуса.
    ``def confirm(paths, recursive) -> bool`` вложен в
    ``_deletion_confirmer`` (``builtin/file_manager/cli.py``), а
    ``on_confirm(...)`` зовётся в ``builtin/file_manager/service.py``: оба
    про перезапись по сети, а не про вопрос пользователю, и регулярка считала
    бы их решениями. Здесь отсекаются они оба — обход идёт по узлам
    ``ast.Call``, а определение функции и вызов чужого метода не вызов.

    Имя метода отсекается тоже: ``self.confirm(...)`` и ``service.confirm``
    не решение, а чужое имя.
    """
    sites: list[tuple[str, int]] = []
    for p in _py_files():
        rel = _rel(p)
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            bare = isinstance(func, ast.Name) and func.id == "confirm"
            qualified = (
                isinstance(func, ast.Attribute)
                and func.attr == "confirm"
                and isinstance(func.value, ast.Name)
                and func.value.id == "feedback"
            )
            if bare or qualified:
                sites.append((rel, node.lineno))
    return sorted(sites)


def test_decision_count_matches_registered():
    """Места, где нужен ответ пользователя.

    Потерянное из списка и появившееся лишнее — регресс, и оба ловятся
    числом: перенос одного решения в другое место даёт то же количество.
    """
    sites = _decision_sites()
    where = ", ".join(f"{rel}:{line}" for rel, line in sites)
    assert len(sites) == DECISION_CALLS, (
        f"ожидалось {DECISION_CALLS} решений, найдено {len(sites)}: {where}"
    )
