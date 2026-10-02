"""Закрытие вкладки CashSCP не блокирует интерфейс.

Регрессия: ``_close_tab`` вызывал ``session.shutdown()`` прямо из GUI-потока.
Внутри это ``future.result(timeout=2)`` плюс ``thread.join(timeout=5)``, то
есть до 7 секунд заморозки на одну вкладку, и таких вкладок могло быть
несколько. Плюс ``deleteLater()`` не вызывался вовсе, поэтому виджет сессии
оставался живым, удерживаемый циклом ссылок через сигналы.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from cashcontrol.builtin.file_manager.gui import window as wm
from cashcontrol.builtin.file_manager.gui.window import (
    RemoteFilesWindow,
    _ShutdownBridge,
)


def _method_source(cls, name: str) -> str:
    return textwrap.dedent(inspect.getsource(getattr(cls, name)))


# ── структурные проверки ───────────────────────────────────────────────

def test_close_tab_does_not_call_shutdown_inline():
    """Главный симптом: блокирующий вызов в обработчике закрытия вкладки."""
    src = _method_source(RemoteFilesWindow, "_close_tab")
    tree = ast.parse(src)

    direct = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "shutdown"
    ]
    assert not direct, (
        "_close_tab вызывает session.shutdown() напрямую: остановка занимает "
        "до 7 с и блокирует GUI-поток"
    )


def test_close_tab_goes_through_bridge():
    src = _method_source(RemoteFilesWindow, "_close_tab")
    assert "_shutdown_bridge.run" in src


def test_close_tab_removes_widget_before_shutdown():
    """Вкладка должна исчезнуть сразу, не дожидаясь остановки потоков."""
    src = _method_source(RemoteFilesWindow, "_close_tab")
    body = ast.dump(ast.parse(src))
    assert body.index("removeTab") < body.index("'run'"), (
        "removeTab() вызывается после запуска остановки: пользователь увидит "
        "зависшую вкладку на время блокировки"
    )


def test_close_event_does_not_call_shutdown_inline():
    src = _method_source(RemoteFilesWindow, "closeEvent")
    tree = ast.parse(src)
    direct = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "shutdown"
    ]
    assert not direct, "closeEvent блокирует GUI на остановке каждой вкладки"
    assert "_shutdown_bridge.run" in src


def test_delete_later_is_connected():
    """deleteLater() обязан вызываться из GUI-потока, иначе Qt не тянет."""
    src = inspect.getsource(RemoteFilesWindow)
    assert "_on_session_stopped" in src
    handler = _method_source(RemoteFilesWindow, "_on_session_stopped")
    assert "deleteLater" in handler


# ── поведение ─────────────────────────────────────────────────────────

class _SlowSession:
    """Сессия, остановка которой занимает заметное время."""

    def __init__(self) -> None:
        self.shutdown_done = False
        self.deleted = False

    def shutdown(self) -> None:
        time.sleep(0.4)
        self.shutdown_done = True

    def deleteLater(self) -> None:
        self.deleted = True


def test_bridge_does_not_block_caller(qtbot):
    """Главный сценарий: вызов возвращается мгновенно."""
    bridge = _ShutdownBridge()
    session = _SlowSession()

    t0 = time.monotonic()
    bridge.run(session)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.1, (
        f"run() блокировал {elapsed:.2f} с вместо того чтобы уйти в поток"
    )
    assert session.shutdown_done is False, "остановка выполнилась синхронно"

    # Дожидаемся завершения в потоке
    deadline = time.monotonic() + 5
    while not session.shutdown_done and time.monotonic() < deadline:
        time.sleep(0.02)
    assert session.shutdown_done


def test_bridge_reports_back_for_gui_cleanup(qtbot):
    """Сигнал finished нужен, чтобы deleteLater выполнился в GUI-потоке."""
    bridge = _ShutdownBridge()
    received: list[object] = []
    bridge.finished.connect(received.append, Qt.QueuedConnection)

    session = _SlowSession()
    bridge.run(session)

    deadline = time.monotonic() + 5
    while not received and time.monotonic() < deadline:
        qtbot.wait(20)

    assert received == [session]


def test_bridge_survives_shutdown_error(qtbot, caplog):
    class _Broken(_SlowSession):
        def shutdown(self) -> None:
            raise RuntimeError("поток не остановился")

    bridge = _ShutdownBridge()
    received: list[object] = []
    bridge.finished.connect(received.append, Qt.QueuedConnection)

    bridge.run(_Broken())

    deadline = time.monotonic() + 5
    while not received and time.monotonic() < deadline:
        qtbot.wait(20)

    assert received, "после ошибки остановки сигнал finished не пришёл, виджет утечёт"
    assert any("Ошибка остановки" in r.getMessage() for r in caplog.records)


def test_bridge_handles_missing_shutdown(qtbot):
    class _NoShutdown:
        deleted = False

        def deleteLater(self):
            self.deleted = True

    bridge = _ShutdownBridge()
    received: list[object] = []
    bridge.finished.connect(received.append, Qt.QueuedConnection)

    bridge.run(_NoShutdown())

    deadline = time.monotonic() + 5
    while not received and time.monotonic() < deadline:
        qtbot.wait(20)
    assert received


def test_close_tab_actual_call_is_fast(qtbot):
    """Закрытие вкладки на живой сессии не должно занимать секунды."""
    win = RemoteFilesWindow()
    qtbot.addWidget(win)

    sessions: list[_SlowSession] = []

    class _FakeTab:
        def widget(self, i):
            return sessions[0] if sessions else None

        def removeTab(self, i):
            pass

        def count(self):
            return 1 if sessions else 0

    win._tabs = _FakeTab()
    win._add_session = lambda: None

    session = _SlowSession()
    sessions.append(session)

    t0 = time.monotonic()
    win._close_tab(0)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.1, f"_close_tab занял {elapsed:.2f} с"


def test_window_module_has_no_blocking_join():
    """Прямой вызов shutdown() допустим только внутри рабочего потока моста."""
    tree = ast.parse(Path(inspect.getfile(wm)).read_text(encoding="utf-8"))
    bridge_method_names = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name in {"run", "_worker"}
    }

    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "shutdown":
                continue
            # Внутри потока моста вызов уместен
            if fn.name in bridge_method_names or any(
                isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef))
                and inner.name == "_worker"
                for inner in ast.walk(fn)
            ):
                continue
            offenders.append(f"{fn.name}()")

    assert not offenders, (
        f"прямой session.shutdown() вне рабочего потока: {offenders}. "
        "Он блокирует GUI на десятки секунд при нескольких вкладках."
    )


@pytest.mark.parametrize("method", ["_close_tab", "closeEvent"])
def test_no_thread_join_in_gui_thread(method):
    src = _method_source(RemoteFilesWindow, method)
    assert ".join(" not in src
    assert "future.result(" not in src
