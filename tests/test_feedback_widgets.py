"""Всплывашка: липкая ошибка, склейка, запись в журнал, потоки."""

from __future__ import annotations

import threading
import time
from typing import ClassVar

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThread

from cashcontrol.gui import feedback
from cashcontrol.gui.notification_manager import Level


class _FakeSignal:
    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, fn) -> None:
        self.slots.append(fn)


class _FakeLabel:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, value: str) -> None:
        self.text = value


class _FakeBar:
    def __init__(self) -> None:
        self.destroyed = _FakeSignal()
        self.titleLabel = _FakeLabel()
        self.contentLabel = _FakeLabel()
        self.raised = 0

    def raise_(self) -> None:
        self.raised += 1

    def fire_destroyed(self) -> None:
        for slot in list(self.destroyed.slots):
            slot()


class _FakeHost:
    """Окно вместо QWidget.

    ``InfoBar.new`` в тестах подменён, Qt не нужен: достаточно, чтобы
    ``_resolve_parent`` вернула непустой результат. Области содержимого у
    заглушки нет — ``_anchor`` обязан откатиться на само окно, и это
    проверяется само собой тем, что полоса вообще строится.
    """

    def window(self) -> _FakeHost:
        return self

    def findChildren(self, _kind) -> list:
        return []

    def isHidden(self) -> bool:
        return False


class _FakeInfoBarFactory:
    """Подмена ``InfoBar.new``, которая помнит и виджеты, и аргументы.

    Лямбда глотала всё, что передавалось в ``InfoBar.new``, и проверять
    было нечего.
    """

    def __init__(self) -> None:
        self.bars: list[_FakeBar] = []
        self.kwargs: list[dict] = []
        self.args: list[tuple] = []

    def new(self, *args, **kwargs) -> _FakeBar:
        bar = _FakeBar()
        self.bars.append(bar)
        self.args.append(args)
        self.kwargs.append(kwargs)
        return bar


_HOST = _FakeHost()


class _NoApplication:
    """Заглушка приложения: доставлять некуда."""

    @staticmethod
    def instance():
        return None


@pytest.fixture
def infobar(monkeypatch):
    """Подмена фабрики полосы вместо лямбды, глотающей аргументы.

    Подменяется ``new`` у класса, которым ``_present`` реально строит
    полосу, а не у ``InfoBar``: ``InfoBar.new`` собирает базовый класс
    напрямую, и ``_present`` вызывает фабрику подкласса.
    """
    factory = _FakeInfoBarFactory()
    monkeypatch.setattr(
        feedback._BoundedInfoBar, "new", staticmethod(factory.new)
    )
    return factory


@pytest.fixture
def bars(monkeypatch, infobar):
    """Чистое состояние склейки поверх подменённого ``InfoBar.new``."""
    monkeypatch.setattr(feedback, "_live", {})
    coalescer = feedback.Coalescer()
    monkeypatch.setattr(feedback, "_coalescer", coalescer)
    return coalescer


@pytest.fixture
def journal(monkeypatch):
    """Журнал синглтона на время теста.

    Подменяется сам экземпляр, а не чистится общий: прежние тесты
    опустошали синглтон, но не возвращали его состояние, и порядок
    прогона влиял на результат.
    """
    from cashcontrol.gui.notification_manager import (
        NotificationManager,
        get_notification_manager,
    )

    monkeypatch.setattr(NotificationManager, "_instance", NotificationManager())
    return get_notification_manager()


def test_error_never_hides_itself():
    """Отрицательная длительность отключает автоскрытие в qfluentwidgets."""
    assert feedback.DURATION_MS[Level.ERROR] < 0


def test_transient_levels_hide_themselves():
    for level in (Level.INFO, Level.SUCCESS, Level.WARNING):
        assert feedback.DURATION_MS[level] > 0


def test_warning_outlives_info():
    """Предупреждение держится дольше обычного сообщения."""
    assert feedback.DURATION_MS[Level.WARNING] > feedback.DURATION_MS[Level.INFO]


def test_notify_writes_journal_and_shows(monkeypatch, journal):
    shown: list[tuple[str, Level]] = []
    monkeypatch.setattr(
        feedback, "_show", lambda m, lvl, t, p: shown.append((m, lvl))
    )

    feedback.notify("сбор завершён", Level.SUCCESS, title="Сбор данных")

    assert shown == [("сбор завершён", Level.SUCCESS)]
    assert journal.get_all()[0].message == "сбор завершён"


def test_notify_keeps_title_in_journal(monkeypatch, journal):
    monkeypatch.setattr(feedback, "_show", lambda *args: None)

    feedback.notify("сбор завершён", Level.SUCCESS, title="Сбор данных")

    assert journal.get_all()[0].title == "Сбор данных"


def test_typo_in_level_reaches_journal_as_info(monkeypatch, journal):
    shown: list[Level] = []
    monkeypatch.setattr(feedback, "_show", lambda m, lvl, t, p: shown.append(lvl))

    feedback.notify("опечатка в уровне", "sucess")

    assert shown == [Level.INFO]
    assert journal.get_all()[0].level is Level.INFO


def test_error_bar_gets_sticky_duration_at_call_site(bars, infobar):
    """Значение доходит до InfoBar, а не остаётся в словаре."""
    feedback._show("ошибка", Level.ERROR, "Ошибка", _HOST)

    assert infobar.kwargs[0]["duration"] == -1


def test_info_bar_gets_four_seconds_at_call_site(bars, infobar):
    feedback._show("сообщение", Level.INFO, "", _HOST)

    assert infobar.kwargs[0]["duration"] == 4000


def test_repeats_merge_into_one_bar(bars, infobar):
    """Три одинаковых сообщения — одна полоса со счётчиком ×3."""
    for _ in range(3):
        feedback._show("перезагрузка", Level.ERROR, "Ошибка", _HOST)

    assert len(infobar.bars) == 1
    assert infobar.bars[0].contentLabel.text.endswith("×3")


def test_repeat_updates_title_as_well(bars, infobar):
    """Полоска живёт дольше одного события, заголовок тоже устаревает."""
    feedback._show("перезагрузка", Level.ERROR, "Первый", _HOST)
    feedback._show("перезагрузка", Level.ERROR, "Второй", _HOST)

    assert len(infobar.bars) == 1
    assert infobar.bars[0].titleLabel.text == "Второй"
    assert infobar.bars[0].contentLabel.text.endswith("×2")


def test_different_messages_get_their_own_bars(bars, infobar):
    feedback._show("одно", Level.ERROR, "", _HOST)
    feedback._show("другое", Level.ERROR, "", _HOST)

    assert len(infobar.bars) == 2


def test_same_message_in_one_window_still_merges(bars, infobar):
    """Внутри окна склейка обязана сохраниться.

    Окно в ключе — часть решения про разные источники, а не отмена
    склейки: повтор в том же окне это всё ещё повтор одного события.
    """
    host = _FakeHost()

    feedback._show("Экспортировано строк: 40", Level.SUCCESS, "", host)
    feedback._show("Экспортировано строк: 40", Level.SUCCESS, "", host)

    assert len(infobar.bars) == 1
    assert len(bars) == 1
    assert infobar.bars[0].contentLabel.text.endswith("×2")


def test_same_message_in_two_windows_gets_two_bars(bars, infobar):
    """Экспорт и импорт в db_viewer дают одинаковый текст из двух вкладок.

    Ключ склейки без окна склеил бы их в одну полосу с несуществующим
    счётчиком ×2. Хосты держатся в именах: у временного объекта адрес
    мог бы переиспользоваться, и тест прошёл бы на обратном ключе.
    """
    first = _FakeHost()
    second = _FakeHost()

    feedback._show("Экспортировано строк: 40", Level.SUCCESS, "", first)
    feedback._show("Экспортировано строк: 40", Level.SUCCESS, "", second)

    assert len(infobar.bars) == 2
    assert len(bars) == 2
    # Текст новой полоски уходит в InfoBar.new позиционным аргументом.
    # Ни одна не помечена повтором: каждая показана ровно один раз.
    assert [args[2] for args in infobar.args] == [
        "Экспортировано строк: 40",
        "Экспортировано строк: 40",
    ]


def test_destroyed_drops_the_key_of_its_own_window_only(bars, infobar):
    """Закрытие полоски одной вкладки не обнуляет счётчик соседней."""
    first = _FakeHost()
    second = _FakeHost()
    feedback._show("Экспортировано строк: 40", Level.SUCCESS, "", first)
    feedback._show("Экспортировано строк: 40", Level.SUCCESS, "", second)

    infobar.bars[0].fire_destroyed()

    assert list(feedback._live.values()) == [infobar.bars[1]]
    assert len(bars) == 1

    # Повтор во втором окне обновляет свою полоску, а не начинает с единицы.
    feedback._show("Экспортировано строк: 40", Level.SUCCESS, "", second)

    assert len(infobar.bars) == 2
    assert infobar.bars[1].contentLabel.text.endswith("×2")


def test_coalesce_key_holds_the_window_id_not_the_widget():
    """В ключе лежит адрес окна, а не сам виджет.

    Удержание виджета в ключе продлило бы ему жизнь: снятие записи из
    словаря тогда зависело бы от того, кто держит ссылку последним.
    """
    host = _FakeHost()

    key = feedback._coalesce_key("Экспортировано строк: 40", Level.SUCCESS, host)

    assert key == ("Экспортировано строк: 40", "success", id(host))
    assert not any(item is host for item in key)


def test_closed_bar_is_forgotten(bars, infobar):
    """Обработчик destroyed убирает и полоску, и её счётчик."""
    feedback._show("сообщение", Level.INFO, "", _HOST)
    assert feedback._live != {}
    assert len(bars) == 1

    infobar.bars[0].fire_destroyed()

    assert feedback._live == {}
    assert len(bars) == 0


def test_closed_bar_does_not_inflate_the_next_counter(bars, infobar):
    """Пользователь закрыл полоску — следующий показ снова первый.

    Без сброса счётчика тот же текст через пару секунд получил бы ×2 при
    единственном реальном вхождении.
    """
    feedback._show("перезагрузка", Level.ERROR, "Ошибка", _HOST)
    feedback._show("перезагрузка", Level.ERROR, "Ошибка", _HOST)
    assert infobar.bars[0].contentLabel.text.endswith("×2")

    infobar.bars[0].fire_destroyed()

    feedback._show("перезагрузка", Level.ERROR, "Ошибка", _HOST)

    assert len(infobar.bars) == 2
    # Текст новой полоски уходит в InfoBar.new позиционным аргументом.
    assert infobar.args[1][2] == "перезагрузка"
    assert len(bars) == 1


def test_no_parent_means_no_bar(bars, infobar):
    feedback._show("без окна", Level.INFO, "", None)

    assert infobar.bars == []
    # Без окна полоски нет, значит нет и записи склейки: ключ с чужим
    # адресом тут взяться неоткуда.
    assert len(bars) == 0


def test_notify_without_parent_still_writes_journal(monkeypatch, journal, infobar):
    """Полоски нет, но сообщение пользователю всё равно показано не зря."""
    monkeypatch.setattr(feedback, "_live", {})
    monkeypatch.setattr(feedback, "_coalescer", feedback.Coalescer())

    feedback.notify("без окна", Level.WARNING, title="Без окна")

    assert infobar.bars == []
    assert journal.get_all()[0].message == "без окна"
    assert journal.get_all()[0].title == "Без окна"


def test_notify_from_worker_thread_is_delivered_on_gui_thread(qapp, monkeypatch, journal):
    """Вызов из рабочего потока доезжает до GUI-потока и показывается.

    Настоящий путь, без подмены доставки. Отметка ставится обработчиком
    ``InfoBar.new`` только если он видит себя в потоке GUI, поэтому
    доставка, оставшаяся в рабочем потоке, отметки не даст.
    """
    monkeypatch.setattr(feedback, "_live", {})
    monkeypatch.setattr(feedback, "_coalescer", feedback.Coalescer())

    gui_thread = qapp.thread()
    delivered: list[str] = []

    def factory_new(*args, **kwargs):
        if QThread.currentThread() is gui_thread:
            delivered.append(args[2])
        return _FakeBar()

    monkeypatch.setattr(
        feedback._BoundedInfoBar, "new", staticmethod(factory_new)
    )

    errors: list[Exception] = []

    def worker() -> None:
        try:
            feedback.notify("из потока", Level.ERROR, title="Поток", parent=_HOST)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=30)

    assert errors == []
    assert not thread.is_alive()
    # Журнал пишется сразу, из вызывающего потока.
    assert journal.get_all()[0].message == "из потока"

    # Доставка встаёт в очередь событий GUI-потока: крутим цикл, пока
    # отметка не появится. Потолок по времени нужен, чтобы висящий
    # вызов давал провал, а не вечное кружение.
    deadline = time.monotonic() + 10.0
    while not delivered and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert delivered == ["из потока"]


class _FakeButton:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, value: str) -> None:
        self.text = value


class _FakeMessageBox:
    """Окно подтверждения вместо ``MessageBox``.

    ``exec()`` у настоящего окна крутит вложенный Qt-цикл, поэтому
    подменяется всё окно: тесту нужен текст кнопки и факт вызова, а не
    диалог.
    """

    instances: ClassVar[list[_FakeMessageBox]] = []

    def __init__(self, title: str, text: str, parent) -> None:
        self.title = title
        self.text = text
        self.yesButton = _FakeButton()
        self.cancelButton = _FakeButton()
        self.executed = 0
        _FakeMessageBox.instances.append(self)

    def exec(self) -> int:
        self.executed += 1
        return 1


@pytest.fixture
def dialogs(monkeypatch):
    _FakeMessageBox.instances.clear()
    monkeypatch.setattr(feedback, "MessageBox", _FakeMessageBox)
    return _FakeMessageBox.instances


def test_confirm_default_yes_button_says_execute(dialogs):
    feedback.confirm("Подтверждение", "Выполнить действие?", parent=_HOST)

    assert dialogs[0].yesButton.text == "Выполнить"


def test_confirm_destructive_yes_button_says_delete(dialogs):
    feedback.confirm(
        "Удаление", "Удалить запись?", parent=_HOST, destructive=True
    )

    assert dialogs[0].yesButton.text == "Удалить"


def test_confirm_yes_text_wins_over_destructive(dialogs):
    """Кнопка обещает действие окна, а не удаление.

    ``destructive=True`` без ``yes_text`` дал бы «Удалить» в окне
    перезагрузки кассы — обещание, которого в этом окне нет.
    """
    feedback.confirm(
        "Перезагрузка кассы",
        "Перезагрузить кассу 10.0.0.1?",
        parent=_HOST,
        destructive=True,
        yes_text="Перезагрузить",
    )

    assert dialogs[0].yesButton.text == "Перезагрузить"


def test_confirm_cancel_button_says_cancel(dialogs):
    feedback.confirm("Перезагрузка кассы", "Перезагрузить?", parent=_HOST)

    assert dialogs[0].cancelButton.text == "Отмена"


def test_confirm_without_parent_never_answers_yes(dialogs):
    """Нет окна — спросить негде, согласиемся не считаем."""
    assert feedback.confirm("Подтверждение", "Действие?", parent=None) is False
    assert dialogs == []


def test_worker_notify_without_application_logs_instead_of_going_silent(monkeypatch, caplog):
    """Нет приложения — доставка невозможна, но молчать нельзя."""
    # Подменяется только имя внутри feedback: глобальный QApplication
    # трогать нельзя, им пользуется весь остальной код процесса.
    monkeypatch.setattr(feedback, "QApplication", _NoApplication)
    # Чужой поток заставляет уйти в ветку доставки, а заглушка убирает
    # саму возможность доставить.
    monkeypatch.setattr(feedback, "_gui_thread", lambda: object())

    with caplog.at_level("WARNING", logger="cashcontrol"):
        feedback._show("без приложения", Level.ERROR, "Ошибка", _HOST)

    assert any("без приложения" in r.getMessage() for r in caplog.records)

