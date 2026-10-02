"""Перетаскивание файла на кассу, где нет SFTP-подсистемы.

Кассы «Тиникор» (TinyCore/dropbear) не отдают SFTP-подсистему:
``start_sftp_client()`` либо отклоняется, либо виснет. Плюс соединение
сессии к моменту перетаскивания уже исчерпано: сборщики данных открыли под
тридцать каналов, и новые перестают подтверждаться — в журнале это видно как
``Command timeout`` на ``test -e``.

Поэтому отправка идёт через файловый сервис на отдельном соединении, с
выбором транспорта и политикой переименования при конфликте.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from cashcontrol.gui.cash_session_widget import CashSessionWidget


def _src() -> str:
    return textwrap.dedent(inspect.getsource(CashSessionWidget._upload_to_cash))


def _connect_src() -> str:
    return textwrap.dedent(inspect.getsource(CashSessionWidget._connect_for_transfer))



def _widget():
    from PySide6.QtWidgets import QWidget

    w = CashSessionWidget.__new__(CashSessionWidget)
    QWidget.__init__(w)
    w._ip = "10.0.0.1"
    return w


def test_drop_upload_does_not_require_sftp():
    """Главная причина поломки: жёсткая привязка к SFTP."""
    src = _src()
    assert "SftpBackend" not in src, (
        "путь перетаскивания не должен требовать SFTP-подсистему"
    )
    assert "start_sftp_client" not in src, (
        "проба SFTP выполняется внутри фабрики транспорта"
    )


def test_drop_upload_selects_transport():
    assert "build_remote_backend" in _src(), (
        "транспорт выбирается: на «Тиникоре» SFTP нет, нужен shell и SCP"
    )


def test_drop_upload_uses_own_connection():
    """Сессионное соединение на «Тиникоре» к этому моменту не отвечает."""
    src = _src()
    assert "_connect_for_transfer" in src, (
        "нужно отдельное соединение, сессионное уже исчерпало каналы"
    )
    assert "ssh.execute(" not in src, (
        "команды нельзя слать в сессионное соединение: они там виснут"
    )
    assert "upload_file" not in src, (
        "перенос делает файловый сервис, а не примитив сессии"
    )


def test_connect_verifies_host_key():
    """Новое соединение обязано проверять ключ хоста."""
    src = _connect_src()
    assert "known_hosts" in src
    assert "default_known_hosts_path" in src


def test_connect_takes_password_from_successful_attempt():
    """Пароль берётся у сессии, а не из настроек наугад."""
    assert "successful_password" in _connect_src()


def test_connect_retries_because_tinycore_drops_bursts():
    """Без повторов второе перетаскивание подряд не проходит."""
    from cashcontrol.gui.cash_session_widget import TRANSFER_CONNECT_DELAYS

    assert len(TRANSFER_CONNECT_DELAYS) >= 2, "нужно больше одной попытки"
    assert TRANSFER_CONNECT_DELAYS[0] == 0.0, "первая попытка идёт без паузы"
    assert all(d > 0 for d in TRANSFER_CONNECT_DELAYS[1:]), "дальше нужен перерыв"
    assert tuple(sorted(TRANSFER_CONNECT_DELAYS)) == TRANSFER_CONNECT_DELAYS, (
        "паузы должны возрастать"
    )
    assert TRANSFER_CONNECT_DELAYS[-1] <= 10.0, "ждать дольше 10 с нельзя"


def test_connect_does_not_retry_on_bad_password():
    """Отказ в пароле повторять бессмысленно: пароль уже проверен сессией."""
    src = _connect_src()
    assert "PermissionDenied" not in src
    assert "asyncssh.Error" in src, "сетевые и протокольные сбои повторяем"


def test_drop_upload_closes_what_it_opened():
    """Открытое здесь соединение нужно закрыть, чужое — нет."""
    src = _src()
    assert "service.close()" in src
    assert "conn.close()" in src, "соединение осталось бы висеть на кассе"
    assert "wait_closed" in src


def test_drop_upload_keeps_rename_policy():
    """Файл на кассе нельзя затирать молча."""
    src = _src()
    assert "OverwritePolicy.RENAME" in src, (
        "фоновая отправка не может спросить о конфликте"
    )
    assert "OverwritePolicy.ASK" not in src


def _notices() -> dict[str, str]:
    """Уровень каждого ``feedback.notify`` по его текстовому куску.

    Разбор дерева, а не подстрока: ``"Level.SUCCESS" in src`` проверяла бы
    наличие имени где-то в файле и молчала бы при обмене уровней двух
    вызовов местами — оба имени остались бы в исходнике. Здесь уровень
    привязан к своему сообщению, поэтому смена уровня у конкретного
    вызова ломает проверку.

    Ключ — первый текстовый кусок f-строки, а не склейка всех кусков.
    Склейка оставляла двойной пробел на месте ``{total}``, и правка
    формулировки роняла бы тест сообщением про уровень, хотя уровень
    тут ни при чём.
    """
    tree = ast.parse(_src())
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "notify"
            and isinstance(func.value, ast.Name)
            and func.value.id == "feedback"
        ):
            continue
        message = node.args[0]
        level = node.args[1] if len(node.args) > 1 else None
        if isinstance(message, ast.Subscript):
            # Обрезка ``f"..."[:120]``: текст сообщения лежит внутри.
            message = message.value
        if not isinstance(message, ast.JoinedStr):
            continue
        head = next(
            (
                part.value
                for part in message.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            ),
            None,
        )
        if head is None:
            continue
        found[head] = (
            f"{level.value.id}.{level.attr}" if _is_level(level) else ast.dump(level)
        )
    return found


def _is_level(node: ast.AST | None) -> bool:
    """Член ``Level``, а не строка.

    Строка прошла бы через ``normalize_level`` и тихо показалась как info
    при опечатке: цвет не тот, в журнале не тот.
    """
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Level"
    )


def test_drop_upload_reports_outcome():
    """Итог отправки виден оператору, и уровень у каждого вызова свой.

    Проверяется не «в файле есть Level.SUCCESS», а соответствие уровня
    сообщению: обмен уровнями между двумя вызовами останется незамеченным
    при проверке по подстроке, потому что оба имени в файле останутся.

    Отсутствие уведомления и неверный уровень — разные падения: первое
    значит, что вызов пропал или переименован, второе — что перепутан
    уровень. Раньше оба случаи попадали в одно сообщение про уровень.
    """
    notices = _notices()
    expected = {
        ": нет подключения к кассе": "Level.ERROR",
        ": копирование на кассу — ": "Level.INFO",
        ": отправка не удалась — ": "Level.ERROR",
        ": отправлено файлов: ": "Level.SUCCESS",
        ": отправка завершилась с ошибкой": "Level.ERROR",
    }
    assert notices, f"в _upload_to_cash нет уведомлений: {_src()}"

    missing = sorted(msg for msg in expected if msg not in notices)
    wrong = {
        msg: (notices[msg], level)
        for msg, level in expected.items()
        if msg in notices and notices[msg] != level
    }
    assert not missing and not wrong, (
        f"уведомления в _upload_to_cash разошлись: нет {missing}, уровень не тот {wrong}"
    )
    assert "transferred_files" in _src(), "уведомление должно содержать счётчик файлов"


def test_drop_upload_checks_session_connected():
    assert 'getattr(ssh, "_conn", None) is None' in _src(), (
        "без сессии отправка невозможна, об этом нужно сказать"
    )
