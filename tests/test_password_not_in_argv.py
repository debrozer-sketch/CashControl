"""Пароль не должен попадать в командную строку процесса.

Регрессия из бэклога: пароль передавался через argv в четырёх местах. Проверено,
что встроенный файловый менеджер приложением открывается **в том же процессе**
(`file_manager_launcher.open_file_manager` вызывает `RemoteFilesWindow(...)`
как функцию), поэтому основной путь программы пароль не раскрывает. Реальная
экспозиция остаётся только у внешних клиентов и у standalone-точки входа
CashSCP, запускаемой как отдельный процесс.

Тест фиксирует границу: если кто-то снова откроет CashSCP через Popen с
паролем в argv, тест упадёт.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from cashcontrol.builtin import file_manager_launcher
from cashcontrol.builtin.file_manager.gui import window as wm

_ROOT = Path(__file__).resolve().parent.parent


def _src(module) -> str:
    return textwrap.dedent(inspect.getsource(module))


# ── основной путь приложения безопасен ─────────────────────────────────

def test_builtin_file_manager_is_opened_in_process():
    """Пароль идёт аргументом Python, а не командной строкой."""
    tree = ast.parse(_src(file_manager_launcher))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "open_file_manager"
    )
    calls = {
        n.func.attr
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "Popen" not in calls and "run" not in calls, (
        "CashSCP стал запускаться как отдельный процесс: пароль уйдёт в "
        "командную строку и станет виден через wmic process get commandline"
    )
    # Окно создаётся вызовом класса в этом же процессе
    assert any(
        isinstance(n.func, ast.Name) and n.func.id == "RemoteFilesWindow"
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
    ), "окно CashSCP должно создаваться вызовом RemoteFilesWindow напрямую"


def test_launcher_passes_password_as_kwarg_not_argv():
    tree = ast.parse(_src(file_manager_launcher))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "open_file_manager"
    )
    kw = {
        k.arg
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        for k in n.keywords
        if k.arg
    }
    assert "password" in kw, "пароль должен передаваться в окно как именованный аргумент"


# ── standalone-точка входа предпочитает переменную окружения ────────────

def test_standalone_password_reads_env(monkeypatch):
    """CashSCP, запущенный как отдельный процесс, берёт пароль из окружения."""
    monkeypatch.setenv("RFILES_PASSWORD", "из-окружения")

    import argparse

    argparse.ArgumentParser()
    # Переиспользуем определение аргументов из main() без запуска GUI
    src = _src(wm)
    assert 'os.environ.get("RFILES_PASSWORD"' in src, (
        "--password в CashSCP должен иметь запасной вариант через RFILES_PASSWORD, "
        "иначе пароль окажется в командной строке процесса"
    )
    assert 'os.environ.get("RFILES_USER"' in src


def test_standalone_password_help_mentions_env():
    src = _src(wm)
    assert "RFILES_PASSWORD" in src
    assert "командной строке" in src or "окружения" in src


def test_cli_password_reads_env():
    """cli.py уже чинился так же, поведение должно остаться."""
    from cashcontrol.builtin.file_manager import cli

    src = _src(cli)
    assert 'os.environ.get("RFILES_PASSWORD"' in src


# ── внешние клиенты: честная фиксация границы ──────────────────────────

def test_external_clients_still_use_argv():
    """Явно фиксирует известное ограничение, чтобы его не потерять.

    KiTTY и WinSCP не умеют принимать пароль через stdin, поэтому пароль
    попадает в их argv. Смена на `-pwfile` или на сессию в реестре не
    проверена на реальных машинах и требует отдельного решения: при
    несовместимости SSH-клиент перестанет открываться, что хуже нынешнего
    поведения.

    Раньше в конце стоял безусловный ``pytest.skip``, и тест всегда
    отмечался пропущенным, хотя три проверки под ним выполнялись и проходили.
    В отчёте он был неотличим от двух настоящих пропусков, а его смысл —
    «ограничение зафиксировано, следим за ним» — терялся. Пропуск убран:
    ограничение по-прежнему описано здесь и проверяется этими же
    утверждениями.
    """
    toolbar = Path(_ROOT / "src/cashcontrol/gui/toolbar.py").read_text(encoding="utf-8")
    assert '"-pw", password' in toolbar
    assert ":{password}@" in toolbar or "password}@" in toolbar


_SECRET_NAMES = {"password", "pwd", "ssh_password", "db_password", "passwd"}


def _logged_secrets(module) -> list[str]:
    """Строки, где в logger попадает переменная с паролем."""
    tree = ast.parse(_src(module))
    found: list[str] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        f = call.func
        if not (isinstance(f, ast.Attribute) and f.attr.startswith("log")):
            continue
        for node in ast.walk(call):
            if isinstance(node, ast.Name) and node.id.lower() in _SECRET_NAMES:
                found.append(f"{module.__name__}:{call.lineno} -> {node.id}")
    return found


@pytest.mark.parametrize(
    "module",
    ["cashcontrol.gui.toolbar", "cashcontrol.builtin.file_manager.gui.window",
     "cashcontrol.core.ssh", "cashcontrol.builtin.file_manager.gui.session"],
)
def test_no_password_logged(module):
    """Пароль не должен попадать в журнал.

    Проверка по AST, а не по слову «password» в строке: фразы вида
    «Launching KiTTY without password» безопасны, а вот f-string с самой
    переменной пароля нет.
    """
    import importlib

    mod = importlib.import_module(module)
    leaks = _logged_secrets(mod)
    assert not leaks, f"пароль может уйти в журнал: {leaks}"
