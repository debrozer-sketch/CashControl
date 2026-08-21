"""
Verify setup_db(database="sco_v3") on a live SCO3 cash register.

Usage:
    python test_sco3_db.py <ip_address>

Example:
    python test_sco3_db.py 192.168.1.100
"""
from __future__ import annotations

import asyncio
import sys

from cashcontrol.core.session import CashSession


async def main(ip: str) -> None:
    session = CashSession(host=ip)

    print(f"[1] SSH connecting to {ip}...")
    await session.connect(connect_db=False)
    assert session.ssh_connected, "SSH failed — aborting"

    print("[2] Calling setup_db(database='sco_v3')...")
    db = session.setup_db(database="sco_v3")
    print(f"    DBSession(host={db.host}, port={db.port}, database={db.database})")

    print("[3] Connecting DB...")
    await session.db.connect()
    assert session.db_connected, "DB connection failed"
    print("    DB connected OK")

    print("[4] Running SELECT version()...")
    row = await session.db.execute_one("SELECT version()")
    pg_version = row[0] if row else "?"
    print(f"    PostgreSQL version: {pg_version}")

    print("[5] Checking current database...")
    row = await session.db.execute_one("SELECT current_database()")
    db_name = row[0] if row else "?"
    print(f"    Current database: {db_name}")
    assert db_name == "sco_v3", f"Expected sco_v3, got {db_name}"

    print("\n✅ All checks passed — setup_db works correctly for SCO3")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
