"""Чтение свойства из базы ``catalog`` через psql — общая часть для коллекторов.

Модуль не коллектор: его берут несколько сборщиков свойств, и дублировать
поиск клиента и разбор результата в двух местах нельзя. Расхождение между
копиями уже стоило поломки — один из сборщиков остался с зашитым
``/usr/bin/psql``, которого на боевой кассе нет.

Запрет на ``-f`` и ``\\i``
-------------------------
Команда проверки читает **одно** свойство и не пишет в базу. Флаг ``-f`` и
мета-команда ``\\i`` выполняют файл, и для файла, взятого с кассы, это уже не
проверка.

На боевой кассе ``172.17.185.1`` лежит ``/home/tc/storage/drawer.sql``:

    --Отключить проверку денежного ящика на кассе
    update sales_management_properties
       set property_value = 'false'
     where property_key = '<свойство кассы>';
    select * from sales_management_properties
     where property_key = '<свойство кассы>';

Это **процедура исправления**, а не проверка. Соблазн «упростить и выполнить
готовый файл с кассы» надо прямо назвать: так команда проверки станет командой
правки, и каждое обновление панели информации будет молча писать
``<свойство кассы>='false'`` в базу боевой кассы. Обновление панели
происходит само, по TTL кэша и по кнопке «Обновить», поэтому запись будет
происходить регулярно и без участия оператора, а отмена проверки денежного
ящика станет необратимой без доступа к базе. Проверка обязана оставаться
``SELECT``-ом: диагностика не имеет права менять то, что диагностирует.

Поэтому запрет закреплён не только тестом, но и в коде: ``assert_read_only``
вызывается при сборке команды и бросает ``ValueError``. Снять запрет можно
только вместе с тестом ``test_guard_catches_file_flag_and_write`` в
``tests/test_psql_collectors.py``, и то осознанно.

Сокет, потом TCP
---------------
Рабочая команда оператора на боевой кассе идёт без ``-h``, то есть через
unix-сокет, и postgres там может не слушать TCP вовсе. Поэтому сначала
пробуем сокет, и только если он не ответил — ``-h 127.0.0.1``.

Первая попытка отбрасывает stderr целиком (``2>/dev/null``). Иначе отказ
сокета, который на рабочей кассе норма, попал бы в лог и в раздел «Проблемы»
как ошибка проверки. Признак перехода на TCP — метка в stderr
``CASHCONTROL_PSQL_SOCKET_MISS``; на успешном результате она игнорируется, а на
неуспешном превращается в честное уточнение «проверены оба подключения».
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "PSQL_NOT_FOUND_ERROR",
    "PSQL_NOT_FOUND_MARKER",
    "PSQL_SOCKET_MISS_MARKER",
    "TCP_HOST",
    "assert_read_only",
    "build_read_command",
    "build_write_batch_command",
    "build_write_command",
    "clean_error",
    "interpret",
    "key_not_found_error",
    "read_only_violation",
    "read_value",
    "used_tcp_fallback",
]

# Признаки, которые ставит сама команда. Слова в stderr не хватает: нужен
# признак, который не может выдать сам psql.
PSQL_NOT_FOUND_MARKER = "CASHCONTROL_PSQL_NOT_FOUND"
PSQL_SOCKET_MISS_MARKER = "CASHCONTROL_PSQL_SOCKET_MISS"

TCP_HOST = "127.0.0.1"

# Инструмента нет: оператор должен знать, что проверка не выполнялась, и видеть,
# где искать. Про «не удалось получить данные из БД» он уже знает и не может из
# этого текста понять, что чинить.
PSQL_NOT_FOUND_ERROR = (
    "psql не найден на кассе: нет в PATH и в /usr/local/bin, /usr/bin, "
    "/usr/local/pgsql/bin, /opt/postgresql/*/bin. Проверка не выполнялась"
)

# Оба подключения не сработали — это уже не «не тот способ», а отказ postgres.
# Без этой оговорки оператор ищет проблему в сокете вместо базы.
BOTH_TRANSPORTS_NOTE = "проверены оба подключения: unix-сокет и 127.0.0.1"

_ERROR_MAX_LEN = 200

# Ключ подставляется в SQL, поэтому ограничен алфавитом таблицы. Кавычка или
# пробел в ключе сломали бы и SQL, и командную строку, а «молчащий» сломанный
# запрос хуже явного отказа.
_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")
# Значение property_value попадает внутрь SQL, а SQL — внутрь строки в
# двойных кавычках оболочки. Символы `$`, backtick, `"` и `\` способны
# вырваться наружу, поэтому допускается только безопасный набор.
_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")

# Поиск клиента: сначала PATH, потом типовые каталоги. Порядок тот же, что у
# x11vnc в builtin/vnc/vnc_preview.py:101-110. ls вызывается с 2>/dev/null —
# нераскрывшийся глоб /opt/postgresql/*/bin/psql печатает в stderr шум, который
# ошибкой psql не является, а head -1 оставляет одну строку.
_PSQL_SEARCH = (
    "PSQL=$(command -v psql 2>/dev/null || "
    "ls /usr/local/bin/psql /usr/bin/psql /usr/local/pgsql/bin/psql "
    "/opt/postgresql/*/bin/psql 2>/dev/null | head -1); "
    '[ -z "$PSQL" ] && { echo "' + PSQL_NOT_FOUND_MARKER + '" >&2; exit 127; }; '
)

# -f и --file читают файл целиком; \i делает то же внутри -c. Проверка обязана
# остаться SELECT-ом, поэтому оба способа запрещены (см. докстринг модуля).
_FILE_FLAG_RE = re.compile(r"(?<![-\w])--?(?:f|file)(?![-\w-])")
_FILE_META_RE = re.compile(r"\\i(?:r|nnclude)?(?![a-z])", re.IGNORECASE)
_WRITE_RE = re.compile(
    r"\b(?:update|insert|delete|drop|alter|truncate|create|grant)\b",
    re.IGNORECASE,
)

_READ_ONLY_BAN = (
    "команда проверки обязана остаться чтением, найдено {found}. "
    "Файлы с кассы вроде /home/tc/storage/drawer.sql — это процедура "
    "исправления (внутри UPDATE), их выполнение писало бы в базу боевой кассы "
    "при каждом обновлении панели. Смотри докстринг _psql.py"
)


def read_only_violation(command: str) -> str | None:
    """Вернуть описание нарушения, если команда не только читает.

    ``None`` означает, что команда прошла проверку.
    """
    found: list[str] = []
    if _FILE_FLAG_RE.search(command):
        found.append("флаг -f/--file (выполнение файла)")
    if _FILE_META_RE.search(command):
        found.append("мета-команда \\i (выполнение файла)")
    if _WRITE_RE.search(command):
        found.append("операция записи в БД")
    if not found:
        return None
    return _READ_ONLY_BAN.format(found=", ".join(found))


def assert_read_only(command: str) -> None:
    """Отказать собирать или отправлять команду, которая не только читает.

    Вызывается при сборке команды, поэтому запрет держится и когда в код
    полезут не тесты, а другой код.
    """
    violation = read_only_violation(command)
    if violation is not None:
        raise ValueError(violation)


def build_write_command(property_key: str, value: str) -> str:
    """Собрать команду точечной записи одного свойства в ``catalog``.

    Пишущая половинка ``psql``. Значение нельзя пропускать «как есть»: оно
    попадает внутрь SQL, а SQL — внутрь строки в двойных кавычках оболочки,
    поэтому ``$``, backtick, кавычка и обратный слэш вырвались бы наружу и
    выполнили произвольную команду. Здесь принимается только безопасный
    набор символов; конкретный набор значений (например, ``true``/``false``)
    проверяет уже исправление — этот уровень отвечает за экранирование, а не
    за смысл.

    Ключ берётся фиксированный, а не из ввода оператора, и проверяется так же,
    как при чтении.
    """
    if not _KEY_RE.match(property_key):
        raise ValueError(
            f"ключ свойства {property_key!r} недопустим: ожидаются буквы, "
            "цифры и подчёркивание"
        )
    if not _VALUE_RE.match(value):
        raise ValueError(
            f"значение {value!r} недопустимо: ожидаются буквы, цифры и знаки "
            "._:- длиной до 200 символов"
        )
    sql = (
        "UPDATE sales_management_properties "
        f"SET property_value = '{value}' "
        f"WHERE property_key = '{property_key}' "
        f"AND property_value IS DISTINCT FROM '{value}';"
    )
    return _PSQL_SEARCH + _invoke(sql, None)


async def read_value(session, property_key: str) -> str | None:
    """Прочитать свойство и вернуть значение, либо ``None`` при неудаче."""
    result = await session.exec(build_read_command(property_key))
    value, _ = interpret(result, property_key)
    return value


def build_write_batch_command(values: dict[str, str]) -> str:
    """Собрать запись нескольких свойств одной транзакцией.

    Отдельная команда на каждый ключ опасна: первая запись прошла, вторая
    нет — а касса осталась в промежуточном состоянии, и ни одна из двух
    команд об этом не сообщает. ``BEGIN``/``COMMIT`` делают пару ключей
    одной неделимой операцией.

    Пустой словарь отвергается: команда без единого UPDATE была бы тихим
    успехом.
    """
    if not values:
        raise ValueError("нечего записывать: не передан ни один ключ")
    parts = []
    for property_key, value in values.items():
        if not _KEY_RE.match(property_key):
            raise ValueError(
                f"ключ свойства {property_key!r} недопустим: ожидаются буквы, "
                "цифры и подчёркивание"
            )
        if not _VALUE_RE.match(value):
            raise ValueError(
                f"значение {value!r} недопустимo: ожидаются буквы, цифры и знаки "
                "._:- длиной до 200 символов"
            )
        parts.append(
            "UPDATE sales_management_properties "
            f"SET property_value = '{value}' "
            f"WHERE property_key = '{property_key}' "
            f"AND property_value IS DISTINCT FROM '{value}';"
        )
    sql = "BEGIN; " + " ".join(parts) + " COMMIT;"
    return _PSQL_SEARCH + _invoke(sql, None)


def key_not_found_error(property_key: str) -> str:
    """Текст для случая «psql отработал, а ключа в таблице нет»."""
    return f"{property_key} не найдена"


def _query(property_key: str) -> str:
    if not _KEY_RE.match(property_key):
        raise ValueError(
            f"ключ свойства {property_key!r} недопустим: ожидаются буквы, "
            "цифры и подчёркивание"
        )
    return (
        "SELECT property_value FROM sales_management_properties "
        f"WHERE property_key = '{property_key}';"
    )


def _invoke(sql: str, host: str | None) -> str:
    """Один запуск psql: с хостом или через unix-сокет."""
    host_arg = f"-h {host} " if host else ""
    return f'"$PSQL" -U postgres {host_arg}-d catalog -t -A -c "{sql}"'


def build_read_command(property_key: str) -> str:
    """Собрать команду чтения одного свойства из ``catalog``.

    Сокет, потом ``-h 127.0.0.1``. Первая попытка глушит stderr, вторая при
    неудаче печатает текст psql в stderr и возвращает его код. ``-f`` и запись
    в БД запрещены, проверка выполняется на готовой строке.
    """
    sql = _query(property_key)
    socket_run = _invoke(sql, None)
    tcp_run = _invoke(sql, TCP_HOST)
    command = (
        _PSQL_SEARCH
        # Попытка через сокет. stderr выброшен: отказ сокета на кассе без
        # TCP-слушателя — норма, а не ошибка проверки.
        + f"OUT=$({socket_run} 2>/dev/null); RC=$?; "
        + 'if [ "$RC" -ne 0 ]; then '
        # Метка перехода: по ней видно, что сокет не ответил. На успехе её
        # игнорирует interpret, на отказе она превращается в уточнение.
        + f'echo "{PSQL_SOCKET_MISS_MARKER}" >&2; '
        + f"OUT=$({tcp_run} 2>/dev/null); RC=$?; "
        + 'if [ "$RC" -ne 0 ]; then '
        # Текст ошибки получаем третьим запуском, stdout в никуда. Слияние
        # stderr со stdout (2>&1) портило бы значение, если psql напишет в
        # stderr при успехе, поэтому так не делаем.
        + f"{tcp_run} 1>/dev/null; exit $?; "
        + "fi; fi; "
        + "printf '%s\\n' \"$OUT\""
    )
    assert_read_only(command)
    return command


def clean_error(stderr: str, exit_code: int) -> str:
    """Свести текст ошибки к одной строке и обрезать.

    Поле «Проблемы» однострочное, а psql на многострочных ошибках (нет
    сокета, нет базы) отдаёт перевод строки за переводом строки. Собственные
    метки команды вырезаются: оператору нужен текст psql, а не наш служебный
    токен.
    """
    text = stderr
    for marker in (PSQL_NOT_FOUND_MARKER, PSQL_SOCKET_MISS_MARKER):
        text = text.replace(marker, " ")
    text = " ".join(text.split())
    if not text:
        return f"psql завершился с кодом {exit_code}"
    if len(text) > _ERROR_MAX_LEN:
        return text[:_ERROR_MAX_LEN] + "…"
    return text


def used_tcp_fallback(result: Any) -> bool:
    """Сработал ли переход с unix-сокета на ``-h 127.0.0.1``.

    Служебная отметка для журнала и для тестов: по ней видно, что сокет на
    кассе не отвечает, даже когда проверка прошла. В раздел «Проблемы» она не
    попадает — успешная проверка проблемой не является.
    """
    return PSQL_SOCKET_MISS_MARKER in (getattr(result, "stderr", "") or "")


def interpret(result: Any, property_key: str) -> tuple[str | None, str | None]:
    """Разобрать результат команды в пару (значение, ошибка).

    Вынесено отдельно от ``collect``, чтобы исходы различались без SSH:
    значение / нет psql / нет ключа / прочая ошибка — четыре разных
    результата, и спутать их здесь нельзя.
    """
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()

    # Метка в stderr плюс ненулевой код возврата из команды. По метке, а не по
    # коду: 127 даёт и exec с негодным файлом, и это «прочая ошибка».
    if PSQL_NOT_FOUND_MARKER in stderr:
        return None, PSQL_NOT_FOUND_ERROR

    # Код возврата, а не поиск слова «error» в stderr: «not found» слова error
    # не содержит, и ошибка инструмента выглядела как отсутствие ключа.
    if result.exit_code != 0:
        text = clean_error(stderr, result.exit_code)
        if PSQL_SOCKET_MISS_MARKER in stderr:
            text = f"{text} ({BOTH_TRANSPORTS_NOTE})"
        return None, text

    if stdout and "row" not in stdout.lower():
        return stdout, None

    return None, key_not_found_error(property_key)
