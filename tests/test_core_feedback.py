"""Обратная связь ядра и инструментов: контракт переведённых файлов.

Сторож в ``test_feedback_guards.py`` ловит форму по всему дереву, но половину
этого набора он не видел: имена файлов лежали в ``PENDING``, а
``builtin/terminal/ui/main_window.py`` в отдельном процессе импортируется не
так, как остальные. Здесь проверяется содержание вызовов: сколько их, у всех
ли назван окно, какие заголовки и уровни пережили перенос и что решение
осталось в синхронном слоте.

Числа взяты разбором дерева, а не пересказом брифа: бриф назвал 25 мест, по
коду их оказалось 35. Разницу дал ``gui/cash_session_widget.py`` — бриф посчитал
в нём три прямых вызова и не учёл семь, сделанных через локальный псевдоним
``notify``, который после перевода на ``feedback.notify`` просто исчез бы.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "cashcontrol"

# Относительный путь -> (вызовов notify, вызовов confirm).
#
# Ноль в window.py не опечатка: строка состояния CashSCP — его собственный
# элемент управления, и она осталась на статус-баре. Ноль закреплён, чтобы
# перенос обратно на всплывашку «Готово» при каждом открытии окна упал
# отдельным падением.
EXPECTED = {
    "builtin/file_manager/gui/session.py": (8, 0),
    "builtin/file_manager/gui/window.py": (0, 0),
    "gui/dialogs/command_editor.py": (4, 1),
    "gui/dialogs/settings/settings_dialog.py": (3, 0),
    "gui/dialogs/settings/tab_logs.py": (3, 1),
    "gui/dialogs/settings/tab_connection.py": (0, 2),
    # Мастер предупреждения копит, а не показывает: на сигнале finished
    # диалог уже скрыт, и полоса с его родителем не появилась бы. Показывает
    # их вызывающий код, то есть main.py.
    "gui/dialogs/setup_wizard/wizard.py": (0, 0),
    # Заголовок «Внимание» переехал сюда вместе с показом: единственное
    # место, где мастер отдаёт накопленное наружу.
    "main.py": (1, 0),
    "builtin/terminal/ui/main_window.py": (2, 0),
    "gui/widgets/virtual_keyboard.py": (2, 0),
    "gui/widgets/info_section_widget.py": (0, 1),
    "gui/cash_session_widget.py": (16, 0),
}

# Подавление RuntimeError на пяти местах выгрузки. Число мест, а не «есть
# где-то»: снятие одного подавления не меняет ни одного числа вызовов
# notify, и без этого якоря откат остаётся зелёным.
UPLOAD_FUNC = "_upload_to_cash"
EXPECTED_UPLOAD_NOTIFY = 5

# Решение, перенесённое прошлой партией: в наборе этой партии его нет, но
# вместе с пятью своими местами оно даёт шесть — число, на которое ссылался
# бриф. Проверяется отдельно, чтобы переезд следующей партии не сдвинул его
# молча.
DB_VIEWER = "builtin/db_viewer/data_panel.py"
# Плюс два confirm — подтверждение записи на кассе у проблемы и удаления
# закладки в просмотре БД. Вызываются не из задачи, а из Qt-слота:
# внутри asyncio-колбэка exec() роняет вложенный цикл. Это проверяется
# отдельно тестом на async-контекст.
EXPECTED_CONFIRM = 6
EXPECTED_CONFIRM_WITH_DB_VIEWER = 7

# Способы, которыми проект возвращался к разрозненной обратной связи.
# Информационный вызов не содержит выбора, и переносить его надлежит в
# журнал с всплывашкой, а не в модальное окно.
#
# Запрет касается всплывашек и модальных окон. Строка состояния окна сюда
# не входит: это элемент управления самого окна, а не сообщение оператору
# через общий канал, поэтому ``statusBar().showMessage`` в
# ``builtin/file_manager/gui/window.py`` — законный вызов и не проверяется.
BANNED = ("QMessageBox", "MessageBox")

# Заголовок второго аргумента старых окон — осмысленная часть сообщения.
# Потерянный заголовок не ломает код, но в журнале остаётся текст без
# указания, какое действие его вызвало.
EXPECTED_TITLES = {
    "Свойства",
    "CashSCP",
    "Копирование",
    "Переименование",
    "Редактор",
    "Ошибка",
    "Папка логов",
    "Внимание",
    "Сниппеты",
    "Ошибка подключения",
    "Сохранено",
    "Готово",
}


# ── разбор дерева ──────────────────────────────────────────────────


def _tree(rel: str) -> ast.Module:
    return ast.parse((SRC / rel).read_text(encoding="utf-8"))


def _calls(tree: ast.Module, name: str) -> list[tuple[int, ast.Call]]:
    """Вызовы ``feedback.<name>(...)`` с номером строки.

    Разбор дерева, а не поиск подстроки: подстрока поймала бы определение,
    комментарий и вызов через локальный импорт. Дерево передаётся
    аргументом — поиск владельца узла идёт по идентичности, а два разбора
    дают два разных дерева.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == name
            and isinstance(func.value, ast.Name)
            and func.value.id == "feedback"
        ):
            found.append((node.lineno, node))
    return sorted(found)


def _attribute_chain(node: ast.AST) -> list[str]:
    """``self.statusBar().showMessage`` -> ``['self', 'statusBar', 'showMessage']``.

    Цепочка разбирается целиком, а не только по внешнему атрибуту: возврат
    старого пути приходит именно цепочкой, и по узлам ``ast.Call`` без неё
    не виден.
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


def _enclosing(tree: ast.Module, target: ast.AST) -> ast.AST | None:
    """Ближайшая внешняя функция, внутри которой лежит узел.

    Подъём по родителям, а не обход в ширину: обход в ширину отдаёт первую
    найденную функцию, то есть самую внешнюю, и ``confirm`` внутри
    ``async def inner()`` внутри ``def outer()`` проскакивал. В дереве
    вложенные корутины есть, и цепочка
    ``virtual_keyboard._on_button_click -> _send`` — не единственная.

    Родители строятся один раз на вызов: обход дерева целиком дешевле,
    чем обход в ширину по поддеревьям всех функций.
    """
    parent_of = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_of[id(child)] = node

    current = parent_of.get(id(target))
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parent_of.get(id(current))
    return None


def _keywords(call: ast.Call) -> dict[str, ast.AST]:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


def _constants(node: ast.AST) -> list[str]:
    return [
        part.value
        for part in ast.walk(node)
        if isinstance(part, ast.Constant) and isinstance(part.value, str)
    ]


def _dotted(node: ast.AST) -> str:
    """``self._host`` -> ``'self._host'``. Не выражение — пустая строка."""
    chain = _attribute_chain(node)
    return ".".join(chain) if chain else ""


def _all_calls(name: str) -> list[tuple[str, int]]:
    """Вызовы ``feedback.<name>`` по всему дереву: путь и строка."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        for line, _ in _calls(ast.parse(path.read_text(encoding="utf-8")), name):
            found.append((rel, line))
    return found


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    """Карта ``id() -> родитель`` для всего дерева."""
    parent_of: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_of[id(child)] = node
    return parent_of


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Функция с данным именем — в любом месте дерева.

    Обход по всему дереву, потому что проверяемые функции вложенные:
    ``_run_wizard`` лежит внутри ``main``, а ``_bar_host`` — внутри класса.
    """
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    return None


def _is_runtime_suppressed(parent_of: dict[int, ast.AST], node: ast.AST) -> bool:
    """Обёрнут ли узел в ``contextlib.suppress(RuntimeError)``.

    Подъём по всем ``With`` выше узла, а не только по ближайшему: подавление
    может лежать на уровень выше ``try``/``except`` или ``if``, и проверка
    одного уровня такой откат пропустила бы.
    """
    current = parent_of.get(id(node))
    while current is not None:
        if isinstance(current, ast.With):
            for item in current.items:
                expr = item.context_expr
                if (
                    isinstance(expr, ast.Call)
                    and isinstance(expr.func, ast.Attribute)
                    and expr.func.attr == "suppress"
                    and _attribute_chain(expr.func)[0] == "contextlib"
                    and any(
                        isinstance(arg, ast.Name) and arg.id == "RuntimeError"
                        for arg in expr.args
                    )
                ):
                    return True
        current = parent_of.get(id(current))
    return False


# ── старые пути убраны ─────────────────────────────────────────────


@pytest.mark.parametrize("rel", sorted(EXPECTED))
def test_no_old_feedback_entry_point_left(rel):
    """Ни импорта, ни обращения к Qt-обратной связи.

    Имена проверяются на всём дереве файла, а не только среди вызовов:
    возвратившийся обход приходит импортом или как ``InfoBar.new(``, и по
    узлам ``ast.Call`` без цепочки атрибутов не виден.
    """
    tree = _tree(rel)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            hit = sorted({alias.name for alias in node.names} & set(BANNED))
            if hit:
                offenders.append(f"{rel}:{node.lineno} from-import {hit}")
        elif isinstance(node, ast.Name) and node.id in BANNED:
            offenders.append(f"{rel}:{node.lineno} имя {node.id}")
        elif isinstance(node, ast.Attribute):
            hit = sorted(set(_attribute_chain(node)) & set(BANNED))
            if hit:
                offenders.append(f"{rel}:{node.lineno} {hit}")
    assert not offenders, f"обратная связь идёт через feedback: {offenders}"


# ── число мест вызова ──────────────────────────────────────────────


@pytest.mark.parametrize("rel", sorted(EXPECTED))
def test_exact_number_of_notify_calls(rel):
    """Каждый вызов на своём месте: молча удалённый не считается.

    Число, а не «больше нуля»: смена ``WARNING`` на ``INFO`` и пропажа
    ``title=`` число не трогают, зато удаление вызова — да.
    """
    calls = _calls(_tree(rel), "notify")
    where = ", ".join(str(line) for line, _ in calls)

    assert len(calls) == EXPECTED[rel][0], (
        f"{rel}: ожидалось {EXPECTED[rel][0]} вызовов feedback.notify, "
        f"найдено {len(calls)}: {where}"
    )


def test_exact_number_of_confirm_calls():
    """Решений пять: по одному в редакторе команд, логах и панели алиаса,
    два в подключении.

    Считается только этот набор: ``toolbar`` и ``status_bar`` переведены
    другими партиями и добавят сюда своих мест.
    """
    total = sum(
        len(_calls(_tree(rel), "confirm")) for rel in EXPECTED if rel != DB_VIEWER
    )
    assert total == EXPECTED_CONFIRM, (
        f"ожидалось {EXPECTED_CONFIRM} вызовов feedback.confirm, найдено {total}"
    )


def test_confirm_count_with_previous_batch():
    """Шесть решений вместе с уже перенесённым — число из брифа.

    Отдельно от предыдущей проверки: так видно, что расхождение было в
    арифметике брифа, а не в пропавшем вызове.
    """
    total = sum(len(_calls(_tree(rel), "confirm")) for rel in EXPECTED)
    db_viewer = len(_calls(_tree(DB_VIEWER), "confirm"))

    assert total == EXPECTED_CONFIRM
    assert db_viewer == 1, f"{DB_VIEWER}: найдено решений {db_viewer}"
    assert total + db_viewer == EXPECTED_CONFIRM_WITH_DB_VIEWER


# ── окно и уровень ─────────────────────────────────────────────────


@pytest.mark.parametrize("rel", sorted(EXPECTED))
def test_every_notify_names_its_window(rel):
    """Без ``parent=`` всплывашка встаёт в угол экрана, а не у окна."""
    offenders = []
    for line, call in _calls(_tree(rel), "notify"):
        if "parent" not in _keywords(call):
            offenders.append(f"notify:{line}")

    assert not offenders, f"без parent= полоса уезжает на экран: {offenders}"


def test_cashscp_names_its_own_window():
    """Вкладка CashSCP полосу крепит к своему окну, а не к панели.

    У вкладки ``self`` — это панель внутри окна CashSCP, а не окно, и
    вспышка встала бы над главным окном приложения. Ошибка тихая: полоса
    появляется, только не там, где пользователь смотрит.

    Само окно ``window.py`` в этой проверке не участвует: строка состояния
    в нём осталась на статус-баре, и вызовов ``notify`` у файла нет. Ноль
    закреплён в ``test_exact_number_of_notify_calls``.
    """
    session = _tree("builtin/file_manager/gui/session.py")
    wrong = [
        line
        for line, call in _calls(session, "notify")
        if _dotted(_keywords(call)["parent"]) != "self._host"
    ]
    assert not wrong, f"полоса CashSCP уедет на главное окно: строки {wrong}"



@pytest.mark.parametrize("rel", sorted(EXPECTED))
def test_every_notify_passes_an_explicit_level(rel):
    """Уровень задаётся членом ``Level``, а не строкой.

    Строки принимает ``normalize_level``, и опечатка ``"erorr"`` молча
    показалась бы как info: с неверным цветом и без следа в журнале.
    """
    offenders = []
    for line, call in _calls(_tree(rel), "notify"):
        level = call.args[1] if len(call.args) > 1 else _keywords(call).get("level")
        if not (isinstance(level, ast.Attribute) and isinstance(level.value, ast.Name)):
            offenders.append(f"notify:{line}")
        elif level.value.id != "Level":
            offenders.append(f"notify:{line} -> {level.value.id}")

    assert not offenders, f"уровень задан членом Level: {offenders}"


def test_titles_kept_from_old_dialogs():
    """Заголовок старого окна не потерян.

    Собираются все ``title=`` переведённых файлов: проверяется множество, а
    не позиции, потому что строки меняются от правки к правке, а смысл —
    нет.
    """
    titles = set()
    for rel in EXPECTED:
        for _, call in _calls(_tree(rel), "notify"):
            title = _keywords(call).get("title")
            if title is not None:
                titles.update(_constants(title))

    missing = sorted(EXPECTED_TITLES - titles)
    assert not missing, f"потеряны заголовки старых окон: {missing}"


# ── решения ────────────────────────────────────────────────────────


def test_confirm_never_inside_a_coroutine():
    """``exec()`` внутри задачи роняет вложенный Qt-цикл.

    След известен в ``builtin/terminal/ui/main_window.py:387-390``. Проверка
    по всему дереву, а не по набору: корутина появиться может и в следующей
    партии, а ловить это должен один тест.
    """
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, call in _calls(tree, "confirm"):
            owner = _enclosing(tree, call)
            if isinstance(owner, ast.AsyncFunctionDef):
                offenders.append(f"{rel}:{owner.name}:{line}")

    assert not offenders, f"confirm только из слота Qt, не из корутины: {offenders}"
    # Пустой список владельцев — не повод пропустить проверку: если разбор
    # перестанет находить вызовы, счётчик сойдётся с нулём.
    # Одиннадцать: девять прежних мест плюс подтверждение записи на кассе у
    # проблемы и удаления закладки. Первое вызывается из Qt-слота
    # _confirm_fix, куда
    # возвращается через QTimer.singleShot, — именно поэтому проверка выше
    # и ловит вызов confirm внутри корутины.
    assert len(_all_calls("confirm")) == 11, (
        f"ожидалось 11 перенесённых решений в дереве, "
        f"найдено {len(_all_calls('confirm'))}"
    )


# Корутина, спрятанная внутрь обычной функции: именно такой случай старый
# обход в ширину пропускал, отдавая внешнюю функцию.
_NESTED_COROUTINE = """
def outer():
    async def inner():
        from cashcontrol.gui import feedback

        feedback.confirm("Удалить", "Точно?", parent=None)
"""


def test_enclosing_finds_the_nearest_function():
    """Владелец узла — ближайшая функция, а не внешняя.

    Синтетическое дерево, а не разбор файла: нужен случай, которого в
    проекте сейчас нет, но который повторится, как только под ``confirm``
    появится своя coroutine-обёртка. Второе утверждение держит эталонный
    обход в ширину: если он перестанет проскакивать, первая проверка
    перестанет что-то доказывать.
    """
    tree = ast.parse(_NESTED_COROUTINE)
    call = _calls(tree, "confirm")[0][1]

    owner = _enclosing(tree, call)
    assert isinstance(owner, ast.AsyncFunctionDef) and owner.name == "inner", (
        f"вложенная корутина спряталась за внешней функцией: {owner}"
    )

    def _breadth_first(tree: ast.Module, target: ast.AST) -> ast.AST | None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                child is target for child in ast.walk(node)
            ):
                return node
        return None

    stale = _breadth_first(tree, call)
    assert isinstance(stale, ast.FunctionDef) and stale.name == "outer", (
        f"эталонный обход в ширину изменился: {stale}"
    )


# ── мастер настройки: предупреждения уходят наружу ───────────────────


def test_wizard_hands_its_warnings_to_the_main_window():
    """Показывается то, что мастер накопил, а не что-то другое.

    Числа вызовов в обоих файлах закреплены выше, но сами по себе они
    файлы не связывают: ``notify`` в ``main.py`` можно оставить, а
    ``take_warnings`` не вызвать, и оба числа останутся верными. Здесь
    проверяется связь: текст уведомления — имя, которому присвоен
    результат ``wizard.take_warnings()``.
    """
    tree = _tree("main.py")
    calls = _calls(tree, "notify")
    assert len(calls) == 1, f"ожидался один вызов notify, найдено {len(calls)}"

    message = calls[0][1].args[0]
    assert isinstance(message, ast.Name), (
        f"показывается не результат take_warnings, а {ast.dump(message)}"
    )
    assigned = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == message.id
            for target in node.targets
        )
    ]
    assert len(assigned) == 1, f"имя {message.id} не присваивается ровно один раз"

    value = assigned[0].value
    assert (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "take_warnings"
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "wizard"
    ), f"{message.id} присваивается не из мастера: {ast.dump(value)}"


def test_wizard_gives_its_warnings_away_once():
    """Список очищается: повторный показ был бы второй полосой того же.

    Метод зовётся на живом экземпляре мастера, который строит пять страниц
    и читает настройки, поэтому проверяется сам метод на подставном
    объекте: контракт тут один — отдаёт текст и забывает его.
    """
    import types

    from cashcontrol.gui.dialogs.setup_wizard.wizard import CashControlSetupWizard

    stub = types.SimpleNamespace(
        _pending_warnings=["SSH-пароли не расшифровались и были оставлены без изменений"]
    )

    text = CashControlSetupWizard.take_warnings(stub)
    assert "SSH-пароли не расшифровались" in text, f"текст собран неверно: {text!r}"
    assert "не удалось расшифровать" in text, f"потеряно объяснение: {text!r}"
    assert CashControlSetupWizard.take_warnings(stub) == "", "предупреждение отдано дважды"

    empty = types.SimpleNamespace(_pending_warnings=[])
    assert CashControlSetupWizard.take_warnings(empty) == "", (
        "без накопленных предупреждений показывать нечего"
    )


def test_wizard_clears_its_pending_list_unconditionally():
    """``_pending_warnings`` присваивается вне ``if warnings:``.

    Сейчас путь без предупреждений недостижим — мастер запускается один раз,
    — и потому это косметика. Но состояние не должно зависеть от того, попал
    ли список в ветку: возврат ``if warnings:`` оставил бы после повторного
    ``_on_finished`` старый список, и ``take_warnings`` отдал бы то, чего
    уже нет.
    """
    tree = _tree("gui/dialogs/setup_wizard/wizard.py")
    finished = _function(tree, "_on_finished")
    assert finished is not None, "_on_finished не найден"

    parent_of = _parents(finished)
    assigned = [
        node
        for node in ast.walk(finished)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute) and target.attr == "_pending_warnings"
            for target in node.targets
        )
    ]
    assert assigned, "_pending_warnings в _on_finished не присваивается"

    guarded = [
        node.lineno for node in assigned if _enclosing_guard(parent_of, node)
    ]
    assert not guarded, (
        f"присваивание под условием, строки {guarded}: старый список "
        "предупреждений переживёт повторный _on_finished"
    )


def _enclosing_guard(parent_of: dict[int, ast.AST], node: ast.AST) -> bool:
    """Лежит ли узел под веткой ``if``/``match`` внутри функции.

    ``try`` в список веток не входит намеренно: присваивание под ``try``
    выполняется всегда, в отличие от присваивания под ``if``. Подъём
    останавливается на границе функции — ``_on_finished`` сам лежит под
    ``try``, и без остановки любой узел в нём считался бы условным.
    """
    current = parent_of.get(id(node))
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        if isinstance(current, (ast.If, ast.Match)):
            return True
        current = parent_of.get(id(current))
    return False


@pytest.mark.parametrize(
    ("rel", "count"),
    [
        ("gui/dialogs/command_editor.py", 1),
        ("gui/dialogs/settings/tab_connection.py", 2),
        ("gui/dialogs/settings/tab_logs.py", 1),
    ],
)
def test_destructive_answers_keep_the_delete_label(rel, count):
    """Надпись «Удалить» задаёт ``destructive``, а не подмена кнопки.

    Без него кнопка обещает «Выполнить», и действие в окне не совпадает с
    тем, что на ней написано.
    """
    calls = _calls(_tree(rel), "confirm")
    assert len(calls) == count, f"{rel}: найдено решений {len(calls)} вместо {count}"

    for line, call in calls:
        keywords = _keywords(call)
        assert isinstance(keywords.get("destructive"), ast.Constant), (
            f"{rel}:{line} без destructive= кнопка обещает «Выполнить»"
        )
        assert keywords["destructive"].value is True


def test_alias_reset_keeps_its_own_label():
    """Сброс алиаса не удаление: надпись «Сбросить» задаётся ``yes_text``.

    ``destructive`` дал бы «Удалить» — обещание действия, которого в окне
    нет.
    """
    calls = _calls(_tree("gui/widgets/info_section_widget.py"), "confirm")
    assert len(calls) == 1

    keywords = _keywords(calls[0][1])
    assert "destructive" not in keywords, (
        "сброс алиаса не удаление, destructive= дал бы надпись «Удалить»"
    )
    assert _constants(keywords["yes_text"]) == ["Сбросить"]


# ── вкладка кассы: подавление RuntimeError на выгрузке ──────────────
#
# Пять полос в ``_upload_to_cash`` обёрнуты в
# ``contextlib.suppress(RuntimeError)``. Причина одна: ``spawn`` это
# ``asyncio.ensure_future``, то есть задача живёт в GUI-потоке, поэтому
# доставка полосы синхронная; ``tab_manager.close_tab`` снимает виджет через
# ``deleteLater()``, корутина продолжает жить, и последний ``await`` попадает
# на удалённый C++-объект.
#
# Проверка нужна потому, что снятие подавления не меняет ни одного числа:
# вызов ``notify`` остаётся на месте, и все прежние сторожи остаются зелёными.


def test_upload_notifies_are_wrapped_in_runtime_suppression():
    """Каждое из пяти уведомлений при выгрузке переживает удалённую вкладку."""
    tree = _tree("gui/cash_session_widget.py")
    upload = _function(tree, UPLOAD_FUNC)
    assert upload is not None, f"{UPLOAD_FUNC} не найдена"

    calls = _calls(upload, "notify")
    assert len(calls) == EXPECTED_UPLOAD_NOTIFY, (
        f"{UPLOAD_FUNC}: ожидалось {EXPECTED_UPLOAD_NOTIFY} вызовов notify, "
        f"найдено {len(calls)}"
    )

    parent_of = _parents(upload)
    naked = [
        line for line, call in calls if not _is_runtime_suppressed(parent_of, call)
    ]
    assert not naked, (
        f"{UPLOAD_FUNC}: уведомления без suppress(RuntimeError) — {naked}. "
        "Без подавления закрытие вкладки во время выгрузки роняет корутину"
    )


def test_upload_suppression_survives_a_synthetic_removal():
    """Сторож видит снятое подавление на синтетическом дереве.

    Эталон к предыдущей проверке: если она перестанет отличать обёрнутое от
    голого, первая станет зелёной на любом откате, и никто этого не увидит.
    """
    tree = ast.parse(
        "async def _upload_to_cash():\n"
        "    from cashcontrol.gui import feedback\n"
        "    feedback.notify('a', None, parent=self)\n"
        "    with contextlib.suppress(RuntimeError):\n"
        "        feedback.notify('b', None, parent=self)\n"
    )
    upload = _function(tree, UPLOAD_FUNC)
    assert upload is not None
    parent_of = _parents(upload)

    wrapped = [
        line
        for line, call in _calls(upload, "notify")
        if _is_runtime_suppressed(parent_of, call)
    ]
    assert wrapped == [5], (
        f"сторож отметил не те вызовы: {wrapped} — должен быть только "
        "обёрнутый, четвёртый снос"
    )


# ── клавиатура: у какой полосы есть переживающее её окно ─────────────
#
# ``_save`` зовётся из двух мест: кнопка «Сохранить» и ``closeEvent``.
# Полосу показывать не у редактора, если он сейчас закрывается: она умирает
# вместе с ним, не показавшись ни одного кадра. Старое ``QMessageBox.critical``
# было модальным и требовало подтверждения, то есть несохранённая раскладка
# не могла проскочить молча.


def test_bar_host_follows_the_closing_flag():
    """По кнопке — редактор, при закрытии — родитель, и обе ветки закреплены."""
    import types

    from cashcontrol.gui.widgets.virtual_keyboard import KeyboardEditorWindow

    sentinel = object()
    stub = types.SimpleNamespace(parent=lambda: sentinel)

    assert KeyboardEditorWindow._bar_host(stub, False) is stub, (
        "по кнопке полоса должна быть у редактора, а не у главного окна"
    )
    assert KeyboardEditorWindow._bar_host(stub, True) is sentinel, (
        "при закрытии полоса должна уйти родителю, который переживёт редактор"
    )


def test_close_event_saves_layout_as_closing():
    """``closeEvent`` зовёт ``_save(closing=True)``.

    Разбор дерева, а не вызов метода: откат ``closing=True`` на ``parent=self``
    не меняет ни одного числа вызовов, и проверка поведением его бы пропустила,
    а этот откат и есть Critical, который закрывали в прошлом круге.
    """
    tree = _tree("gui/widgets/virtual_keyboard.py")
    close = _function(tree, "closeEvent")
    assert close is not None, "closeEvent не найден"

    saves = [
        node
        for node in ast.walk(close)
        if isinstance(node, ast.Call) and _attribute_chain(node.func)[-1:] == ["_save"]
    ]
    assert len(saves) == 1, f"closeEvent должен звать _save ровно один раз, нашёл {len(saves)}"

    keywords = _keywords(saves[0])
    assert "closing" in keywords, (
        "closeEvent зовёт _save без closing: полоса уйдёт редактору, "
        "который вот-вот закроется"
    )
    assert isinstance(keywords["closing"], ast.Constant) and keywords["closing"].value is True


# ── main.py: окно раньше предупреждений ─────────────────────────────
#
# ``take_warnings()`` зовётся после ``_show_main_window()``, и это не
# оформление кода: полоса с ``parent=None`` уходит только в журнал, то есть
# пользователь не увидит предупреждения мастера, ради которого всё затевалось.


def test_wizard_warnings_are_taken_after_the_window_is_shown():
    """``take_warnings`` вызывается после ``_show_main_window``.

    Номера строк, а не текст: перестановка двух строк не меняет ни имён, ни
    числа вызовов, и проверка по содержимому прошла бы.
    """
    tree = _tree("main.py")
    runner = _function(tree, "_run_wizard")
    assert runner is not None, "_run_wizard не найдена"

    shown = [
        node.lineno
        for node in ast.walk(runner)
        if isinstance(node, ast.Call)
        and _attribute_chain(node.func)[-1:] == ["_show_main_window"]
    ]
    taken = [
        node.lineno
        for node in ast.walk(runner)
        if isinstance(node, ast.Call)
        and _attribute_chain(node.func)[-1:] == ["take_warnings"]
    ]
    assert shown, "_show_main_window не зовётся в _run_wizard"
    assert taken, "take_warnings не зовётся в _run_wizard"

    assert taken[0] > shown[0], (
        f"take_warnings на строке {taken[0]}, а окно показывается на "
        f"{shown[0]}: parent=None уедет в журнал, и предупреждение мастера "
        "пользователь не увидит"
    )
