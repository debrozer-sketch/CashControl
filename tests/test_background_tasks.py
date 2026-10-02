"""Фоновые задачи GUI удерживаются в ссылке, а их ошибки логируются.

Регрессия: в десяти местах использовался ``asyncio.ensure_future(...)`` без
сохранения результата. asyncio держит на задачу только слабую ссылку, поэтому
задача могла быть собрана сборщиком мусора посреди выполнения, и действие
молча обрывалось. Исключение из такой задачи к тому же терялось с
предупреждением "Task exception was never retrieved".

``RUF006`` был отключён глобально с комментарием, что fire-and-forget
«намеренный», из-за чего новые случаи не отлавливались.
"""

from __future__ import annotations

import asyncio
import gc

import pytest

from cashcontrol.infrastructure import task_runner
from cashcontrol.infrastructure.task_runner import active_count, cancel_all, spawn


@pytest.fixture(autouse=True)
def _clean():
    yield
    cancel_all()


# ── удержание ссылки ───────────────────────────────────────────────────

async def test_task_is_tracked_while_running():
    started = asyncio.Event()
    release = asyncio.Event()

    async def _work():
        started.set()
        await release.wait()

    task = spawn(_work(), label="проверка")
    await started.wait()

    assert active_count() == 1
    assert task in _tracked()

    release.set()
    await task


async def test_task_is_untracked_after_completion():
    async def _work():
        return 1

    task = spawn(_work())
    await task
    await asyncio.sleep(0)

    assert active_count() == 0
    assert task not in _tracked()


async def test_task_survives_gc():
    """Главный сценарий: без ссылки задачу собирает мусор."""
    started = asyncio.Event()
    release = asyncio.Event()
    done = asyncio.Event()

    async def _work():
        started.set()
        try:
            await release.wait()
        finally:
            done.set()

    spawn(_work())
    await started.wait()

    # Имитируем то, что делает Python при первой же сборке цикла
    for _ in range(3):
        gc.collect()

    release.set()
    # Раньше здесь стояло `await asyncio.wait_for(...), "сообщение"` — это
    # кортеж, а не assert. Тест проходил, только если исключения не было, а
    # диагностическое сообщение не показывалось никогда: при таймауте падало
    # «TimeoutError» без указания, что именно сломалось.
    try:
        await asyncio.wait_for(done.wait(), timeout=3)
    except TimeoutError:
        pytest.fail("задача была уничтожена сборщиком мусора")


async def test_label_is_applied():
    async def _work():
        return None

    task = spawn(_work(), label="метка")
    assert task.get_name() == "метка"
    await task


# ── ошибки не теряются ─────────────────────────────────────────────────

async def test_failure_is_logged(caplog):
    async def _boom():
        raise RuntimeError("сломалось")

    with caplog.at_level("ERROR"):
        task = spawn(_boom(), label="падающая")
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    logged = [r.getMessage() for r in caplog.records if "падающая" in r.getMessage()]
    assert logged, "исключение из фоновой задачи потеряно"
    assert any("сломалось" in m for m in logged)


async def test_cancellation_is_not_logged_as_error(caplog):
    async def _work():
        await asyncio.sleep(10)

    task = spawn(_work())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert not errors, "отмена задачи не должна логироваться как ошибка"


async def test_successful_task_logs_nothing(caplog):
    async def _work():
        return 42

    with caplog.at_level("ERROR"):
        await spawn(_work())
        await asyncio.sleep(0)

    assert not [r for r in caplog.records if r.levelname == "ERROR"]


# ── отмена при выходе ──────────────────────────────────────────────────

async def test_cancel_all_stops_running_tasks():
    started = asyncio.Event()

    async def _work():
        started.set()
        await asyncio.sleep(30)

    task = spawn(_work())
    await started.wait()

    cancel_all()
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert active_count() == 0


async def test_cancel_all_is_idempotent():
    cancel_all()
    cancel_all()
    assert active_count() == 0


# ── покрытие мест применения ───────────────────────────────────────────

@pytest.mark.parametrize(
    "module",
    ["cashcontrol.gui.toolbar", "cashcontrol.gui.tab_manager", "cashcontrol.gui.prefetch"],
)
def test_spawn_is_used_in_gui_module(module):
    """В GUI fire-and-forget обязан идти через spawn, а не ensure_future."""
    import ast
    import importlib
    import inspect
    import textwrap

    mod = importlib.import_module(module)
    src = textwrap.dedent(inspect.getsource(mod))
    tree = ast.parse(src)

    bare = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"ensure_future", "create_task"}
    ]
    assert not bare, (
        f"{module}: найдены вызовы без удержания ссылки — "
        "задача может быть собрана сборщиком мусора"
    )
    assert "spawn" in src, f"{module} не использует task_runner.spawn"


def test_ruf006_can_be_enabled():
    """Глобальное отключение RUF006 больше не нужно и маскировало случаи."""
    import tomllib
    from pathlib import Path

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    ignore = data["tool"]["ruff"]["lint"]["ignore"]
    assert "RUF006" not in ignore, (
        "RUF006 отключён, значит fire-and-forget снова пройдёт молча. "
        "Либо включите проверку, либо уберите глобальное исключение."
    )


def _tracked() -> set:
    return task_runner._background
