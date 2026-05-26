# database.py
from __future__ import annotations

from datetime import date, time
from typing import List

from sqlalchemy.orm import Session

from models import SessionLocal, init_db, ensure_schema, Appointment

# Ensure our tables exist and new columns are added if missing on import.
init_db()
ensure_schema()


def get_db() -> Session:
    """
    Provide a SQLAlchemy session.
    Caller is responsible for closing, or use context management.
    """
    return SessionLocal()


# Optional convenience helpers (kept for backward compatibility).
def get_appointments_by_date(db: Session, target_date: date) -> List[Appointment]:
    """Return all appointments scheduled on a specific date."""
    return (
        db.query(Appointment)
        .filter(Appointment.date == target_date)
        .order_by(Appointment.start_time)
        .all()
    )


def get_appointments_between(
    db: Session, target_date: date, start_time: time, end_time: time
) -> List[Appointment]:
    """Return all appointments between specific times on a given date."""
    return (
        db.query(Appointment)
        .filter(
            Appointment.date == target_date,
            Appointment.start_time >= start_time,
            Appointment.end_time <= end_time,
        )
        .order_by(Appointment.start_time)
        .all()
    )

from contextlib import contextmanager

@contextmanager
def db_session():
    db = get_db()
    try:
        yield db
    finally:
        db.close()