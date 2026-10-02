"""Поиск в редакторе БД идёт по всей таблице, а не по загруженной странице.

Дефект, который закрывают эти проверки: поиск прятал строки среди уже
загруженных, поэтому искомая строка дальше сотой не находилась, а пустой грид
выглядел как «ничего нет». Левая панель с фильтром таблиц к поиску отношения не
имеет, но именно из-за неё дефект и обнаружился.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from cashcontrol.builtin.db_viewer.sql import _LIKE_ESCAPE_RE, _search_where

# ── условие поиска ──────────────────────────────────────────────────


def _sql_text(composed) -> str:
    """Разобрать Composable в читаемый SQL.

    ``as_string`` требует живого соединения, а условие проверяется без базы,
    поэтому строка собирается из тех же кусков вручную. Значения литералов
    подставляются как есть — важна структура, а не значения.
    """
    def walk(node):
        inner = getattr(node, "_wrapped", None)
        if not isinstance(inner, (tuple, list)):
            return str(node)
        return "".join(walk(piece) for piece in inner)

    return walk(composed)


def test_search_covers_every_column():
    cols = [{"name": "key"}, {"name": "value"}]
    sql = _sql_text(_search_where("DNS1", cols))

    assert "key" in sql and "value" in sql
    assert sql.count(" OR ") == 1, "условия колонок должны соединяться через OR"
    assert "ILIKE" in sql


def test_search_is_narrowed_to_the_chosen_column():
    cols = [{"name": "key"}, {"name": "value"}]
    sql = _sql_text(_search_where("DNS1", cols, only_col="key"))

    assert "value" not in sql, "выбранная колонка ограничивает поиск"
    assert "key" in sql


def test_wildcards_in_the_query_are_escaped():
    """Поиск «50%» ищет текст «50%», а не работает как шаблон.

    Без экранирования «_» в запросе совпала бы с любым символом, и в выдачу
    попадали строки, которых оператор не искал.
    """
    assert _LIKE_ESCAPE_RE.sub(r"\\\1", "50%_x") == r"50\%\_x"
    sql = _sql_text(_search_where("50%_x", [{"name": "key"}]))
    assert r"\%" in sql and r"\_" in sql
    assert "ESCAPE" in sql


def test_blank_search_builds_no_condition():
    assert _search_where("   ", [{"name": "key"}]) is None


# ── конфликт «%» с подстановкой psycopg2 ────────────────────────────


def test_query_with_search_keeps_no_placeholders():
    """В собранном запросе не должно остаться ``%s``.

    psycopg2, получив ``params``, прогоняет собранный текст через
    %-подстановку. Рукописный «%» из условия поиска становился спецсимволом
    формата, и загрузка падала: поиск «DNS1» даёт «%DNS1%», а «%D» —
    недопустимый спецсимвол. Проверено: ``q % (...)`` даёт ``ValueError:
    unsupported format character 'D'``.
    """
    from cashcontrol.builtin.db_viewer.sql import _search_where, _sel_query

    cols = [{"name": "key"}]
    q = _sel_query(
        "catalog", "t", cols,
        _search_where("DNS1", cols), None, 100, 0)

    assert "%s" not in _sql_text(q), "остался плейсхолдер %s рядом с данными"


def test_page_is_loaded_without_params(monkeypatch):
    """Загрузка страницы идёт без params — подстановки не происходит вовсе."""
    from cashcontrol.builtin.db_viewer import sql as sqlmod

    seen = {}

    class _Cursor:
        def execute(self, *args, **kwargs):
            # Пишем все вызовы, а не последний: при активном поиске их два
            # (сама страница и счётчик), и проверка одного последнего
            # пропустила бы params на первом запросе.
            seen.setdefault("calls", []).append((args, kwargs))

        def fetchmany(self, n):
            return []

        def fetchone(self):
            return (0,)

    class _Conn:
        def cursor(self):
            return _Cursor()

    monkeypatch.setattr(sqlmod, "_load_meta", lambda *a, **k: {
        "columns": [{"name": "key"}], "pk": ["key"], "estimated": 5})

    sqlmod._load_page(_Conn(), None, "catalog", "t", 100, 0, None,
                      "", "DNS1", None)

    assert seen["calls"], "запрос не выполнен"
    for args, kwargs in seen["calls"]:
        assert len(args) == 1, f"запрос ушёл с параметрами: {args!r}"
        assert kwargs in (None, {}), f"запрос ушёл с параметрами: {kwargs!r}"


def test_page_load_passes_search_to_the_database(monkeypatch):
    """Поиск доезжает до запроса, а не остаётся в поле ввода."""
    from cashcontrol.builtin.db_viewer import sql as sqlmod

    captured = {}

    class _Cursor:
        def execute(self, *args, **kwargs):
            if not isinstance(args[0], str):
                captured.setdefault("queries", []).append(args[0])
                return
            captured.setdefault("count_query", args[0])

        def fetchmany(self, n):
            return []

        def fetchone(self):
            return (0,)

    class _Conn:
        def cursor(self):
            return _Cursor()

    monkeypatch.setattr(sqlmod, "_load_meta", lambda *a, **k: {
        "columns": [{"name": "key"}], "pk": ["key"], "estimated": 5})

    sqlmod._load_page(_Conn(), None, "catalog", "t", 100, 0, None,
                      "", "DNS1", None)

    assert captured.get("queries"), "условие поиска не попало в запрос"


def test_columns_are_cast_to_text():
    """ILIKE не существует для jsonb и массивов.

    В кассовых таблицах такие колонки есть, и без приведения запрос падал бы
    с «operator does not exist» на первой же из них.
    """
    sql = _sql_text(_search_where("x", [{"name": "payload"}]))
    assert "::text" in sql


# ── панель данных ───────────────────────────────────────────────────


@pytest.fixture
def panel(qapp, qtbot):
    from cashcontrol.builtin.db_viewer.data_panel import _DataPanel

    p = _DataPanel(lambda: None, "postgres", "catalog", "sales_management_properties")
    qtbot.addWidget(p)
    p._meta = {"columns": [{"name": "key"}, {"name": "value"}], "pk": ["key"]}
    p._search_col.addItems(["key", "value"])
    return p


def test_search_is_sent_to_the_database(panel, monkeypatch):
    """Поиск обязан дойти до базы, а не спрятать строки на странице."""
    calls = []
    monkeypatch.setattr(panel, "reload", lambda: calls.append(
        (panel._search_text, panel._search_column)))

    panel._search_edit.setText("DNS1")

    assert panel._search_edit.text() == "DNS1", "текст должен долежать до запроса"
    panel._apply_search()

    assert calls == [("DNS1", None)], "поиск не ушёл в запрос"
    assert panel._page == 1, "результат поиска должен начинаться с первой страницы"


def test_search_column_narrows_the_query(panel, monkeypatch):
    calls = []
    monkeypatch.setattr(panel, "reload", lambda: calls.append(
        (panel._search_text, panel._search_column)))

    panel._search_edit.setText("DNS1")
    panel._search_col.setCurrentText("key")
    panel._apply_search()

    assert calls[-1] == ("DNS1", "key")


def test_typing_does_not_hit_the_database_on_every_letter(panel, monkeypatch):
    """Ввод фильтруется с задержкой: буква за буквой по базе — это десятки
    запросов на слово."""
    from cashcontrol.builtin.db_viewer.data_panel import _SEARCH_DEBOUNCE_MS

    calls = []
    monkeypatch.setattr(panel, "reload", lambda: calls.append(1))

    panel._search_edit.setText("D")

    assert calls == [], "запрос ушёл до истечения задержки"
    assert panel._search_timer.interval() == _SEARCH_DEBOUNCE_MS


def test_reset_clears_the_query(panel, monkeypatch):
    calls = []
    monkeypatch.setattr(panel, "reload", lambda: calls.append(1))

    panel._search_edit.setText("DNS1")
    panel._search_col.setCurrentText("key")
    panel._apply_search()
    panel._reset_search()

    assert panel._search_text == ""
    assert panel._search_column is None
    assert panel._search_col.currentText() == "Все колонки"


def test_found_count_is_shown(panel):
    panel._search_text = "DNS1"
    panel._update_search_label(2)
    assert "2" in panel._lbl_search.text()


def test_empty_result_says_where_it_looked(panel):
    """Пустой результат обязан отличаться от «грузится» и говорить, где искали."""
    panel._search_text = "DNS1"
    panel._update_search_label(0)

    text = panel._lbl_search.text()
    assert "DNS1" in text
    assert "не найдено" in text.lower()
    assert "всей таблице" in text, "не сказано, что искали по всей таблице, а не по странице"


def test_no_label_without_a_query(panel):
    panel._search_text = ""
    panel._update_search_label(7)
    assert panel._lbl_search.text() == ""
