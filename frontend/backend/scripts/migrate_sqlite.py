# scripts/migrate_sqlite.py
import os
import sqlite3

DB_PATH = os.environ.get("APPOINTMENTS_DB", "appointments.db")

DDL = [
    ("title", "TEXT", None),
    ("label", "TEXT", None),
    ("color", "TEXT", None),
    ("location", "TEXT", None),
    ("modality", "TEXT", None),
    ("timezone", "TEXT", None),
    ("attendees", "TEXT", None),
    ("recurrence_rule", "TEXT", None),
    ("reminder_offset_min", "INTEGER", None),
    ("tentative", "INTEGER", "0"),
    ("is_all_day", "INTEGER", "0"),
    ("notes", "TEXT", None),
    ("external_id", "TEXT", None),
    ("created_at", "TEXT", None),
    ("updated_at", "TEXT", None),
]

def main():
    if not os.path.exists(DB_PATH):
        print(f"[migrate] {DB_PATH} not found. Nothing to migrate.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Discover existing columns
    cur.execute("PRAGMA table_info(appointments)")
    existing = {row[1] for row in cur.fetchall()}

    # Add any missing columns
    added = []
    for col, typ, default in DDL:
        if col in existing:
            continue
        sql = f"ALTER TABLE appointments ADD COLUMN {col} {typ}"
        if default is not None:
            sql += f" DEFAULT {default}"
        cur.execute(sql)
        added.append(col)

    # Optionally seed timestamps for existing rows
    if "created_at" in (set(c for c, *_ in DDL) - existing):
        try:
            cur.execute("UPDATE appointments SET created_at = COALESCE(created_at, datetime('now'))")
        except Exception:
            pass
    if "updated_at" in (set(c for c, *_ in DDL) - existing):
        try:
            cur.execute("UPDATE appointments SET updated_at = COALESCE(updated_at, datetime('now'))")
        except Exception:
            pass

    conn.commit()
    conn.close()

    if added:
        print("[migrate] Added columns:", ", ".join(added))
    else:
        print("[migrate] No changes needed; schema already up to date.")

if __name__ == "__main__":
    main()