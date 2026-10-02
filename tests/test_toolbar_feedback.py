"""Обратная связь тулбара: контракт и поведение при отказе.

Сторож в ``test_feedback_guards.py`` ловит форму — запрещённые импорты,
``TOP_SCREEN``, литералы ``duration``. Форма проходит и при удалённом
вызове, и при смене уровня, и при потерянном ``parent=``. Здесь проверяется
содержание: сколько вызовов, у всех ли есть окно, где стоят подтверждения
и что попадает в журнал, когда активной вкладки нет.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from cashcontrol.gui import feedback
from cashcontrol.gui.notification_manager import Level

SRC = Path(__file__).resolve().parent.parent / "src" / "cashcontrol"
TOOLBAR = SRC / "gui" / "toolbar.py"

# Девять мест отказывают через хелпер, плюс сам хелпер с его вызовом
# notify. Числа взяты разбором дерева, а не пересказом брифа: бриф
# предыдущей задачи называл 32 места, по коду их было 35.
EXPECTED_NOTIFY = 26
EXPECTED_CONFIRM = 2
HELPER_TEXT = "Нет активной вкладки: откройте вкладку с кассой"


# ── контракт по исходному коду ───────────────────────────────────


def _tree() -> ast.Module:
    return ast.parse(TOOLBAR.read_text(encoding="utf-8"))


def _calls(tree: ast.Module, name: str) -> list[tuple[int, ast.Call]]:
    """Вызовы ``feedback.<name>(...)`` с номером строки.

    Разбор дерева, а не поиск подстроки: подстрока поймала бы и
    определение, и комментарий, и вызов через локальный импорт. Дерево
    передаётся аргументом, а не разбирается здесь: поиск владельца узла
    идёт по идентичности, а два разбора дают два разных дерева.
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
    """Внешняя функция, внутри которой лежит узел.

    Обход в ширину, не в глубину: у ``_on_commands_clicked`` внутри
    ``CashToolbar``, и поиск должен вернуть именно метод, а не класс.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            child is target for child in ast.walk(node)
        ):
            return node
    return None


def test_exact_number_of_notify_calls():
    """Каждый вызов на своём месте: молча удалённый не считается.

    Число, а не «больше нуля»: смена ``WARNING`` на ``INFO`` и пропажа
    ``title=`` число не трогают, зато удаление вызова — да.
    """
    calls = _calls(_tree(), "notify")
    where = ", ".join(str(line) for line, _ in calls)

    assert len(calls) == EXPECTED_NOTIFY, (
        f"ожидалось {EXPECTED_NOTIFY} вызовов feedback.notify, "
        f"найдено {len(calls)}: {where}"
    )


def test_exact_number_of_confirm_calls():
    calls = _calls(_tree(), "confirm")
    where = ", ".join(str(line) for line, _ in calls)

    assert len(calls) == EXPECTED_CONFIRM, (
        f"ожидалось {EXPECTED_CONFIRM} вызова feedback.confirm, "
        f"найдено {len(calls)}: {where}"
    )


def test_every_call_names_its_window():
    """Без ``parent=`` всплывашка встаёт в угол экрана, а не у окна.

    Вспомогательный хелпер проверяется отдельно: у него вызов один, и
    потеря ``parent=`` в нём точно так же ломает привязку.
    """
    offenders = []
    tree = _tree()
    checked = 0
    for name in ("notify", "confirm"):
        for line, call in _calls(tree, name):
            checked += 1
            if not any(kw.arg == "parent" for kw in call.keywords):
                offenders.append(f"{name}:{line}")

    assert not offenders, f"без parent= полоса уезжает на экран: {offenders}"
    # Число проверенных вызовов обязано совпасть с контрактом: разбор
    # перестал бы находить вызовы, проверка прошла бы вхолостую.
    assert checked == EXPECTED_NOTIFY + EXPECTED_CONFIRM, (
        f"проверено {checked} вызовов вместо "
        f"{EXPECTED_NOTIFY + EXPECTED_CONFIRM}"
    )


def test_confirm_never_inside_a_coroutine():
    """``exec()`` внутри задачи роняет вложенный Qt-цикл.

    След известен в ``builtin/terminal/ui/main_window.py:387-390``.
    """
    tree = _tree()
    offenders = []
    for line, call in _calls(tree, "confirm"):
        owner = _enclosing(tree, call)
        if isinstance(owner, ast.AsyncFunctionDef):
            offenders.append(f"{owner.name}:{line}")

    assert offenders == [], f"confirm только из слота Qt, не из корутины: {offenders}"
    # Пустой список владельцев — не повод пропустить проверку: если
    # разбор перестанет находить вызовы, счётчик сойдётся с нулём.
    assert len(_calls(tree, "confirm")) == EXPECTED_CONFIRM


def test_no_coroutine_mentions_confirm_at_all():
    """Запрет шире проверки вызова: заглянуть в тело и не найти имени."""
    tree = _tree()
    offenders = []
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
                offenders.append(f"{node.name}:{child.lineno}")

    assert not offenders, f"корутина не зовёт confirm: {offenders}"


def test_reboot_confirmation_warns_about_consequences():
    """Оператор видит, что произойдёт, а не только что нажата кнопка.

    Второе предложение исходного диалога потерялось при переносе текста
    из брифа дословно. Текст собирается из кусков f-строки: ip подставляется
    в первое предложение, второе остаётся константой.
    """
    texts = []
    for _, call in _calls(_tree(), "confirm"):
        if len(call.args) < 2:
            continue
        node = call.args[1]
        chunks = [
            part.value
            for part in ast.walk(node)
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ]
        texts.append("".join(chunks))
    reboot = [t for t in texts if t.startswith("Перезагрузить кассу")]

    assert reboot, f"нет подтверждения перезагрузки среди confirm: {texts}"
    assert "Система будет перезагружена." in reboot[0], (
        f"потеряно предупреждение о последствиях: {reboot[0]!r}"
    )


# ── поведение при отказе ─────────────────────────────────────────


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
def toolbar(qapp, monkeypatch, journal):
    """Тулбар без единой вкладки.

    Конструируется настоящий виджет: подмена `_require_active_tab`
    проверяла бы саму подмену, а не путь отказа обработчика.
    """
    from PySide6.QtWidgets import QWidget

    from cashcontrol.gui.toolbar import CashToolbar

    class _EmptySessionManager:
        active_ip = None

        def get_session(self, ip):
            return None

    class _EmptyTabManager:
        def get_active_session(self):
            return None

    window = QWidget()
    window._tab_manager = _EmptyTabManager()
    toolbar = CashToolbar(_EmptySessionManager(), parent=window)
    # Окно держится только на Python-объекте: без этой ссылки сборщик
    # уносит его вместе с тулбаром, и self.window() падает на
    # удалённом C++-объекте.
    toolbar._test_window = window

    # Всплывашку не строим: проверяется журнал, а InfoBar без настоящей
    # вкладки в тесте только мешает. Журнал пишется до показа.
    monkeypatch.setattr(feedback, "_show", lambda *args: None)
    return toolbar


def _records(journal, text: str):
    return [n for n in journal.get_all() if n.message == text]


def _assert_single_warning(journal, where: str) -> None:
    records = _records(journal, HELPER_TEXT)
    assert len(records) == 1, (
        f"{where}: ожидалась одна запись {HELPER_TEXT!r}, "
        f"получено {len(records)}: "
        f"{[n.message for n in journal.get_all()]}"
    )
    assert records[0].level is Level.WARNING, (
        f"{where}: уровень {records[0].level}, ожидался WARNING"
    )


def test_restart_button_reports_no_active_tab_once(toolbar, journal):
    toolbar._on_restart_pos()

    _assert_single_warning(journal, "_on_restart_pos")


def test_other_buttons_refuse_without_a_title(toolbar, journal):
    """Заголовок есть только там, где он что-то различает.

    У девяти кнопок отказ один и тот же: подпись «Клавиатура» на клике по
    «Рестарт» вводила бы в заблуждение.
    """
    toolbar._on_restart_pos()

    records = _records(journal, HELPER_TEXT)
    assert len(records) == 1
    assert records[0].title == ""


def test_reboot_button_reports_no_active_tab_once(toolbar, journal):
    toolbar._on_reboot_terminal()

    _assert_single_warning(journal, "_on_reboot_terminal")


def test_vnc_button_reports_no_active_tab_once(toolbar, journal):
    toolbar._on_vnc()

    _assert_single_warning(journal, "_on_vnc")


def test_launch_program_reports_no_active_tab_once(toolbar, journal):
    toolbar._launch_program(r"C:\tools\app.exe", "{host}", "Приложение")

    _assert_single_warning(journal, "_launch_program")


def test_postgres_button_reports_no_active_tab_once(toolbar, journal, monkeypatch):
    """Пустой ``db_client_path`` загоняет в ветку встроенного просмотрщика.

    Без пустого пути обработчик уходит в ``_launch_program``, и этот путь
    проверялся бы дважды вместо одного.
    """
    monkeypatch.setattr(
        toolbar._config.settings.programs, "db_client_path", None, raising=False
    )

    toolbar._on_postgres()

    _assert_single_warning(journal, "_on_postgres")


def test_commands_button_reports_no_active_tab_once(toolbar, journal):
    toolbar._on_commands_clicked()

    _assert_single_warning(journal, "_on_commands_clicked")


def test_keyboard_button_reports_no_active_tab_once(toolbar, journal):
    """Клавиатура делит текст с остальными кнопками.

    Отдельный текст означал отдельную полосу: девять одинаковых отказов
    оператор видел девять раз, а после склейки — одну.
    """
    toolbar._on_keyboard()

    _assert_single_warning(journal, "_on_keyboard")


def test_keyboard_refusal_keeps_its_title(toolbar, journal):
    """Отказ клавиатуры назван своей кнопкой.

    Заголовок уходил вместе с переходом на общий хелпер: текст в журнале
    оставался верным, но указания, какая кнопка нажата, не было ни в
    вспышке, ни в списке панели.
    """
    toolbar._on_keyboard()

    records = _records(journal, HELPER_TEXT)
    assert len(records) == 1
    assert records[0].title == "Клавиатура"


@pytest.mark.parametrize(
    ("handler", "kwargs"),
    [
        ("_launch_kitty", {}),
        ("_launch_winscp", {}),
    ],
)
async def test_async_launchers_report_no_active_tab_once(
    handler, kwargs, toolbar, journal
):
    """Корутины отказывают тем же текстом.

    Отдельно потому, что эти обработчики запускаются через ``spawn`` и
    живут вне GUI-потока: путь доставки другой, журнал — тот же.
    """
    await getattr(toolbar, handler)(**kwargs)

    _assert_single_warning(journal, handler)


def test_repeated_clicks_record_each_refusal(toolbar, journal):
    """Два отказа подряд — две записи: журнал хранит факты, а не полосы.

    Сама склейка проверяется отдельно, в `tests/test_feedback.py` на
    `Coalescer`. Здесь `_show` заглушен: проверяется только журнал, и
    приравнивать его записи к полоскам нельзя.
    """
    toolbar._on_restart_pos()
    toolbar._on_restart_pos()

    records = _records(journal, HELPER_TEXT)
    assert len(records) == 2
    assert all(r.level is Level.WARNING for r in records)
