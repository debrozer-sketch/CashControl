"""Обратная связь встроенного просмотрщика базы: контракт и поведение.

Сторож в ``test_feedback_guards.py`` после правки пакета перестаёт быть
для него особенным случаем: пять файлов db_viewer выходят из ``PENDING``
и попадают под общие запреты. Список ``PENDING`` снят целиком, и проверять
форму здесь больше не о чем — она одна и та же для всех. Здесь проверяется
содержание пакета: сколько вызовов, у всех ли есть окно, как проверяется
ответ на удаление и что попадает в журнал при отказе и при ошибке в
рабочем потоке.

Разбор дерева, а не подстрока: подстрока поймала бы и определение, и
комментарий, и вызов, завёрнутый в лямбду, но не поймала бы забытый
``parent=`` или ``confirm`` внутри корутины.
"""

from __future__ import annotations

import ast
import importlib.util
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from cashcontrol.gui import feedback
from cashcontrol.gui.notification_manager import Level

SRC = Path(__file__).resolve().parent.parent / "src" / "cashcontrol"
PKG = SRC / "builtin" / "db_viewer"

# Пять файлов пакета. Числа вызовов взяты разбором дерева: бриф называл
# 20 мест вызова, по коду их 20 — 19 вызовов ``_toast`` и один
# ``QMessageBox.question``.
FILES = ("storage.py", "data_panel.py", "sql_console.py", "widget.py", "tables_panel.py")
EXPECTED_NOTIFY = 19
# Два решения во всём пакете: удаление строк таблицы в data_panel.py и
# удаление закладки в sql_console.py. Второе появилось при разборе
# аудита: кнопка «Удалить» в окне закладок работала сразу, без вопроса.
EXPECTED_CONFIRM = 2

# Имена, которых в пакете быть не должно. ``InfoBarPosition`` — часть
# того же обхода, что и ``InfoBar``, а ``QMessageBox`` принесён из Qt
# мимо общего API.
BANNED = ("InfoBar", "InfoBarPosition", "MessageBox", "QMessageBox")


# ── контракт по исходному коду ─────────────────────────────────────────


def _tree(name: str) -> ast.Module:
    return ast.parse((PKG / name).read_text(encoding="utf-8"))


def _trees() -> dict[str, ast.Module]:
    return {name: _tree(name) for name in FILES}


def _calls(tree: ast.Module, name: str) -> list[tuple[int, ast.Call]]:
    """Вызовы ``feedback.<name>(...)`` с номером строки.

    Дерево передаётся аргументом, а не разбирается здесь: поиск владельца
    узла идёт по идентичности, а два разбора дают два разных дерева.
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


def _enclosing(tree: ast.Module, target: ast.AST) -> ast.AST | None:
    """Внешняя функция, внутри которой лежит узел."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            child is target for child in ast.walk(node)
        ):
            return node
    return None


def _sum(fn) -> int:
    return sum(len(fn(tree)) for tree in _trees().values())


def test_no_private_toast_helper_left():
    """Ни определения, ни вызова, ни импорта ``_toast``.

    Проверяется имя, а не вызов с тремя аргументами: у мёртвого вызова
    нашлись бы и определение, и импорт в четырёх файлах, а проверка по
    подстроке «_toast(» пропустила бы голый импорт.
    """
    offenders = []
    for name, tree in _trees().items():
        for node in ast.walk(tree):
            plain = isinstance(node, ast.Name) and node.id == "_toast"
            attribute = isinstance(node, ast.Attribute) and node.attr == "_toast"
            if plain or attribute:
                offenders.append(f"{name}:{node.lineno}")
    assert not offenders, f"свой обход InfoBar удалён, а его следы остались: {offenders}"


def test_no_qt_feedback_widgets_anywhere_in_the_package():
    """Ни импорта, ни обращения к Qt-обратной связи.

    Ловится и ``getattr(InfoBar, kind)``, и ``QMessageBox.Yes`` в
    сравнении: прежние сторожевые проверки видели только вызов
    ``InfoBar.success(`` и пропускали оба.
    """
    offenders = []
    banned = set(BANNED)
    for name, tree in _trees().items():
        for node in ast.walk(tree):
            hit = None
            if isinstance(node, ast.Name) and node.id in banned:
                hit = f"имя {node.id}"
            elif isinstance(node, ast.Attribute) and node.attr in banned:
                hit = f"атрибут {node.attr}"
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                hit = sorted({alias.name for alias in node.names} & banned)
            if hit:
                offenders.append(f"{name}:{node.lineno} {hit}")
    assert not offenders, f"обратная связь живёт только в gui/feedback.py: {offenders}"


def test_exact_number_of_notify_calls():
    """Каждый вызов на своём месте: молча удалённый не считается.

    Число, а не «больше нуля»: смена ``Level.ERROR`` на ``Level.INFO`` и
    пропажа ``parent=`` число не трогают, зато удаление вызова — да.
    """
    calls = _sum(lambda tree: _calls(tree, "notify"))
    assert calls == EXPECTED_NOTIFY, (
        f"ожидалось {EXPECTED_NOTIFY} вызовов feedback.notify, найдено {calls}"
    )


def test_exact_number_of_confirm_calls():
    calls = _sum(lambda tree: _calls(tree, "confirm"))
    assert calls == EXPECTED_CONFIRM, (
        f"ожидалось {EXPECTED_CONFIRM} вызов feedback.confirm, найдено {calls}"
    )


def test_every_notify_call_names_its_window():
    """Без ``parent=`` всплывашка встаёт в угол экрана, а не у окна.

    Раньше виджет подставлялся первым позиционным аргументом, и потерять
    его можно было вместе с переносом: место вызова осталось, привязка
    исчезла.
    """
    offenders = []
    checked = 0
    for name, tree in _trees().items():
        for line, call in _calls(tree, "notify"):
            checked += 1
            if not any(kw.arg == "parent" for kw in call.keywords):
                offenders.append(f"{name}:{line}")
    assert not offenders, f"без parent= полоса уезжает на экран: {offenders}"
    # Счётчик обязан совпасть с контрактом: перестав разбирать вызовы,
    # проверка прошла бы вхолостую.
    assert checked == EXPECTED_NOTIFY, f"проверено {checked} вызовов"


def test_every_notify_call_passes_level_as_the_second_argument():
    """Второй позиционный аргумент — атрибут ``Level``, а не что попало.

    ``notify`` принимает сообщение первым и уровень вторым, а прежний
    ``_toast`` звал ``getattr(InfoBar, kind)``, где вид обратной связи
    шёл первым. Переставленные ``notify(Level.SUCCESS, 'текст', ...)``
    не падают: ``normalize_level`` получил бы объект ``Level`` вместо
    строки, записал бы предупреждение в журнал и показал всё как
    ``info``. Остальные проверки файла такой вызов пропускают: число
    вызовов, наличие ``parent=`` и даже уровень в журнале на месте
    остаются верными.

    Требуется именно ``ast.Attribute`` над именем ``Level``: строка,
    вызов и ``Level('error')`` означают, что уровень уехал на другое
    место, а проверить это больше нечем.
    """
    offenders = []
    checked = 0
    for name, tree in _trees().items():
        for line, call in _calls(tree, "notify"):
            checked += 1
            level = call.args[1] if len(call.args) > 1 else None
            if not (
                isinstance(level, ast.Attribute)
                and isinstance(level.value, ast.Name)
                and level.value.id == "Level"
            ):
                offenders.append(f"{name}:{line} {ast.unparse(call)}")
    assert not offenders, (
        f"уровень — второй позиционный аргумент, атрибут Level: {offenders}"
    )
    assert checked == EXPECTED_NOTIFY, f"проверено {checked} вызовов"


def test_confirm_never_inside_a_coroutine():
    """``exec()`` внутри задачи роняет вложенный Qt-цикл.

    След известен в ``builtin/terminal/ui/main_window.py:387-390``.
    """
    offenders = []
    for name, tree in _trees().items():
        for line, call in _calls(tree, "confirm"):
            owner = _enclosing(tree, call)
            if isinstance(owner, ast.AsyncFunctionDef):
                offenders.append(f"{name}:{owner.name}:{line}")
    assert offenders == [], f"confirm только из слота Qt, не из корутины: {offenders}"


def test_no_coroutine_mentions_confirm_at_all():
    """Запрет шире проверки вызова: заглянуть в тело и не найти имени.

    В пакете корутин нет вообще, и это не повод проверку выбросить:
    ``_Worker`` построен на QThread, и следующая партия может перевести
    обработчики на ``spawn``.
    """
    offenders = []
    for name, tree in _trees().items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Attribute)
                    and child.attr == "confirm"
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "feedback"
                ):
                    offenders.append(f"{name}:{node.name}:{child.lineno}")
    assert not offenders, f"корутина не зовёт confirm: {offenders}"


def test_delete_answer_is_tested_as_a_bool():
    """Ответ на удаление проверяется как ``bool``, а не сравнением с Qt.

    Прежний код сравнивал результат с ``QMessageBox.Yes``. Наивный перенос
    оставил бы сравнение с числом, и тогда окно отвечало бы «да», а
    удаление не происходило: ``bool(1) != 1024``.
    """
    tree = _tree("data_panel.py")
    offenders = []
    for line, call in _calls(tree, "confirm"):
        owner = _enclosing(tree, call)
        guard = next(
            (n for n in ast.walk(owner) if isinstance(n, ast.If) and call in ast.walk(n.test)),
            None,
        )
        if guard is None:
            offenders.append(f"вызов вне условия:{line}")
            continue
        if not (
            isinstance(guard.test, ast.UnaryOp)
            and isinstance(guard.test.op, ast.Not)
            and guard.test.operand is call
        ):
            offenders.append(f"ответ проверяется не как bool:{line}")
        if len(guard.body) != 1 or not isinstance(guard.body[0], ast.Return):
            offenders.append(f"отказ не выходит сразу:{line}")
    assert offenders == [], f"отказ от удаления должен быть ранним выходом: {offenders}"
    # Условие найдено один раз: пустой список проверял бы сам себя.
    # Здесь ровно один вызов в ЭТОМ файле. EXPECTED_CONFIRM считает по всему
    # пакету, и равенство с ним здесь было случайным совпадением: второе
    # место — удаление закладки в sql_console.py.
    assert len(_calls(tree, "confirm")) == 1, (
        f"в data_panel.py ожидался один вызов confirm, найдено "
        f"{len(_calls(tree, 'confirm'))}"
    )


def test_delete_confirmation_is_marked_destructive():
    """Надпись «Удалить» вместо «Выполнить» — только здесь.

    Окно спрашивает об удалении строк, и кнопка, обещающая выполнение,
    вводила бы в заблуждение.
    """
    calls = _calls(_tree("data_panel.py"), "confirm")
    flagged = [
        line
        for line, call in calls
        if any(kw.arg == "destructive" and ast.literal_eval(kw.value) for kw in call.keywords)
    ]
    assert flagged == [line for line, _ in calls], f"подтверждение удаления не помечено: {calls}"


def test_package_is_no_longer_pending_in_the_guard():
    """Ослабление снято в самом стороже, а не только по факту.

    Пять имён в ``PENDING`` были пятью файлами, выпавшими из-под запретов на
    ``_toast`` и Qt-обратную связь. Пока такой список есть, новый старый вызов
    в просмотрщике проходит молча, поэтому проверяется отсутствие списка, а
    не отсутствие в нём нужных имён: второе удовлетворяется и списком из
    одного чужого файла.
    """
    spec = importlib.util.spec_from_file_location(
        "_cashcontrol_feedback_guards", Path(__file__).with_name("test_feedback_guards.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert not hasattr(module, "PENDING"), "ослабление сторожа вернулось"

    guarded = {module._rel(p) for p in module._py_files()}
    left = sorted(f"builtin/db_viewer/{name}" for name in FILES if f"builtin/db_viewer/{name}" not in guarded)
    assert left == [], f"db_viewer всё ещё вне сторожа: {left}"


# ── поведение: журнал вместо всплывашки ────────────────────────────────


class _Factory:
    """Соединение не нужно: ни один тест не доходит до БД."""

    database = "postgres"


class _Signal:
    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, fn) -> None:
        self.slots.append(fn)

    def emit(self, *args) -> None:
        for slot in list(self.slots):
            slot(*args)


class _FakeWorker:
    """Воркер без потока: панель подписывается на слоты и запускает его."""

    def __init__(self, *args, **kwargs) -> None:
        self.done = _Signal()
        self.failed = _Signal()
        self.finished = _Signal()

    def start(self) -> None:
        pass

    def isRunning(self) -> bool:
        return False

    def cancel(self, *args, **kwargs) -> None:
        pass


@pytest.fixture
def journal(monkeypatch):
    """Журнал синглтона на время теста.

    Подменяется сам экземпляр: прежние тесты опустошали общий, и порядок
    прогона влиял на результат.
    """
    from cashcontrol.gui.notification_manager import (
        NotificationManager,
        get_notification_manager,
    )

    monkeypatch.setattr(NotificationManager, "_instance", NotificationManager())
    return get_notification_manager()


@pytest.fixture
def shown(monkeypatch):
    """Кем и с каким окном показана бы всплывашка.

    ``_show`` заглушен: проверяется журнал, а InfoBar без показанного
    окна только мешает. Сами аргументы сохраняются — по ним видно, к
    какому виджету привязалась бы полоса.
    """
    calls: list[tuple] = []
    monkeypatch.setattr(feedback, "_show", lambda *args: calls.append(args))
    return calls


def _records(journal, text: str):
    return [n for n in journal.get_all() if n.message == text]


def _messages(journal) -> list[str]:
    return [n.message for n in journal.get_all()]


def _assert_one(journal, text: str, level: Level, where: str) -> None:
    records = _records(journal, text)
    assert len(records) == 1, (
        f"{where}: ожидалась одна запись {text!r}, получено {len(records)}: {_messages(journal)}"
    )
    assert records[0].level is level, f"{where}: уровень {records[0].level}, ожидался {level}"


def _assert_anchored(shown, parent, where: str) -> None:
    assert shown, f"{where}: всплывашка не показана вовсе"
    assert shown[-1][3] is parent, f"{where}: полоса привязана не к тому окну"


@pytest.fixture
def console(qapp, monkeypatch, journal, shown):
    """Настоящая консоль: подмена обработчика проверяла бы подмену.

    Виджет держится на Python-объекте фикстуры: без этой ссылки сборщик
    уносит его вместе с окном, и следующий тест получает уже удалённый
    C++-объект.
    """
    from cashcontrol.builtin.db_viewer.sql_console import _SqlConsole

    monkeypatch.setattr(
        "cashcontrol.builtin.db_viewer.sql_console._Worker", _FakeWorker, raising=True
    )
    widget = _SqlConsole(_Factory())
    widget._test_self = widget
    return widget


@pytest.fixture
def panel(qapp, monkeypatch, journal, shown):
    """Панель открытой таблицы с одной загруженной страницей."""
    from cashcontrol.builtin.db_viewer.data_panel import _DataPanel

    monkeypatch.setattr(
        "cashcontrol.builtin.db_viewer.data_panel._Worker", _FakeWorker, raising=True
    )
    widget = _DataPanel(_Factory(), "postgres", "public", "orders")
    widget._meta = {
        "columns": [{"name": "id", "type": "int4"}, {"name": "note", "type": "text"}],
        "pk": ["id"],
    }
    widget._grid.set_model(widget._meta["columns"], widget._meta["pk"],
                           [[1, "первая"], [2, "вторая"]])
    widget._test_self = widget
    return widget


def test_export_without_result_warns_once(console, journal, shown):
    console._export("csv")

    _assert_one(journal, "Нет результата для экспорта", Level.WARNING, "_export")
    _assert_anchored(shown, console, "_export")


def test_copy_result_reports_success(console, journal, shown):
    console._result_rows = [(1, "первая")]
    console._result_columns = [{"name": "id", "type": ""}, {"name": "note", "type": ""}]

    console._copy_result()

    _assert_one(journal, "Результат скопирован в буфер", Level.SUCCESS, "_copy_result")
    _assert_anchored(shown, console, "_copy_result")


def test_filter_error_warns_and_keeps_the_page(panel, monkeypatch, journal, shown):
    """Ошибка разбора фильтра не перезапрашивает страницу.

    Проверяется и уровень, и то, что ``return`` после сообщения остался
    на месте: без него панель уходила бы в БД с заведомо негодным
    условием и второй раз показывала ту же ошибку.
    """
    reloaded = []
    monkeypatch.setattr(panel, "reload", lambda: reloaded.append(True))
    panel._filter_edit.setText("нет_такой = 1")

    panel.apply_filter()

    _assert_one(
        journal,
        "Некорректный фильтр: «нет_такой = 1»",
        Level.WARNING,
        "apply_filter",
    )
    _assert_anchored(shown, panel, "apply_filter")
    assert reloaded == [], f"страница перезапрошена с негодным фильтром: {reloaded}"


def test_delete_without_selection_asks_for_rows(panel, monkeypatch, journal, shown):
    asked = []
    monkeypatch.setattr(feedback, "confirm", lambda *a, **kw: asked.append(kw) or False)

    panel.delete_selected()

    _assert_one(journal, "Выберите строки для удаления", Level.WARNING, "delete_selected")
    _assert_anchored(shown, panel, "delete_selected")
    assert asked == [], f"окно спрашивало об удалении без выбора строк: {asked}"


def test_delete_refused_keeps_rows(panel, monkeypatch, journal, shown):
    """Отказ от подтверждения ничего не удаляет.

    Смысл проверки — в форме ответа. ``QMessageBox.question`` возвращал
    число, ``confirm`` — ``bool``; отказ обязан быть ``not confirm(...)``,
    иначе отказ и согласие меняются местами.
    """
    asked = []
    writes = []
    monkeypatch.setattr(feedback, "confirm", lambda *a, **kw: asked.append(kw) or False)
    monkeypatch.setattr(panel, "_run_write", lambda kind, payload: writes.append((kind, payload)))
    panel._grid.selectAll()

    panel.delete_selected()

    assert asked, "подтверждение удаления не показано"
    assert writes == [], f"строки удалены без согласия: {writes}"
    assert _messages(journal) == [], f"отказ попал в журнал как событие: {_messages(journal)}"


def test_delete_confirmed_sends_the_key_rows(panel, monkeypatch, journal, shown):
    """Согласие удаляет выбранные строки по первичному ключу.

    Текст окна собирается из числа строк и имени таблицы: оператор должен
    видеть, что именно исчезнет, а не абстрактное «Удалить запись».
    """
    asked: list[tuple] = []
    writes: list[tuple] = []

    def fake_confirm(*args, **kwargs):
        asked.append((args, kwargs))
        return True

    monkeypatch.setattr(feedback, "confirm", fake_confirm)
    monkeypatch.setattr(panel, "_run_write", lambda kind, payload: writes.append((kind, payload)))
    panel._grid.selectAll()

    panel.delete_selected()

    assert writes == [("delete", [[1], [2]])], f"в БД ушло не то: {writes}"
    (args, kwargs) = asked[0]
    assert args[0] == "Удаление", f"заголовок окна потерян: {args[0]!r}"
    assert '"public"."orders"' in args[1], f"в окне нет имени таблицы: {args[1]!r}"
    assert "2 строк(и)" in args[1], f"в окне нет числа строк: {args[1]!r}"
    assert kwargs["parent"] is panel, "окно привязано не к панели"
    assert kwargs["destructive"] is True, "кнопка подтверждения не «Удалить»"


def test_worker_failure_is_recorded_from_its_own_thread(qapp, monkeypatch, journal, shown):
    """Ошибка воркера попадает в журнал из его потока.

    Слот ``failed`` подключён обычной лямбдой, и вызывается он из
    ``_Worker.run`` — то есть из чужого потока. ``notify`` пишет в журнал
    до показа полосы, поэтому запись не зависит от того, от какого потока
    пришёл вызов.
    """
    from cashcontrol.builtin.db_viewer.tables_panel import _TablesPanel

    monkeypatch.setattr(
        "cashcontrol.builtin.db_viewer.tables_panel._Worker", _FakeWorker, raising=True
    )
    panel = _TablesPanel(_Factory())
    panel._test_self = panel
    panel._load_tables()
    worker = panel._worker

    assert worker.failed.slots, "панель не подписалась на ошибку воркера"
    thread = threading.Thread(target=lambda: worker.failed.emit("нет связи"))
    thread.start()
    thread.join(10)

    assert not thread.is_alive(), "слот ошибки не отработал"
    _assert_one(journal, "нет связи", Level.ERROR, "tables_panel.failed")
    _assert_anchored(shown, panel, "tables_panel.failed")
