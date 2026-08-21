"""
Verify setup_db logic directly — no SSH/DB required.
"""
from __future__ import annotations

from cashcontrol.core.session import CashSession


def main():
    s = CashSession(host="172.18.105.43")

    # Before setup_db: db is None (lazy)
    assert s._db is None, "DB should not exist before first access"
    print("[1] _db is None on init — OK")

    # setup_db creates a DBSession with the specified database
    db = s.setup_db(database="sco_v3")
    assert s._db is db, "setup_db should return the same instance"
    print(f"[2] setup_db returned DBSession(host={db.host}, database={db.database}) — OK")
    assert db.database == "sco_v3", f"Expected sco_v3, got {db.database}"
    print("[3] database='sco_v3' — OK")

    # After setup_db, s.db returns the same session
    assert s.db is db, "s.db should be the same as setup_db return"
    print("[4] s.db returns the same DBSession — OK")

    # Changing database
    db2 = s.setup_db(database="cashregister")
    assert s._db is db2, "setup_db should replace _db with new database"
    assert db2.database == "cashregister"
    assert s.db is db2
    print(f"[5] Switching database: db={db2.database} — OK")

    print("\n✅ All checks passed — setup_db works correctly")


if __name__ == "__main__":
    main()
