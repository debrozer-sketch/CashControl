"""Воркеры DB Viewer не должны переживать свою панель.

Регрессия: ``_Worker`` — это ``QThread`` с ``parent=<панель>``, то есть
дочерний QObject. В панели данных воркеры экспорта CSV и импорта CSV
создавались как локальная переменная и нигде не сохранялись, а ``_close_tab``
отменял только ``panel._worker`` (последний загрузчик). Уничтожение панели
во время работы воркера даёт ``QThread: Destroyed while thread is still
running`` и ``qFatal`` → ``abort()``: приложение умирает без трассировки.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from cashcontrol.builtin.db_viewer.data_panel import _DataPanel
from cashcontrol.builtin.db_viewer.sql_console import _SqlConsole
from cashcontrol.builtin.db_viewer.workers import _Worker


def _factory():
    class _F:
        host = "10.0.0.1"
        port = 5432
        user = "postgres"
        database = "postgres"

        def connect(self, database=None):  # pragma: no cover - не вызывается
            raise AssertionError("соединение не требуется для проверки учёта")

    return _F()


def _tracked_workers(panel) -> list[_Worker]:
    return list(panel._workers)


# ── учёт воркеров ──────────────────────────────────────────────────────

def test_data_panel_shutdown_cancels_all_workers(qtbot):
    """Главный сценарий: воркеры импорта/экспорта обязаны остановиться."""
    panel = _DataPanel(_factory(), "postgres", "public", "t1")
    qtbot.addWidget(panel)

    started = []
    for _ in range(3):
        w = _Worker(_factory(), lambda conn, worker: time.sleep(30), parent=panel)
        started.append(w)
        panel._start_worker(w)

    assert len(_tracked_workers(panel)) == 3, "воркеры не взяты под учёт"
    assert panel._worker is started[-1]

    panel.shutdown()

    for w in started:
        deadline = time.monotonic() + 3
        while w.isRunning() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not w.isRunning(), "воркер пережил shutdown панели"
    assert panel._workers == set()
    assert panel._worker is None


def test_finished_worker_is_removed_from_tracking(qtbot):
    panel = _DataPanel(_factory(), "postgres", "public", "t1")
    qtbot.addWidget(panel)

    w = _Worker(_factory(), lambda conn, worker: 1, parent=panel)
    panel._start_worker(w)
    w.wait(3000)

    assert not w.isRunning()
    # finished приходит из рабочего потока, поэтому обработкаqueued-сигнала
    # требует прокрутки цикла событий.
    qtbot.waitUntil(lambda: not w.isRunning(), timeout=3000)
    QApplication.processEvents()

    assert panel._workers == set(), "завершившийся воркер остался в учёте"
    assert panel._worker is w  # последний указатель сохраняется для reload() и save()


def test_shutdown_without_workers_is_safe(qtbot):
    panel = _DataPanel(_factory(), "postgres", "public", "t1")
    qtbot.addWidget(panel)
    panel.shutdown()
    panel.shutdown()


# ── путь закрытия вкладки ──────────────────────────────────────────────

@pytest.mark.parametrize(
    ("cls", "method"),
    [(_DataPanel, "open"), (_DataPanel, "_run_write"),
     (_DataPanel, "export"), (_DataPanel, "import_csv")],
)
def test_every_data_panel_worker_goes_through_tracking(cls, method):
    """Ни один воркер в панели не должен запускаться минуя учёт.

    Раньше export_csv и import_csv делали ``w.start()`` напрямую, воркер
    нигде не сохранялся, и панель уничтожала его во время работы.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(cls))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method
    )

    def calls(attr):
        return [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == attr
        ]

    tracked = calls("_start_worker") + calls("_track")
    bare_start = [
        n for n in calls("start")
        # .start() внутри _start_worker сюда не попадает: он в другом методе
        if not (isinstance(n.func.value, ast.Name) and n.func.value.id == "self")
    ]

    assert tracked, (
        f"{cls.__name__}.{method}: воркер не проходит через учёт. "
        "Панель уничтожит его во время работы, и Qt завершит приложение "
        "через abort() без трассировки."
    )
    assert not bare_start, (
        f"{cls.__name__}.{method} вызывает .start() напрямую, минуя учёт"
    )


def test_sql_console_workers_go_through_tracking():
    import ast
    import inspect

    src = Path(inspect.getfile(_SqlConsole)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for method in ("execute", "_export"):
        fn = next(
            (n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method),
            None,
        )
        if fn is None:
            continue
        bare = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "start"
        ]
        assert not bare, f"_SqlConsole.{method} запускает воркер напрямую, минуя учёт"


def test_close_tab_shuts_down_panel_before_delete(qtbot):
    """widget._close_tab обязан вызвать shutdown до deleteLater()."""
    import ast
    import inspect
    from pathlib import Path

    from cashcontrol.builtin.db_viewer import widget as wg

    tree = ast.parse(Path(inspect.getfile(wg.PostgresToolWidget)).read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_close_tab"
    )
    called = [
        n.func.attr for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    ]
    assert "shutdown" in called, "_close_tab не вызывает panel.shutdown()"
    assert "deleteLater" in called

    body = ast.dump(fn)
    assert body.index("'shutdown'") < body.index("'deleteLater'"), (
        "deleteLater() вызывается раньше shutdown(): панель будет уничтожена "
        "во время работы воркеров, и Qt завершит приложение через abort()"
    )


def test_widget_shutdown_reaches_every_panel(qtbot):
    import ast
    import inspect
    from pathlib import Path

    from cashcontrol.builtin.db_viewer import widget as wg

    src = Path(inspect.getfile(wg.PostgresToolWidget)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "shutdown"
    )
    called = {
        n.func.attr for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    # Панели вкладок и SQL-консоль
    assert "shutdown" in called
    assert "cancel" in called or "shutdown" in called


def test_sql_console_tracks_and_cancels_export_worker(qtbot):
    console = _SqlConsole(_factory())
    qtbot.addWidget(console)

    w = _Worker(_factory(), lambda conn, worker: time.sleep(30), parent=console)
    console._start_worker(w)

    assert console._workers == {w}
    console.shutdown()

    deadline = time.monotonic() + 3
    while w.isRunning() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not w.isRunning(), "экспорт из консоли пережил shutdown"
