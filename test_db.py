"""
Тест подключения к Catalog БД через SSH + psql.

Использование:
    python test_db.py <IP> [--ssh-user <user>] [--ssh-pass <pass>] [--db-user <user>] [--db-pass <pass>]
"""

import argparse
import asyncio
import json
import sys

import asyncssh


def c(text: str) -> str:
    """Clean ANSI."""
    return text


async def run(conn, cmd: str, label: str = ""):
    """Run command and print result."""
    print(f"\n[{label}] {cmd}" if label else f"\n$ {cmd}")
    result = await conn.run(cmd, check=False)
    out = result.stdout.strip()
    err = result.stderr.strip()
    if out:
        for line in out.split("\n"):
            print(f"  > {line}")
    if err:
        for line in err.split("\n"):
            print(f"  ! {line}")
    print(f"  exit={result.returncode}")
    return result


async def test_db(
    ip: str,
    ssh_user: str,
    ssh_pass: str | None,
):
    print(f"\n{'='*60}")
    print(f"  Касса: {ip}")
    print(f"  SSH:   {ssh_user}@{ip}")
    print(f"  PG:    postgres@Catalog")
    print(f"{'='*60}")

    # 1. SSH
    print("\n---[1] SSH ---")
    try:
        kwargs = {"host": ip, "username": ssh_user, "known_hosts": None}
        if ssh_pass:
            kwargs["password"] = ssh_pass
        conn = await asyncssh.connect(**kwargs)
        print("  SSH: OK")
    except Exception as e:
        print(f"  SSH: {e}")
        return

    # 2. psql version
    await run(conn, "which psql && psql --version", label="2. psql")

    # 3. Попытка подключения разными способами
    print("\n---[3] Тест подключения к Catalog ---")

    # 3a. Без -U (попытка под текущим пользователем)
    await run(
        conn,
        "psql -d Catalog -c 'SELECT 1 AS test;' 2>&1 | head -5",
        label="3a. psql -d Catalog (без -U)",
    )

    # 3b. С -U postgres через Unix socket
    await run(
        conn,
        "psql -U postgres -d Catalog -c 'SELECT 1 AS test;' 2>&1 | head -5",
        label="3b. psql -U postgres -d Catalog (socket)",
    )

    # 3c. С -U через TCP (127.0.0.1) — без пароля
    await run(
        conn,
        "psql -U postgres -h 127.0.0.1 -d Catalog -c 'SELECT 1 AS test;' 2>&1 | head -5",
        label="3c. psql -U postgres -h 127.0.0.1 (TCP, без пароля)",
    )

    # 3d. sudo -u postgres
    await run(
        conn,
        "sudo -u postgres psql -d Catalog -c 'SELECT 1 AS test;' 2>&1 | head -5",
        label="3d. sudo -u postgres psql -d Catalog",
    )

    # 4. Ищем базу данных Catalog
    print("\n---[4] Проверка существования БД Catalog ---")
    r = await conn.run(
        "psql -U postgres -h 127.0.0.1 -d postgres -t -A -c \"SELECT 1 FROM pg_database WHERE datname = 'catalog';\" 2>&1",
        check=False,
    )
    has_catalog = r.stdout.strip() == "1"
    print(f"  БД 'catalog': {'ЕСТЬ' if has_catalog else 'НЕТ'}")

    # Если нет Catalog, ищем похожие
    if not has_catalog:
        r = await conn.run(
            "psql -U postgres -h 127.0.0.1 -d postgres -t -A -c \"SELECT datname FROM pg_database WHERE datname ILIKE '%cat%' OR datname ILIKE '%catalog%' ORDER BY datname;\" 2>&1",
            check=False,
        )
        similar = [l.strip() for l in r.stdout.strip().split("\n") if l.strip() and "FATAL" not in l]
        if similar:
            print(f"  Похожие БД: {', '.join(similar)}")
        else:
            print("  Похожие БД не найдены")

    # 5. Список БД (через postgres database, которая есть всегда)
    print(f"\n---[5] Список БД ---")
    r = await conn.run(
        "psql -U postgres -h 127.0.0.1 -d postgres -t -A -c \"SELECT datname FROM pg_database ORDER BY datname;\" 2>&1",
        check=False,
    )
    for line in r.stdout.strip().split("\n"):
        line = line.strip()
        if line and "does not exist" not in line and "FATAL" not in line:
            print(f"  {line}")

    if not has_catalog:
        # Если Catalog не нашлась — покажем схему из postgres БД
        print(f"\n---[6] Поиск таблицы sales_management_properties по всем БД ---")
        r = await conn.run(
            "psql -U postgres -h 127.0.0.1 -d postgres -t -A -c \"SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname;\" 2>&1",
            check=False,
        )
        all_dbs = [l.strip() for l in r.stdout.strip().split("\n") if l.strip() and "FATAL" not in l]
        print(f"  Все пользовательские БД: {all_dbs}")
        for db_name in all_dbs:
            r2 = await conn.run(
                f"psql -U postgres -h 127.0.0.1 -d {db_name} -t -A -c \"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'sales_management_properties');\" 2>&1",
                check=False,
            )
            exists = r2.stdout.strip() == "t"
            print(f"    {db_name}: таблица {'ЕСТЬ' if exists else 'НЕТ'}")
        conn.close()
        return

    # Если Catalog есть — работаем с ней
    db_name = "catalog"
    r = await conn.run(
        f"psql -U postgres -h 127.0.0.1 -d {db_name} -c \"\\d sales_management_properties\" 2>&1",
        check=False,
    )
    print(f"\n---[6] Описание таблицы ---")
    for line in r.stdout.strip().split("\n"):
        print(f"  {line}")

    # 7. Нужные ключи
    print(f"\n---[7] Поиск нужных ключей ---")
    target_keys = ["paymentTypeRanks", "retailOnlyDrawerClose"]
    for key in target_keys:
        r = await conn.run(
            f"psql -U postgres -h 127.0.0.1 -d {db_name} -t -A -c \"SELECT length(property_value), left(property_value, 300) FROM sales_management_properties WHERE property_key = '{key}';\" 2>&1",
            check=False,
        )
        raw = r.stdout.strip()
        if raw and "0 rows" not in raw and "does not exist" not in raw:
            parts = raw.split("\n")[0].split("|")
            length = parts[0].strip() if len(parts) > 0 else "?"
            val = parts[1] if len(parts) > 1 else raw
            print(f"  {key}: length={length}")
            print(f"    value={val[:200]}")
        else:
            print(f"  {key}: НЕ НАЙДЕН")

    # 8. Пять любых ключей для примера
    print(f"\n---[8] Примеры других ключей ---")
    r = await conn.run(
        f"psql -U postgres -h 127.0.0.1 -d {db_name} -t -A -c \"SELECT property_key, left(property_value, 80) FROM sales_management_properties ORDER BY property_key LIMIT 5;\" 2>&1",
        check=False,
    )
    for line in r.stdout.strip().split("\n"):
        if line.strip():
            print(f"  {line}")

    conn.close()
    print(f"\n{'='*60}")
    print("  Готово")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Тест подключения к Catalog БД")
    parser.add_argument("ip", help="IP кассы")
    parser.add_argument("--ssh-user", default="tc", help="SSH пользователь")
    parser.add_argument("--ssh-pass", help="SSH пароль")
    args = parser.parse_args()

    asyncio.run(
        test_db(args.ip, args.ssh_user, args.ssh_pass)
    )


if __name__ == "__main__":
    main()
