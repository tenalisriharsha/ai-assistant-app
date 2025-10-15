# crud.py

from datetime import date as _date, time as _time, timedelta, datetime as _dt
from calendar import monthrange
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, and_

from models import Appointment, Reminder
from difflib import SequenceMatcher
import difflib
import re


# ------------------------
# Core fetch by id
# ------------------------

def get_appointment_by_id(db: Session, appt_id: int) -> Optional[Appointment]:
    """Fetch a single appointment by primary key."""
    return db.query(Appointment).get(appt_id)


# ------------------------
# Existing READ operations
# ------------------------

def get_appointments_by_date(db: Session, target_date: _date) -> List[Appointment]:
    """Return all appointments on a given date."""
    return (
        db.query(Appointment)
        .filter(Appointment.date == target_date)
        .order_by(Appointment.start_time)
        .all()
    )


def get_day_appointments_sorted(db: Session, target_date: _date) -> List[Appointment]:
    """Alias/helper: explicitly named 'sorted' for planners."""
    return get_appointments_by_date(db, target_date)


def get_appointments_for_week(db: Session, week_start: _date, week_end: _date) -> List[Appointment]:
    """Return all appointments between week_start and week_end (inclusive)."""
    return (
        db.query(Appointment)
        .filter(Appointment.date.between(week_start, week_end))
        .order_by(Appointment.date, Appointment.start_time)
        .all()
    )


def get_appointments_in_range(db: Session, start_date: _date, end_date: _date) -> List[Appointment]:
    """Generic range fetch, inclusive."""
    return (
        db.query(Appointment)
        .filter(Appointment.date.between(start_date, end_date))
        .order_by(Appointment.date, Appointment.start_time)
        .all()
    )


def get_appointments_between(db: Session, target_date: _date, start: _time, end: _time) -> List[Appointment]:
    """Return all appointments on target_date whose time window falls between start and end."""
    return (
        db.query(Appointment)
        .filter(
            Appointment.date == target_date,
            Appointment.start_time >= start,
            Appointment.end_time <= end,
        )
        .order_by(Appointment.start_time)
        .all()
    )


def get_next_appointment(db: Session, today: _date) -> Optional[Appointment]:
    """Return the next upcoming appointment on or after today."""
    return (
        db.query(Appointment)
        .filter(Appointment.date >= today)
        .order_by(Appointment.date, Appointment.start_time)
        .first()
    )


def search_appointments_by_description(db: Session, term: str) -> List[Appointment]:
    """
    Return appointments whose description matches `term` using case-insensitive
    substring OR >=60% fuzzy similarity (default). Delegates to find_appointments
    so the behavior is centralized.
    """
    return find_appointments(db, term=term, case_insensitive=True, min_ratio=0.60)


def get_appointments_on_weekends(db: Session, year: int, month: int) -> List[Appointment]:
    """
    Return all appointments in the given month that fall on a weekend (Saturday or Sunday).
    """
    start_date_ = _date(year, month, 1)
    last_day = monthrange(year, month)[1]
    end_date_ = _date(year, month, last_day)

    all_appts = (
        db.query(Appointment)
        .filter(Appointment.date.between(start_date_, end_date_))
        .order_by(Appointment.date, Appointment.start_time)
        .all()
    )
    return [a for a in all_appts if a.date.isoweekday() in (6, 7)]


def get_appointments_after_time(db: Session, target_date: _date, threshold: _time) -> List[Appointment]:
    """
    Return all appointments on target_date that start at or after the given threshold time.
    """
    return (
        db.query(Appointment)
        .filter(
            Appointment.date == target_date,
            Appointment.start_time >= threshold,
        )
        .order_by(Appointment.start_time)
        .all()
    )


def count_appointments_in_month(db: Session, start_date: _date, end_date: _date) -> int:
    """
    Count the total number of appointments within the given date range (inclusive).
    """
    return (
        db.query(Appointment)
        .filter(Appointment.date.between(start_date, end_date))
        .count()
    )


# alias for backwards compatibility
def count_appointments_in_range(db: Session, start_date: _date, end_date: _date) -> int:
    """Inclusive count using SQL COUNT for performance (kept name for legacy callers)."""
    return int(
        db.query(func.count(Appointment.id))
        .filter(Appointment.date.between(start_date, end_date))
        .scalar() or 0
    )


def get_conflicting_appointments(db: Session, target_date: _date):
    """
    Find all pairs of appointments on target_date whose time ranges overlap.
    Returns a list of tuples: [(appt1, appt2), ...].
    """
    appts = (
        db.query(Appointment)
        .filter(Appointment.date == target_date)
        .order_by(Appointment.start_time)
        .all()
    )
    conflicts = []
    for i in range(len(appts)):
        for j in range(i + 1, len(appts)):
            a, b = appts[i], appts[j]
            # overlap if a starts before b ends AND b starts before a ends
            if a.start_time < b.end_time and b.start_time < a.end_time:
                conflicts.append((a, b))
    return conflicts


# ------------------------
# NEW WRITE operations
# ------------------------

def _overlaps(a_start: _time, a_end: _time, b_start: _time, b_end: _time) -> bool:
    """True if [a_start, a_end) overlaps [b_start, b_end)."""
    return (a_start < b_end) and (b_start < a_end)


def find_conflicts_for_slot(db: Session, target_date: _date, start_t: _time, end_t: _time) -> List[Appointment]:
    """Return appointments on target_date that would conflict with the proposed slot."""
    day_appts = get_appointments_by_date(db, target_date)
    return [a for a in day_appts if _overlaps(start_t, end_t, a.start_time, a.end_time)]


def create_appointment(
    db: Session,
    date_: _date,
    start_time_: _time,
    end_time_: _time,
    description_: str,
    allow_overlap: bool = False,
    **kwargs,
) -> Appointment:
    """
    Create and persist a single appointment.
    If allow_overlap=False, raises ValueError on conflict.
    """
    if not allow_overlap:
        conflicts = find_conflicts_for_slot(db, date_, start_time_, end_time_)
        if conflicts:
            raise ValueError("Time slot conflicts with existing appointments")

    # Drop any unsupported keys accidentally passed in (like 'query')
    safe_kwargs = {k: v for k, v in kwargs.items() if k in Appointment.__table__.columns}

    appt = Appointment(
        date=date_,
        start_time=start_time_,
        end_time=end_time_,
        description=description_,
        **safe_kwargs
    )
    # Keep title in sync if not explicitly provided
    try:
        if getattr(appt, "title", None) in (None, ""):
            appt.title = description_ or ""
    except Exception:
        # if the model has no title column, ignore
        pass
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


def create_appointment_if_free(
    db: Session,
    date_: _date,
    start_time_: _time,
    end_time_: _time,
    description_: str,
) -> Tuple[Optional[Appointment], List[Appointment]]:
    """
    Try to create an appointment only if the time is free.
    Returns (created_appt_or_None, conflicting_appts_list)
    """
    conflicts = find_conflicts_for_slot(db, date_, start_time_, end_time_)
    if conflicts:
        return None, conflicts
    appt = create_appointment(db, date_, start_time_, end_time_, description_, allow_overlap=True)
    return appt, []


def bulk_create_appointments(
    db: Session,
    entries: List[dict],
    allow_overlap: bool = False,
) -> List[Appointment]:
    """
    Bulk-create many appointments.
    Each entry dict must have: date, start_time, end_time, description.
    If allow_overlap=False, any detected conflict raises ValueError (no partial commit).
    """
    to_create: List[Appointment] = []
    # Pre-check conflicts if not allowing overlap
    if not allow_overlap:
        for e in entries:
            d, s, e_t, desc = e["date"], e["start_time"], e["end_time"], e.get("description", "")
            conflicts = find_conflicts_for_slot(db, d, s, e_t)
            if conflicts:
                raise ValueError(f"Conflict when creating '{desc}' on {d} {s}-{e_t}")

    # Create
    for e in entries:
        appt = Appointment(
            date=e["date"],
            start_time=e["start_time"],
            end_time=e["end_time"],
            description=e.get("description", ""),
            title=(e.get("description", "") or ""),
        )
        db.add(appt)
        to_create.append(appt)
    db.commit()
    for a in to_create:
        db.refresh(a)
    return to_create


# ------------------------
# Lenient bulk/single create (skip conflicts)
# ------------------------

from typing import Optional

def bulk_create_appointments_lenient(
    db: Session,
    entries: List[dict],
) -> Tuple[List[Appointment], List[dict]]:
    """
    Create many appointments but skip conflicting ones instead of failing the whole batch.
    Returns (created_appointments, skipped_conflicts) where each skipped item is:
       {
          "date": date,
          "start_time": time,
          "end_time": time,
          "description": str,
          "conflicts": [Appointment, ...]
       }
    """
    created: List[Appointment] = []
    skipped: List[dict] = []

    allowed_cols = set(getattr(Appointment.__table__, "columns").keys())

    for e in entries:
        d = e["date"]
        s = e["start_time"]
        t = e["end_time"]
        desc = e.get("description", "") or ""

        # conflict check
        conflicts = find_conflicts_for_slot(db, d, s, t)
        if conflicts:
            skipped.append({
                "date": d,
                "start_time": s,
                "end_time": t,
                "description": desc,
                "conflicts": conflicts,
            })
            continue

        payload = {k: v for k, v in e.items() if k in allowed_cols}
        payload.setdefault("description", desc)
        # default title mirrors description when present
        if "title" in allowed_cols:
            payload.setdefault("title", payload.get("description", ""))

        appt = Appointment(**payload)
        db.add(appt)
        created.append(appt)

    db.commit()
    for a in created:
        db.refresh(a)
    return created, skipped


def create_appointment_lenient(
    db: Session,
    *,
    date_: _date,
    start_time_: _time,
    end_time_: _time,
    description_: str,
    **kwargs,
) -> Tuple[Optional[Appointment], Optional[dict]]:
    """
    Create one appointment if free; otherwise return a skipped_conflict dict.
    Returns (created_or_None, skipped_dict_or_None)
    """
    conflicts = find_conflicts_for_slot(db, date_, start_time_, end_time_)
    if conflicts:
        return None, {
            "date": date_,
            "start_time": start_time_,
            "end_time": end_time_,
            "description": description_ or "",
            "conflicts": conflicts,
        }
    appt = create_appointment(
        db,
        date_,
        start_time_,
        end_time_,
        description_,
        allow_overlap=True,
        **kwargs,
    )
    return appt, None


def update_appointment(
    db: Session,
    appt_id: int,
    *,
    date_: Optional[_date] = None,
    start_time_: Optional[_time] = None,
    end_time_: Optional[_time] = None,
    description_: Optional[str] = None,
    allow_overlap: bool = False,
    query=None,
    **kw,
) -> Optional[Appointment]:
    """
    Update fields of an appointment. If allow_overlap=False, checks conflicts.
    Accepts common alias names (date, start_time, end_time, description) via **kw
    for extra robustness.
    Returns updated Appointment or None if not found.
    """
    # Normalize alias names if provided
    if date_ is None and "date" in kw:
        date_ = kw["date"]
    if start_time_ is None and "start_time" in kw:
        start_time_ = kw["start_time"]
    if end_time_ is None and "end_time" in kw:
        end_time_ = kw["end_time"]
    if description_ is None and "description" in kw:
        description_ = kw["description"]

    appt = db.query(Appointment).get(appt_id)
    if not appt:
        return None

    new_date = date_ if date_ is not None else appt.date
    new_start = start_time_ if start_time_ is not None else appt.start_time
    new_end = end_time_ if end_time_ is not None else appt.end_time

    if not allow_overlap:
        conflicts = [
            a for a in get_appointments_by_date(db, new_date)
            if a.id != appt_id and _overlaps(new_start, new_end, a.start_time, a.end_time)
        ]
        if conflicts:
            raise ValueError("Updated time slot conflicts with existing appointments")

    # Apply changes in place
    if date_ is not None:
        appt.date = date_
    if start_time_ is not None:
        appt.start_time = start_time_
    if end_time_ is not None:
        appt.end_time = end_time_
    if description_ is not None:
        appt.description = description_
        appt.title = description_  # keep title synchronized
    appt.query = query or appt.query

    db.commit()
    db.refresh(appt)
    return appt


def update_appointment_time(
    db: Session,
    appt_id: int,
    *,
    date_: Optional[_date] = None,
    start_time_: Optional[_time] = None,
    end_time_: Optional[_time] = None,
    allow_overlap: bool = False,
    **kw,
) -> Optional[Appointment]:
    """
    Alias for updating only the date/time fields of an appointment.
    Mirrors `update_appointment` but accepts alias kw names (date, start_time, end_time).
    """
    # Accept alias names via **kw for robustness
    if date_ is None and "date" in kw:
        date_ = kw["date"]
    if start_time_ is None and "start_time" in kw:
        start_time_ = kw["start_time"]
    if end_time_ is None and "end_time" in kw:
        end_time_ = kw["end_time"]

    return update_appointment(
        db,
        appt_id,
        date_=date_,
        start_time_=start_time_,
        end_time_=end_time_,
        allow_overlap=allow_overlap,
    )


def update_appointment_title(
    db: Session,
    appt_id: int,
    title: str,
) -> Optional[Appointment]:
    """Convenience alias to rename an appointment."""
    return update_appointment(
        db,
        appt_id,
        description_=title,
        allow_overlap=True,  # title-only changes never cause time conflicts
    )


def reschedule_appointment(
    db: Session,
    appt_id: int,
    to_date: _date,
    start_time_: _time,
    end_time_: _time,
    *,
    allow_overlap: bool = False,
) -> Optional[Appointment]:
    """Convenience alias to move an appointment to a new date/time."""
    return update_appointment(
        db,
        appt_id,
        date_=to_date,
        start_time_=start_time_,
        end_time_=end_time_,
        allow_overlap=allow_overlap,
    )


# ------------------------
# Delete operations
# ------------------------

def delete_appointment(db: Session, appt_id: int) -> bool:
    """Delete a single appointment by id. Returns True if deleted, False if not found."""
    appt = db.query(Appointment).get(appt_id)
    if not appt:
        return False
    db.delete(appt)
    db.commit()
    return True


def delete_appointment_by_id(db: Session, appt_id: int) -> bool:
    """Alias for delete_appointment to match app.py imports."""
    return delete_appointment(db, appt_id)


def delete_on_date(db: Session, target_date: _date, term: Optional[str] = None) -> List[Appointment]:
    """
    Delete all appointments on `target_date`. If `term` is provided, restrict to descriptions containing the term.
    Returns the list of deleted Appointment objects (snapshotted before commit).
    """
    q = db.query(Appointment).filter(Appointment.date == target_date)
    if term:
        q = q.filter(or_(
            Appointment.description.ilike(f"%{term}%"),
            Appointment.title.ilike(f"%{term}%")
        ))
    victims = q.order_by(Appointment.start_time).all()
    for a in victims:
        db.delete(a)
    db.commit()
    return victims


def delete_by_search(db: Session, term: str) -> List[Appointment]:
    """
    Delete appointments whose description or title contains `term` (case-insensitive).
    Returns the list of deleted objects.
    """
    victims = (
        db.query(Appointment)
        .filter(or_(
            Appointment.description.ilike(f"%{term}%"),
            Appointment.title.ilike(f"%{term}%")
        ))
        .all()
    )
    for a in victims:
        db.delete(a)
    db.commit()
    return victims


def delete_by_label(db: Session, label: str) -> List[Appointment]:
    """
    Delete appointments with an exact matching label. If the Appointment model has no `label` field, this is a no-op.
    Returns the list of deleted objects.
    """
    if not hasattr(Appointment, "label"):
        return []
    victims = db.query(Appointment).filter(getattr(Appointment, "label") == label).all()
    for a in victims:
        db.delete(a)
    db.commit()
    return victims


# ------------------------
# Move day helpers
# ------------------------

def move_appointments_day(db: Session, from_date: _date, to_date: _date) -> int:
    """
    Move all appointments on 'from_date' to 'to_date' (same times).
    Returns number of moved records. (Legacy helper)
    """
    updated, _ = move_day_appointments(db, from_date, to_date, keep_times=True)
    return len(updated)


def move_day_appointments(db: Session, from_date: _date, to_date: _date, *, keep_times: bool = True) -> Tuple[List[Appointment], List[Appointment]]:
    """
    Move all appointments on `from_date` to `to_date`.
    If keep_times=True, preserves start/end times; otherwise shifts to same duration starting at original start_time.
    Returns (updated_list, skipped_conflicts_list).
    """
    day_appts = db.query(Appointment).filter(Appointment.date == from_date).order_by(Appointment.start_time).all()
    updated: List[Appointment] = []
    skipped: List[Appointment] = []
    for a in day_appts:
        new_start = a.start_time
        new_end = a.end_time
        conflicts = [
            x for x in get_appointments_by_date(db, to_date)
            if _overlaps(new_start, new_end, x.start_time, x.end_time)
        ]
        if conflicts:
            skipped.append(a)
            continue
        a.date = to_date
        if not keep_times:
            # (optionally adjust — current implementation preserves as-is)
            pass
        updated.append(a)
    db.commit()
    for a in updated:
        db.refresh(a)
    return updated, skipped


# ------------------------
# Fuzzy/CI text matching + find
# ------------------------

def _match_text(hay: Optional[str], needle: Optional[str], *, case_insensitive: bool = True, min_ratio: float = 0.60) -> bool:
    """
    Return True if `needle` is a (case-insensitive) substring of `hay` or the
    fuzzy similarity ratio is >= min_ratio. Empty needle matches everything.
    """
    if not needle:
        return True
    if not hay:
        return False
    a, b = hay, needle
    if case_insensitive:
        a, b = a.casefold(), b.casefold()
    if b in a:
        return True
    try:
        return SequenceMatcher(None, a, b).ratio() >= float(min_ratio or 0.0)
    except Exception:
        return False


def find_appointments(
    db: Session,
    *,
    target_date: Optional[_date] = None,
    term: Optional[str] = None,
    start_time_: Optional[_time] = None,
    end_time_: Optional[_time] = None,
    label: Optional[str] = None,
    case_insensitive: bool = True,
    min_ratio: float = 0.60,
) -> List[Appointment]:
    """
    Flexible finder used by LLM-driven flows:
      - filter by exact date
      - fuzzy text match on description/title (CI substring OR SequenceMatcher >= min_ratio)
      - filter by time window containment (start>=, end<=)
      - optional exact label match (if model has `label`)
    """
    q = db.query(Appointment)
    if target_date is not None:
        q = q.filter(Appointment.date == target_date)
    if start_time_ is not None:
        q = q.filter(Appointment.start_time >= start_time_)
    if end_time_ is not None:
        q = q.filter(Appointment.end_time <= end_time_)
    if label and hasattr(Appointment, "label"):
        q = q.filter(getattr(Appointment, "label") == label)

    base = q.order_by(Appointment.date, Appointment.start_time).all()
    if not term:
        return base

    matched = []
    for a in base:
        desc = (getattr(a, "description", "") or "")
        titl = (getattr(a, "title", "") or "")
        if (
            _match_text(desc, term, case_insensitive=case_insensitive, min_ratio=min_ratio)
            or _match_text(titl, term, case_insensitive=case_insensitive, min_ratio=min_ratio)
        ):
            matched.append(a)
    return matched


# ------------------------
# Selector-based helpers (for updated app.py/openai_handler flows)
# ------------------------

def _norm(_s: Optional[str]) -> str:
    return (_s or "").strip().lower()


def _ratio(a: Optional[str], b: Optional[str]) -> float:
    a_n, b_n = _norm(a), _norm(b)
    if not a_n or not b_n:
        return 0.0
    try:
        return difflib.SequenceMatcher(None, a_n, b_n).ratio()
    except Exception:
        return 0.0


def _parse_time_str_raw(s: Any) -> Optional[_time]:
    """Accepts '14:30', '14:30:00', '2 pm', '2:30 PM', or a datetime.time."""
    if isinstance(s, _time):
        return s
    if not s:
        return None
    t = str(s).strip().lower()

    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", t)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        ss = int(m.group(3) or 0)
        if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
            return _time(hh, mm, ss)

    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", t)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        mer = m.group(3).lower()
        if mer == "pm" and hh != 12:
            hh += 12
        if mer == "am" and hh == 12:
            hh = 0
        return _time(hh % 24, mm, 0)
    return None


def _selector_threshold(sel: Dict[str, Any]) -> float:
    """prefer 0..1 scale; tolerate 50..100 from older code."""
    thr = sel.get("min_ratio") if isinstance(sel, dict) else None
    if thr is None:
        thr = sel.get("threshold") if isinstance(sel, dict) else None
    if thr is None:
        return 0.60
    try:
        thr_f = float(thr)
        return thr_f / 100.0 if thr_f > 1.0 else max(0.0, min(1.0, thr_f))
    except Exception:
        return 0.60


def _apply_basic_filters(qry, sel: Dict[str, Any]):
    """Apply cheap SQL-side filters (date/start_time/end_time/label/id) before fuzzy scoring."""
    if not isinstance(sel, dict):
        return qry
    if sel.get("id") is not None:
        try:
            _id = int(sel["id"])
            qry = qry.filter(Appointment.id == _id)
        except Exception:
            pass
    if sel.get("date"):
        try:
            d = sel["date"]
            if isinstance(d, str):
                d = _date.fromisoformat(d)
            qry = qry.filter(Appointment.date == d)
        except Exception:
            pass
    if sel.get("start_time"):
        t = _parse_time_str_raw(sel.get("start_time"))
        if t:
            qry = qry.filter(Appointment.start_time == t)
    if sel.get("end_time"):
        t = _parse_time_str_raw(sel.get("end_time"))
        if t:
            qry = qry.filter(Appointment.end_time == t)
    if sel.get("label"):
        val = str(sel["label"])
        if sel.get("case_insensitive", True):
            qry = qry.filter(Appointment.label.ilike(f"%{val}%"))
        else:
            qry = qry.filter(Appointment.label.like(f"%{val}%"))
    return qry


def find_appointments_by_selector(db: Session, selector: Dict[str, Any], limit: int = 5) -> List[Appointment]:
    """
    Flexible finder supporting:
      selector = {
         id?, date?, start_time?, end_time?, title?, term?, label?,
         case_insensitive?: bool (default True),
         min_ratio?: float in [0,1] (default 0.60)
      }
    Returns up to `limit` results sorted by descending score then time.
    """
    sel = selector or {}
    thr = _selector_threshold(sel)
    term = sel.get("title") or sel.get("term") or sel.get("description")
    term_n = _norm(term)

    # Start with cheap SQL filters
    base = db.query(Appointment)
    base = _apply_basic_filters(base, sel)

    # If no date filter was provided, bound the search to a reasonable window around today
    if not sel.get("date"):
        today = _date.today()
        win_start = today - timedelta(days=45)
        win_end = today + timedelta(days=60)
        base = base.filter(Appointment.date >= win_start, Appointment.date <= win_end)

    candidates = base.order_by(Appointment.date.asc(), Appointment.start_time.asc()).all()

    # Score by fuzzy title / term
    scored: List[Tuple[float, Appointment]] = []
    for a in candidates:
        score = 0.0
        if term_n:
            t_title = _norm(getattr(a, "title", None)) or _norm(getattr(a, "description", None))
            if term_n and t_title and term_n in t_title:
                score = 1.0
            else:
                score = _ratio(term, getattr(a, "title", None))
                score = max(score, _ratio(term, getattr(a, "description", None)))
        else:
            # no term -> score by presence of date/time match only
            score = 0.5
        if not term_n or score >= thr:
            scored.append((score, a))

    scored.sort(key=lambda x: (-x[0], getattr(x[1], "start_time", _time(0, 0))))
    return [a for (_s, a) in scored[:limit]]


def update_title_by_selector(db: Session, selector: Dict[str, Any], new_title: str) -> Optional[Appointment]:
    """
    Find the best matching appointment using the selector and update its title.
    Returns the updated appointment or None if not found.
    """
    matches = find_appointments_by_selector(db, selector, limit=1)
    if not matches:
        return None
    appt = matches[0]
    appt.description = new_title or appt.description
    appt.title = new_title or appt.title
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


def reschedule_by_selector(
    db: Session,
    selector: Dict[str, Any],
    *,
    new_date: Optional[_date] = None,
    new_start_time: Optional[_time] = None,
    new_end_time: Optional[_time] = None,
    allow_overlap: bool = False,
) -> Optional[Appointment]:
    """
    Find one appointment by selector and move it. If duration is implied by existing
    start/end, maintain it when only new_start_time is given.
    """
    matches = find_appointments_by_selector(db, selector, limit=1)
    if not matches:
        return None
    appt = matches[0]

    # keep duration when we have only new_start_time
    duration_min = None
    if appt.start_time and appt.end_time:
        duration_min = int((_dt.combine(_date.today(), appt.end_time) - _dt.combine(_date.today(), appt.start_time)).total_seconds() // 60)

    target_date = new_date or appt.date
    target_start = new_start_time or appt.start_time
    target_end = new_end_time
    if target_end is None and target_start and duration_min is not None:
        try:
            end_dt = _dt.combine(_date.today(), target_start) + timedelta(minutes=duration_min)
            target_end = end_dt.time().replace(microsecond=0)
        except Exception:
            target_end = appt.end_time

    if not allow_overlap:
        conflicts = [
            a for a in get_appointments_by_date(db, target_date)
            if a.id != appt.id and _overlaps(target_start, target_end, a.start_time, a.end_time)
        ]
        if conflicts:
            raise ValueError("Updated time slot conflicts with existing appointments")

    appt.date = target_date
    appt.start_time = target_start
    appt.end_time = target_end
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


def reschedule_by_selector_legacy(
    db: Session,
    selector: dict,
    *,
    to_date: _date,
    to_start: _time,
    to_end: _time,
    allow_overlap: bool = False,
) -> Optional[Appointment]:
    """
    Legacy wrapper retained for older callers that pass (to_date/to_start/to_end).
    """
    return reschedule_by_selector(
        db,
        selector,
        new_date=to_date,
        new_start_time=to_start,
        new_end_time=to_end,
        allow_overlap=allow_overlap,
    )


def delete_by_selector(db: Session, selector: Dict[str, Any]) -> int:
    """
    Delete all appointments matching a selector. Returns number of rows deleted.
    """
    sel = selector or {}
    matches = find_appointments_by_selector(db, sel, limit=100)
    ids = [getattr(m, 'id', None) for m in matches]
    ids = [i for i in ids if i is not None]
    if not ids:
        return 0
    q = db.query(Appointment).filter(Appointment.id.in_(ids))
    count = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return int(count)

# ------------------------
# REMINDERS
# ------------------------

def _dt_combine(d: _date, t: _time) -> _dt:
    return _dt(d.year, d.month, d.day, t.hour, t.minute, t.second)

def create_reminder(
    db: Session,
    *,
    date_: _date,
    time_: _time,
    title: str,
    description: Optional[str] = None,
    lead_minutes: int = 0,
    channel: str = "inapp",
    appointment_id: Optional[int] = None,
) -> Reminder:
    r = Reminder(
        date=date_,
        time=time_,
        title=title or (description or "Reminder"),
        description=description or title,
        lead_minutes=int(lead_minutes or 0),
        channel=channel or "inapp",
        appointment_id=appointment_id,
        active=True,
        delivered=False,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r

def create_reminder_for_appointment(
    db: Session,
    appt: Appointment,
    *,
    lead_minutes: int = 15,
    title: Optional[str] = None,
    channel: str = "inapp",
) -> Reminder:
    # Compute reminder wall time = (appt.date, appt.start_time) - lead
    start_dt = _dt_combine(appt.date, appt.start_time)
    fire_dt = start_dt - timedelta(minutes=int(lead_minutes or 0))
    return create_reminder(
        db,
        date_=fire_dt.date(),
        time_=fire_dt.time().replace(microsecond=0),
        title=title or (appt.description or "Upcoming appointment"),
        description=f"Reminder for: {appt.description or 'appointment'}",
        lead_minutes=int(lead_minutes or 0),
        channel=channel,
        appointment_id=appt.id,
    )

def get_reminder_by_id(db: Session, reminder_id: int) -> Optional[Reminder]:
    return db.query(Reminder).get(reminder_id)

def list_reminders(
    db: Session,
    *,
    start_date: Optional[_date] = None,
    end_date: Optional[_date] = None,
    active: Optional[bool] = None,
    search: Optional[str] = None,
) -> List[Reminder]:
    q = db.query(Reminder)
    if start_date and end_date:
        q = q.filter(Reminder.date.between(start_date, end_date))
    elif start_date:
        q = q.filter(Reminder.date >= start_date)
    elif end_date:
        q = q.filter(Reminder.date <= end_date)
    if active is not None:
        q = q.filter(Reminder.active == bool(active))
    if search:
        q = q.filter(or_(
            Reminder.title.ilike(f"%{search}%"),
            Reminder.description.ilike(f"%{search}%"),
        ))
    return q.order_by(Reminder.date, Reminder.time).all()

def delete_reminder(db: Session, reminder_id: int) -> bool:
    r = db.query(Reminder).get(reminder_id)
    if not r:
        return False
    db.delete(r)
    db.commit()
    return True

def update_reminder(
    db: Session,
    reminder_id: int,
    *,
    date_: Optional[_date] = None,
    time_: Optional[_time] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    lead_minutes: Optional[int] = None,
    channel: Optional[str] = None,
    active: Optional[bool] = None,
) -> Optional[Reminder]:
    r = db.query(Reminder).get(reminder_id)
    if not r:
        return None
    if date_ is not None:
        r.date = date_
    if time_ is not None:
        r.time = time_
    if title is not None:
        r.title = title
    if description is not None:
        r.description = description
    if lead_minutes is not None:
        r.lead_minutes = int(lead_minutes)
    if channel is not None:
        r.channel = channel
    if active is not None:
        r.active = bool(active)
    db.commit()
    db.refresh(r)
    return r

def toggle_reminder(db: Session, reminder_id: int, *, active: Optional[bool] = None) -> Optional[Reminder]:
    r = db.query(Reminder).get(reminder_id)
    if not r:
        return None
    r.active = (not r.active) if active is None else bool(active)
    db.commit()
    db.refresh(r)
    return r

def mark_reminder_delivered(db: Session, reminder_id: int) -> Optional[Reminder]:
    r = db.query(Reminder).get(reminder_id)
    if not r:
        return None
    r.delivered = True
    db.commit()
    db.refresh(r)
    return r

def snooze_reminder(db: Session, reminder_id: int, minutes: int = 10) -> Optional[Reminder]:
    r = db.query(Reminder).get(reminder_id)
    if not r:
        return None
    # push only the time component forward; keep same date
    new_time = (_dt.combine(_date.today(), r.time) + timedelta(minutes=int(minutes or 0))).time().replace(microsecond=0)
    r.time = new_time
    r.delivered = False
    db.commit()
    db.refresh(r)
    return r

def get_due_reminders(db: Session, now: Optional[_dt] = None) -> List[Reminder]:
    now = now or _dt.utcnow()
    # due if (date,time) &lt;= now and active and not delivered
    return db.query(Reminder).filter(
        and_(
            or_(Reminder.date < now.date(), and_(Reminder.date == now.date(), Reminder.time <= now.time())),
            Reminder.active == True,
            Reminder.delivered == False,
        )
    ).order_by(Reminder.date, Reminder.time).all()