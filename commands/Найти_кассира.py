# [command]
# name        = Найти_кассира
# description = Найти кассира по табельному номеру
# category    = user
# timeout     = 30

INPUT_PROMPT = "Enter cashier employee number:"

async def execute(session, **kwargs):
    tab_num = kwargs.get("user_input", "").strip()
    if not tab_num:
        return "Cancelled"
    if not tab_num.isdigit():
        return "Error: employee number must contain only digits"

    cash_type = getattr(session, "cash_type", "") or ""
    db_name = "sco_v3" if cash_type == "sco3" else "user"

    from cashcontrol.core.db import DBSession
    db = DBSession(session.host, database=db_name)
    try:
        await db.connect()
        rows = await db.execute(
            "SELECT COUNT(*) AS cnt FROM public.us_user WHERE tab_num = $1::text",
            tab_num,
        )
        count = rows[0]["cnt"] if rows else 0
        if count > 0:
            return f"Cashier with number {tab_num} found"
        else:
            return f"Cashier with number {tab_num} not found"
    except Exception as e:
        return f"DB connection error ({db_name}): {e}"
    finally:
        try:
            await db.disconnect()
        except Exception:
            pass