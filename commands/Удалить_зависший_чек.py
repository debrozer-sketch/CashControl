# [command]
# name        = Удалить_зависший_чек
# description = Delete stuck receipt from database
# category    = user
# timeout     = 30

async def execute(session, **kwargs):
    from cashcontrol.core.db import DBSession

    db = DBSession(session.host, database="cash")
    try:
        await db.connect()

        rows = await db.execute(
            "SELECT * FROM public.ch_purchase ORDER BY id DESC LIMIT 1"
        )

        if not rows:
            return "Table ch_purchase is empty"

        row = rows[0]
        purchase_id = row["id"]
        datecommit = row["datecommit"]

        if datecommit is not None:
            return (
                f"No stuck receipts found\n"
                f"  Last receipt ID {purchase_id} closed: {datecommit}"
            )

        lines = [
            f"Stuck receipt found",
            f"{'-' * 40}",
        ]
        for key in row.keys():
            val = row[key]
            lines.append(f"  {key:<30} {val if val is not None else '\u2014'}")
        lines.append(f"{'-' * 40}")
        info_text = "\n".join(lines)

        from PySide6.QtWidgets import QMessageBox, QApplication
        msg = QMessageBox(QApplication.activeWindow())
        msg.setWindowTitle("Delete stuck receipt?")
        msg.setText(f"Stuck receipt ID {purchase_id} found.\n\nDelete permanently?")
        msg.setDetailedText(info_text)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.button(QMessageBox.StandardButton.Yes).setText("Yes, delete")
        msg.button(QMessageBox.StandardButton.No).setText("No, cancel")
        reply = msg.exec()

        if reply != QMessageBox.StandardButton.Yes:
            return info_text + "\n\nDeletion cancelled"

        await db.execute(
            "DELETE FROM public.ch_purchase WHERE id = $1",
            purchase_id,
        )

        return info_text + f"\n\nReceipt ID {purchase_id} deleted"

    except Exception as e:
        return f"Error: {e}"
    finally:
        try:
            await db.disconnect()
        except Exception:
            pass