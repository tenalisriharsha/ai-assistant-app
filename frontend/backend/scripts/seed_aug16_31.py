# scripts/seed_aug16_31.py
import sys
from pathlib import Path
# Ensure project root is importable when running from scripts/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import date, time, timedelta
from models import SessionLocal, Appointment, init_db
from sqlalchemy import and_

START = date(2025, 8, 16)
END   = date(2025, 8, 31)

def t(h, m=0, s=0): return time(h, m, s)

def add(session, d, s, e, desc, **extra):
    a = Appointment(
        date=d, start_time=s, end_time=e,
        description=desc,
        # If your model has these optional columns, you can set them:
        title=extra.get("title", desc),
        label=extra.get("label"),
        color=extra.get("color"),
        location=extra.get("location"),
        modality=extra.get("modality"),
        timezone=extra.get("timezone"),
        attendees=extra.get("attendees"),
        recurrence_rule=extra.get("recurrence_rule"),
        reminder_offset_min=extra.get("reminder_offset_min"),
        tentative=extra.get("tentative"),
        is_all_day=extra.get("is_all_day"),
        notes=extra.get("notes"),
        external_id=extra.get("external_id"),
    )
    session.add(a)

def main():
    # Ensure tables exist
    init_db()

    db = SessionLocal()
    try:
        # 1) Clear only the target range to avoid duplicates on re-run
        print(f"Clearing appointments between {START} and {END}…")
        db.query(Appointment).filter(
            and_(Appointment.date >= START, Appointment.date <= END)
        ).delete(synchronize_session=False)
        db.commit()

        # 2) Seed daily baseline + some special events
        d = START
        while d <= END:
            wk = d.weekday()  # 0=Mon … 5=Sat 6=Sun

            # Baseline blocks every day (including weekends)
            add(db, d, t(9),  t(10), "Morning stand-up")
            add(db, d, t(13), t(14), "Lunch break")
            add(db, d, t(16), t(17), "Wrap-up / Review")

            # Weekday extras
            if wk < 5:
                # Some variations over the period
                if d == date(2025, 8, 19):
                    add(db, d, t(15), t(16), "Dr. Smith follow-up", location="Clinic")
                if d == date(2025, 8, 20):
                    add(db, d, t(10, 30), t(11, 30), "Dentist", location="Dental Care")
                if d == date(2025, 8, 22):
                    # Intentional overlap for conflict testing
                    add(db, d, t(10), t(11), "Design review", modality="Zoom")
                    add(db, d, t(10, 30), t(11, 30), "Client sync", location="Room A")
                if d == date(2025, 8, 26):
                    add(db, d, t(15), t(16), "Project sync", modality="Zoom")
                if d == date(2025, 8, 28):
                    add(db, d, t(18, 30), t(19), "Call with John")
                if d == date(2025, 8, 29):
                    add(db, d, t(15), t(16, 30), "Team retrospective")

            db.commit()
            d += timedelta(days=1)

        # Count result
        total = db.query(Appointment).filter(
            and_(Appointment.date >= START, Appointment.date <= END)
        ).count()
        print(f"Seed complete. Inserted {total} rows in {START}..{END}.")
    finally:
        db.close()

if __name__ == "__main__":
    main()