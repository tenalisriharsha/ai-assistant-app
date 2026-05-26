# handlers/appointments.py
from datetime import datetime, date, time, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from models import Appointment

def get_appointments_on(db: Session, target_date: date):
    return db.query(Appointment).filter(Appointment.date == target_date).all()

def get_appointments_between_times(db: Session, start: time, end: time, target_date: date):
    return (
        db.query(Appointment)
        .filter(
            Appointment.date == target_date,
            Appointment.start_time >= start,
            Appointment.end_time <= end,
        )
        .all()
    )

def get_appointments_today(db: Session):
    today = date.today()
    return get_appointments_on(db, today)

def get_appointments_this_week(db: Session):
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())  # Monday
    end_of_week = start_of_week + timedelta(days=6)
    return (
        db.query(Appointment)
        .filter(Appointment.date.between(start_of_week, end_of_week))
        .all()
    )

def get_appointments_after_time(db: Session, after: time, target_date: date = None):
    target_date = target_date or date.today()
    return (
        db.query(Appointment)
        .filter(
            Appointment.date == target_date,
            Appointment.start_time >= after,
        )
        .all()
    )

def count_appointments_in_month(db: Session, year: int, month: int):
    return (
        db.query(func.count(Appointment.id))
        .filter(
            func.strftime("%Y", Appointment.date) == str(year),
            func.strftime("%m", Appointment.date) == f"{month:02}",
        )
        .scalar()
    )

def find_keyword(db: Session, keyword: str):
    return (
        db.query(Appointment)
        .filter(Appointment.description.ilike(f"%{keyword}%"))
        .all()
    )

def get_next_appointment(db: Session):
    now = datetime.now()
    today = now.date()
    current_time = now.time()
    return (
        db.query(Appointment)
        .filter(
            or_(
              and_(Appointment.date == today, Appointment.start_time > current_time),
              Appointment.date > today
            )
        )
        .order_by(Appointment.date, Appointment.start_time)
        .first()
    )

def get_weekend_appointments(db: Session, year: int, month: int):
    # Saturday is 5, Sunday is 6
    return (
        db.query(Appointment)
        .filter(
            func.strftime("%Y", Appointment.date) == str(year),
            func.strftime("%m", Appointment.date) == f"{month:02}",
            func.strftime("%w", Appointment.date).in_(["0", "6"])
        )
        .all()
    )

def find_conflicts(db: Session, target_date: date):
    """
    Return any pairs of appointments on target_date whose times overlap.
    """
    appts = get_appointments_on(db, target_date)
    conflicts = []
    for i, a in enumerate(appts):
        for b in appts[i + 1 :]:
            if not (a.end_time <= b.start_time or b.end_time <= a.start_time):
                conflicts.append((a, b))
    return conflicts