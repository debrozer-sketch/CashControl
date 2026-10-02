"""Журнал принимает четыре уровня и не даёт тихой опечатки."""

from __future__ import annotations

from cashcontrol.gui.feedback import Coalescer
from cashcontrol.gui.notification_manager import (
    Level,
    NotificationManager,
    normalize_level,
)


def _fresh() -> NotificationManager:
    manager = NotificationManager()
    manager.clear()
    return manager


def _clock() -> tuple[list[float], object]:
    """Подставные часы и список, которым двигают время.

    Часы внедрены в ``Coalescer``, а не подменён ``time.monotonic`` всего
    процесса: подмена модуля задевала всё, что считает время в прогоне.
    """
    now = [1000.0]
    return now, (lambda: now[0])


def test_all_four_levels_are_accepted():
    manager = _fresh()
    for level in ("info", "success", "warning", "error"):
        n = manager.record("проверка", level=level)
        assert n.level is Level(level)


def test_unknown_level_becomes_info_and_is_logged(caplog):
    with caplog.at_level("WARNING", logger="cashcontrol"):
        result = normalize_level("sucess")
    assert result is Level.INFO
    assert any("sucess" in r.getMessage() for r in caplog.records)


def test_level_enum_is_a_string_for_palette_lookup():
    assert Level.ERROR == "error"


def test_record_appends_newest_first():
    manager = _fresh()
    manager.record("первое")
    manager.record("второе")
    assert [n.message for n in manager.get_all()] == ["второе", "первое"]


def test_record_returns_entry_with_id_and_title():
    manager = _fresh()
    n = manager.record("сбор данных", Level.INFO, title="Сбор данных")
    assert n.title == "Сбор данных"
    assert n.timestamp is not None
    # Идентификаторы монотонны, а очистка журнала возвращает счётчик к
    # началу. Проверка «id > 0» была истинна для любого числа и ничего
    # не утверждала.
    assert manager.record("второе").id == n.id + 1
    manager.clear()
    assert manager.record("третье").id == 1


def test_same_text_within_window_bumps_counter():
    c = Coalescer(window_ms=5000)
    assert c.bump("перезагрузка", "error") == 1
    assert c.bump("перезагрузка", "error") == 2
    assert c.bump("перезагрузка", "error") == 3


def test_different_text_is_separate():
    c = Coalescer(window_ms=5000)
    assert c.bump("одно", "error") == 1
    assert c.bump("другое", "error") == 1


def test_different_level_is_separate():
    c = Coalescer(window_ms=5000)
    assert c.bump("текст", "error") == 1
    assert c.bump("текст", "info") == 1


def test_counter_resets_after_window():
    now, clock = _clock()
    c = Coalescer(window_ms=5000, clock=clock)
    # Дельты в секундах: monotonic() возвращает секунды, а окно задано в
    # миллисекундах. Прибавление 4000 означало бы 4000 секунд, и окно
    # истекало бы мгновенно — счётчик никогда не дорастал бы до двух.
    assert c.bump("текст", "info") == 1
    now[0] += 4
    assert c.bump("текст", "info") == 2
    now[0] += 6  # с последнего показа прошло 6 секунд, окно истекло
    assert c.bump("текст", "info") == 1


def test_forget_drops_the_counter():
    """Закрытая полоска не должна оставлять за собой счётчик."""
    _, clock = _clock()
    c = Coalescer(window_ms=5000, clock=clock)
    assert c.bump("текст", "info") == 1
    assert c.bump("текст", "info") == 2

    c.forget("текст", "info")

    assert len(c) == 0
    assert c.bump("текст", "info") == 1


def test_coalescer_drops_the_oldest_over_capacity():
    """Ключ строится из текста, то есть заранее не ограничен."""
    now, clock = _clock()
    c = Coalescer(window_ms=5000, clock=clock, capacity=2)
    c.bump("а", "info")
    now[0] += 1
    c.bump("б", "info")
    now[0] += 1
    c.bump("в", "info")

    assert len(c) == 2

    # «а» вытеснен как самая старая, поэтому начинается заново.
    now[0] += 1
    assert c.bump("а", "info") == 1


def test_coalescer_evicts_by_time_not_by_insertion_order():
    """Порядок вставки расходится со временем показа.

    «а» вставлено первым, но повторно показано последним, поэтому по
    времени самая старая запись — «б». Вытеснение по ``next(iter(...))``
    выбрало бы «а» и этот тест упал бы.
    """
    now, clock = _clock()
    c = Coalescer(window_ms=50000, clock=clock, capacity=2)

    c.bump("а", "info")  # t=1000, вставлено первым
    now[0] += 1
    c.bump("б", "info")  # t=1001, вставлено вторым
    now[0] += 1
    c.bump("а", "info")  # t=1002, метка «а» теперь самая свежая

    now[0] += 1
    c.bump("в", "info")  # t=1003, предел превышен

    assert len(c) == 2
    # «б» — самая старая по времени, и он вытеснен.
    now[0] += 1
    assert c.bump("б", "info") == 1


def test_first_show_has_no_counter():
    """Счётчик появляется только со второго показа."""
    c = Coalescer(window_ms=5000)
    assert c.bump("текст", "info") == 1
