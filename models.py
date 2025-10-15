# models.py
from __future__ import annotations

from pathlib import Path
from typing import List, Set

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Date,
    Time,
    String,
    Text,
    Boolean,
    DateTime,
    func,
    ForeignKey,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Use an absolute path so every module (and subfolder scripts) hit the same DB.
BASE_DIR = Path(__file__).resolve().parent
SQLALCHEMY_DATABASE_URL = f"sqlite:///{(BASE_DIR / 'appointments.db').as_posix()}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


class Appointment(Base):
    __tablename__ = "appointments"

    # --- Core fields ---
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False, index=True)
    end_time = Column(Time, nullable=False, index=True)
    description = Column(Text, nullable=True, index=True)

    # --- Optional fields (additive, nullable) ---
    title = Column(String(200), nullable=True, index=True)

    label = Column(String(50), nullable=True, index=True)
    color = Column(String(20), nullable=True)

    location = Column(String(200), nullable=True)
    modality = Column(String(50), nullable=True)     # 'zoom', 'in-person', etc.
    timezone = Column(String(50), nullable=True)     # e.g. 'America/Los_Angeles'
    attendees = Column(Text, nullable=True)          # comma/JSON list (your choice)

    recurrence_rule = Column(String(255), nullable=True)   # iCal RRULE
    reminder_offset_min = Column(Integer, nullable=True)   # minutes before start

    tentative = Column(Boolean, nullable=True, default=False)
    is_all_day = Column(Boolean, nullable=True, default=False)
    notes = Column(Text, nullable=True)

    external_id = Column(String(255), nullable=True, unique=False)
    created_at = Column(DateTime, nullable=True, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Appointment(id={self.id!r}, date={self.date!r}, "
            f"start={self.start_time!r}, end={self.end_time!r}, "
            f"title={self.title!r}, description={self.description!r})>"
        )

    def to_dict(self) -> dict:
        """Serialize to a plain dict (keeps your current API keys)."""
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "start_time": self.start_time.strftime("%H:%M:%S"),
            "end_time": self.end_time.strftime("%H:%M:%S"),
            "description": self.description,
            # optional fields
            "title": self.title,
            "label": self.label,
            "color": self.color,
            "location": self.location,
            "modality": self.modality,
            "timezone": self.timezone,
            "attendees": self.attendees,
            "recurrence_rule": self.recurrence_rule,
            "reminder_offset_min": self.reminder_offset_min,
            "tentative": self.tentative,
            "is_all_day": self.is_all_day,
            "notes": self.notes,
            "external_id": self.external_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    time = Column(Time, nullable=False, index=True)
    title = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)

    lead_minutes = Column(Integer, nullable=False, default=0)   # minutes before target (0 means exact time)
    channel = Column(String(50), nullable=False, default="inapp")  # inapp|email|sms|webhook
    active = Column(Boolean, nullable=False, default=True)
    delivered = Column(Boolean, nullable=False, default=False)

    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True)

    created_at = Column(DateTime, nullable=True, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    # Optional relationship back to Appointment
    appointment = relationship("Appointment", backref="reminders")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Reminder(id={self.id!r}, date={self.date!r}, time={self.time!r}, "
            f"title={self.title!r}, active={self.active!r}, delivered={self.delivered!r})>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "time": self.time.strftime("%H:%M:%S"),
            "title": self.title,
            "description": self.description,
            "lead_minutes": self.lead_minutes,
            "channel": self.channel,
            "active": self.active,
            "delivered": self.delivered,
            "appointment_id": self.appointment_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ----------------------------
# Utilities
# ----------------------------
def init_db() -> None:
    """
    Creates tables if they don't exist.
    This does not add new columns to existing tables (SQLite limitation),
    so use ensure_schema() below for additive schema upgrades.
    """
    Base.metadata.create_all(bind=engine)


def _existing_columns(engine: Engine, table_name: str) -> Set[str]:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table_name});").fetchall()
        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        return {r[1] for r in rows}


def ensure_schema() -> None:
    """
    Adds any new optional columns to the existing 'appointments' table if missing.
    Safe for SQLite; preserves data. Re-runnable (no-ops if already applied).
    """
    # Create any newly-declared tables (e.g., reminders) safely if missing.
    Base.metadata.create_all(bind=engine)

    cols = _existing_columns(engine, "appointments")
    to_add: List[str] = []

    desired = {
        "title": "TEXT",
        "label": "VARCHAR(50)",
        "color": "VARCHAR(20)",
        "location": "VARCHAR(200)",
        "modality": "VARCHAR(50)",
        "timezone": "VARCHAR(50)",
        "attendees": "TEXT",
        "recurrence_rule": "VARCHAR(255)",
        "reminder_offset_min": "INTEGER",
        "tentative": "BOOLEAN",
        "is_all_day": "BOOLEAN",
        "notes": "TEXT",
        "external_id": "VARCHAR(255)",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    }

    for name, ddl in desired.items():
        if name not in cols:
            to_add.append(f"ALTER TABLE appointments ADD COLUMN {name} {ddl};")

    if not to_add:
        return

    with engine.begin() as conn:
        for stmt in to_add:
            conn.exec_driver_sql(stmt)