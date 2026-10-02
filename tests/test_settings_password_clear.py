"""«Отмена» в настройках не должна стирать пароли безвозвратно.

Регрессия: ``_clear_ssh_passwords`` и ``_clear_db_passwords`` писали
``config.update(..., *_passwords_encrypted=[])`` сразу. ``ConfigManager.update``
сохраняет настройки немедленно, а кнопка «Отмена» выполняет ``reject()`` и
save() не вызывает. В итоге пользователь нажимал «Очистить», потом «Отмена»,
и пароли пропадали навсегда, хотя диалог читался как транзакционный.

Теперь очистка помечается флагом и применяется только в save().
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from cashcontrol.gui.dialogs.settings import tab_connection as tc


def _method(name: str):
    tree = ast.parse(Path(inspect.getfile(tc)).read_text(encoding="utf-8"))
    return next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )


def _config_updates(fn) -> list[str]:
    """Список вызовов config.update("connection", ...) по атрибутам полей."""
    found = []
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if n.func.attr != "update" or not n.args:
            continue
        section = n.args[0]
        if not (isinstance(section, ast.Constant) and section.value == "connection"):
            continue
        for kw in n.keywords:
            if kw.arg and "passwords_encrypted" in kw.arg:
                found.append(kw.arg)
    return found


# ── очистка не пишет в конфиг сразу ────────────────────────────────────

@pytest.mark.parametrize("method", ["_clear_ssh_passwords", "_clear_db_passwords"])
def test_clear_does_not_touch_config_immediately(method):
    updates = _config_updates(_method(method))
    assert not updates, (
        f"{method} пишет {updates} напрямую: ConfigManager.update сохраняет "
        "настройки сразу, и «Отмена» уже не откатит изменение"
    )


@pytest.mark.parametrize("method", ["_clear_ssh_passwords", "_clear_db_passwords"])
def test_clear_sets_deferred_flag(method):
    src = inspect.getsource(getattr(tc.TabConnection, method))
    assert "_cleared = True" in src, f"{method} не выставляет флаг отложенной очистки"


def test_save_applies_pending_clearing():
    """save() обязан записать пустой список, если очистка была помечена."""
    fn = _method("save")
    assert "ssh_passwords_encrypted" in _config_updates(fn)
    assert "db_passwords_encrypted" in _config_updates(fn)

    src = inspect.getsource(tc.TabConnection.save)
    assert "_ssh_passwords_cleared" in src
    assert "_db_passwords_cleared" in src
    # Очистка должна обрабатываться раньше текста в поле, иначе повторно
    # введённый пароль перезапишет намерение удалить все
    assert "elif ssh_text" in src, "очистка не имеет приоритета над текстом поля"
    assert src.index("if self._ssh_passwords_cleared") < src.index("elif ssh_text")
    assert src.index("if self._db_passwords_cleared") < src.index("elif db_text")


def test_load_resets_flags():
    src = inspect.getsource(tc.TabConnection.load)
    for flag in ("_ssh_passwords_cleared", "_db_passwords_cleared"):
        assert flag in src, f"load() не сбрасывает {flag}: очистка переживёт переоткрытие диалога"


def test_constructor_initialises_flags():
    src = inspect.getsource(tc.TabConnection.__init__)
    for flag in ("_ssh_passwords_cleared", "_db_passwords_cleared"):
        assert flag in src, f"__init__ не инициализирует {flag}"


# ── поведение на настоящем виджете ─────────────────────────────────────

def _tab_with_config(qtbot, config_manager, passwords=("pw1", "pw2")):
    """Таб настроек поверх изолированного ConfigManager (см. tests/conftest.py).

    Раньше здесь подменялся ConfigManager._resolve_path, но ConfigManager это
    синглтон с кэшируемым путём, поэтому подмена не действовала и тест писал
    в настоящий data/settings.json.
    """
    config_manager.update("connection", ssh_passwords_encrypted=list(passwords))
    tab = tc.TabConnection()
    qtbot.addWidget(tab)
    tab.load(config_manager)
    return tab, config_manager


class _AutoYes:
    """Подтверждение, на которое всегда отвечают «Да».

    Запоминает свои вызовы: подмена, которая ничего не различает, годится
    только чтобы тест позеленел. С её списком видно, что вопрос задан и с
    каким заголовком, а тест, до которого код не дошёл, падает.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs) -> bool:
        self.calls.append((args, kwargs))
        return True

    @property
    def titles(self) -> list[str]:
        return [args[0] for args, _ in self.calls if args]


@pytest.fixture
def auto_yes(monkeypatch) -> _AutoYes:
    """Окно подтверждения заменяется на безусловное «Да».

    Подменяется ``feedback.confirm``, а не ``MessageBox`` в модуле вкладки:
    очистка паролей ушла на единый API, и подмена класса окна больше не
    мешает — вместо неё открылось бы настоящее модальное окно и тест встал бы.

    Намерение прежнее: код обязан спросить разрешение, а тест отвечает «да».
    Фикстура возвращает подмену, чтобы тесты, которым нужно подтверждение,
    проверяли ещё и сам факт вопроса.
    """
    from cashcontrol.gui import feedback

    stub = _AutoYes()
    monkeypatch.setattr(feedback, "confirm", stub)
    return stub


def test_cancel_keeps_passwords(qtbot, config_manager, auto_yes):
    """Главный сценарий: очистили, нажали «Отмена», пароли на месте."""
    tab, cfg = _tab_with_config(qtbot, config_manager)
    assert cfg.settings.connection.ssh_passwords_encrypted == ["pw1", "pw2"]

    tab._clear_ssh_passwords()
    assert not tab.ssh_passwords.toPlainText().strip()

    # «Отмена»: save() не вызывается
    cfg.reload()

    assert cfg.settings.connection.ssh_passwords_encrypted == ["pw1", "pw2"], (
        "пароли исчезли без сохранения: диалог ведёт себя не как транзакция"
    )


def test_save_clears_passwords_when_confirmed(qtbot, config_manager, auto_yes):
    tab, cfg = _tab_with_config(qtbot, config_manager)

    tab._clear_ssh_passwords()
    tab.save(cfg)

    assert cfg.settings.connection.ssh_passwords_encrypted == []
    # Очистка обязана была спросить: без вопроса подмена ни разу не
    # вызвалась бы, и тест прошёл бы на коде, который ничего не спрашивал.
    assert auto_yes.titles, "очистка не спросила разрешение, а тест всё равно зелёный"


def test_confirmed_clearing_survives_retype(qtbot, config_manager, auto_yes):
    """Повторно введённый пароль не должен отменять подтверждённую очистку."""
    tab, cfg = _tab_with_config(qtbot, config_manager)

    tab._clear_ssh_passwords()
    tab.ssh_passwords.setPlainText("typo")
    tab.save(cfg)

    assert cfg.settings.connection.ssh_passwords_encrypted == []
    assert auto_yes.titles, "очистка не спросила разрешение"


def test_cancel_then_reopen_keeps_passwords(qtbot, config_manager, auto_yes):
    """Отмена, затем повторное открытие: очистка не должна «залипнуть»."""
    tab, cfg = _tab_with_config(qtbot, config_manager)

    tab._clear_ssh_passwords()
    # Отмена, потом диалог открыли заново
    tab.load(cfg)

    assert tab._ssh_passwords_cleared is False
    assert cfg.settings.connection.ssh_passwords_encrypted == ["pw1", "pw2"]


def test_db_cancel_keeps_passwords(qtbot, config_manager, auto_yes):
    tab, cfg = _tab_with_config(qtbot, config_manager)
    cfg.update("connection", db_passwords_encrypted=["dbpw"])
    tab.load(cfg)

    tab._clear_db_passwords()
    cfg.reload()

    assert cfg.settings.connection.db_passwords_encrypted == ["dbpw"]
    assert auto_yes.titles, "очистка паролей БД не спросила разрешение"


def test_empty_field_keeps_existing_passwords(qtbot, config_manager):
    """Пустое поле означает «не менять», а не «очистить»."""
    tab, cfg = _tab_with_config(qtbot, config_manager)
    tab.ssh_passwords.clear()

    tab.save(cfg)

    assert cfg.settings.connection.ssh_passwords_encrypted == ["pw1", "pw2"]


def test_typed_passwords_are_saved(qtbot, config_manager):
    tab, cfg = _tab_with_config(qtbot, config_manager, passwords=())
    tab.ssh_passwords.setPlainText("new1\nnew2")

    tab.save(cfg)

    from cashcontrol.core.security.encryption import decrypt_passwords

    stored = cfg.settings.connection.ssh_passwords_encrypted
    assert len(stored) == 2
    assert sorted(decrypt_passwords(stored)) == ["new1", "new2"]
