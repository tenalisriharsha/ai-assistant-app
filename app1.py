# app.py  — Scheduler API (updated)

from flask import Flask, request, jsonify
from flask_cors import CORS
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import date as _date, time as _time, timedelta, datetime as _dt, timezone as _tz
from difflib import SequenceMatcher

from openai_handler import parse_query
from database import SessionLocal
from crud import (
    # reads
    get_appointment_by_id,
    get_appointments_by_date,
    get_appointments_for_week,
    get_appointments_between as crud_get_appointments_between,
    get_next_appointment,
    search_appointments_by_description,
    get_appointments_on_weekends,
    get_appointments_after_time,
    count_appointments_in_range,
    get_conflicting_appointments,
    # writes / helpers
    create_appointment,
    create_appointment_if_free,
    bulk_create_appointments,
    find_conflicts_for_slot,
    # NEW modify/delete helpers
    find_appointments,
    update_appointment_time,
    update_appointment_title,
    reschedule_appointment,
    delete_appointment_by_id,
    delete_on_date,
    delete_by_search,
    delete_by_label,
    move_day_appointments,
    # reminders
    create_reminder, create_reminder_for_appointment, list_reminders,
    get_reminder_by_id, update_reminder, delete_reminder, toggle_reminder,
    get_due_reminders, snooze_reminder, mark_reminder_delivered,
)

# Safe import for ZoneInfo (Python 3.9+)
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None  # type: ignore

# Optional templates module
try:
    from templates import generate_template_blocks
except Exception:
    generate_template_blocks = None  # type: ignore

from schemas import Appointment as AppointmentSchema
from pydantic import ValidationError  # used in serializer guard

app = Flask(__name__)
CORS(app)

# ---------- helpers ----------
def _compute_free_slots(appts):
    day_start = _time(0, 0)
    day_end = _time(23, 59, 59)
    free = []
    prev_end = day_start
    for a in appts:
        if a.start_time > prev_end:
            free.append({"start": prev_end.isoformat(), "end": a.start_time.isoformat()})
        if a.end_time > prev_end:
            prev_end = a.end_time
    if prev_end < day_end:
        free.append({"start": prev_end.isoformat(), "end": day_end.isoformat()})
    return free


def _to_date(obj) -> Optional[_date]:
    if isinstance(obj, _date):
        return obj
    if isinstance(obj, str):
        try:
            return _date.fromisoformat(obj)
        except Exception:
            return None
    return None


def _to_time(obj) -> Optional[_time]:
    if isinstance(obj, _time):
        return obj
    if isinstance(obj, str):
        s = obj.strip().lower()
        m = re.match(r"^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?$", s)
        if not m:
            return None
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        ss = int(m.group(3) or 0)
        ampm = m.group(4)
        if ampm == "pm" and hh != 12:
            hh += 12
        if ampm == "am" and hh == 12:
            hh = 0
        return _time(hh, mm, ss)
    return None


def _as_delta(t1: _time, t2: _time) -> timedelta:
    return timedelta(hours=t2.hour, minutes=t2.minute, seconds=t2.second) - \
           timedelta(hours=t1.hour, minutes=t1.minute, seconds=t1.second)


def _add_minutes(t: _time, minutes: int) -> _time:
    base = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
    res = base + timedelta(minutes=minutes)
    total_seconds = int(res.total_seconds())
    hh = (total_seconds // 3600) % 24
    mm = (total_seconds % 3600) // 60
    ss = total_seconds % 60
    return _time(hh, mm, ss)


def _duration_minutes(start_t: _time, end_t: _time) -> int:
    delta = _as_delta(start_t, end_t)
    mins = int(delta.total_seconds() // 60)
    return mins if mins > 0 else 0


# ---- fuzzy match helpers ----
def _fuzzy_match(haystack: Optional[str], needle: Optional[str], *, case_insensitive: bool = True, min_ratio: float = 0.60) -> bool:
    """
    Case-insensitive substring check with a fuzzy fallback.
    Returns True if `needle` is contained in `haystack` (respecting case_insensitive),
    or if the SequenceMatcher ratio is ≥ min_ratio.
    """
    if not needle:
        return True
    if not haystack:
        return False
    h = haystack
    n = needle
    if case_insensitive:
        h = h.lower()
        n = n.lower()
    if n in h:
        return True
    try:
        return SequenceMatcher(None, n, h).ratio() >= float(min_ratio)
    except Exception:
        # Fallback to simple containment if SequenceMatcher is unavailable for any reason
        return n in h

def _match_opts(selector: dict, data: Optional[dict] = None) -> tuple[Optional[bool], Optional[float]]:
    """
    Extract case-insensitive / fuzzy matching options from a selector and/or the request payload.
    Accepts keys: case_insensitive, min_ratio, fuzzy_ratio (aliases).
    Returns (case_insensitive, min_ratio or None).
    """
    ci = None
    mr = None
    if isinstance(selector, dict):
        ci = selector.get('case_insensitive')
        mr = selector.get('min_ratio') or selector.get('fuzzy_ratio')
    if data:
        if ci is None:
            ci = data.get('case_insensitive')
        if mr is None:
            mr = data.get('min_ratio') or data.get('fuzzy_ratio')
    # Normalize
    try:
        mr = float(mr) if mr is not None else None
    except Exception:
        mr = None
    if isinstance(ci, str):
        ci = ci.lower() in ('1', 'true', 'yes', 'y', 'on')
    return ci, mr


# ---- simple recurrence helpers (range-based) ----
def _iter_dates_range(
    start_date: _date,
    end_date: _date,
    *,
    pattern: str = "DAILY",
    weekday: Optional[int] = None,
    by_weekdays: Optional[List[int]] = None,
    interval: int = 1,
):
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    pattern = (pattern or "DAILY").upper()
    allowed = set()
    if pattern == "WEEKLY":
        if by_weekdays and isinstance(by_weekdays, list):
            allowed = {int(x) for x in by_weekdays if isinstance(x, (int, str))}
        elif weekday is not None:
            allowed = {int(weekday)}
        else:
            allowed = {start_date.weekday()}

    i = 0
    d = start_date
    while d <= end_date:
        if pattern == "DAILY":
            if i % max(1, int(interval or 1)) == 0:
                yield d
        elif pattern == "WEEKDAYS":
            if d.weekday() < 5:
                yield d
        elif pattern == "WEEKLY":
            if d.weekday() in allowed:
                yield d
        else:
            yield d
        i += 1
        d += timedelta(days=1)


# ---- date range helper ----
def _parse_date_range_param(dr) -> Optional[tuple[_date, _date]]:
    if not dr:
        return None
    s = e = None
    if isinstance(dr, list) and len(dr) == 2:
        s = _to_date(dr[0]); e = _to_date(dr[1])
    elif isinstance(dr, str) and "/" in dr:
        left, right = dr.split("/", 1)
        s = _to_date(left.strip()); e = _to_date(right.strip())
    if s and e:
        if e < s:
            s, e = e, s
        return s, e
    return None


# ---- naive phrase helpers (month/day & recurring fallback) ----
_month_map = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
    'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9, 'oct': 10,
    'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12,
}
_weekday_map = {
    'mon': 0, 'monday': 0, 'tue': 1, 'tues': 1, 'tuesday': 1, 'wed': 2, 'wednesday': 2,
    'thu': 3, 'thur': 3, 'thurs': 3, 'thursday': 3, 'fri': 4, 'friday': 4,
    'sat': 5, 'saturday': 5, 'sun': 6, 'sunday': 6,
}

def _parse_month_name_token(tok: str) -> Optional[int]:
    if not tok:
        return None
    return _month_map.get(tok.strip().lower())

# --- NEW: Spoken date helpers (minimal + isolated) ---
def _strip_ordinals(s: str) -> str:
    # "29th" → "29", "1st" → "1"
    return re.sub(r'\b(\d{1,2})(st|nd|rd|th)\b', r'\1', s, flags=re.IGNORECASE)

def _parse_human_date(text: str, *, reference: Optional[_date] = None) -> Optional[_date]:
    """
    Parse common spoken dates: "29th August", "Aug 29", "Aug 29, 2025", "29 Aug 2025",
    and variants like "on the 28th of August".
    If year is missing, assume current year.
    """
    if not text:
        return None
    reference = reference or _date.today()

    # normalize: drop ordinals and collapse multiple spaces
    def _strip_ordinals_local(s: str) -> str:
        s = re.sub(r'\b(\d{1,2})(st|nd|rd|th)\b', r'\1', s, flags=re.IGNORECASE)
        s = re.sub(r'\s+', ' ', s)
        return s

    t = _strip_ordinals_local(text.strip().lower())
    mon_pat = r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'

    # Pattern A: "28 august [2025]" and "on the 28 of august"
    m = re.search(rf'\b(?:on\s+the\s+|on\s+)?(\d{{1,2}})\s+(?:of\s+)?{mon_pat}(?:\s+(\d{{4}}))?\b', t)
    if m:
        day = int(m.group(1))
        mon = _parse_month_name_token(m.group(2))
        year = int(m.group(3)) if m.group(3) else reference.year
        if mon:
            try:
                return _date(year, mon, day)
            except Exception:
                return None

    # Pattern B: "august 28 [, 2025]"
    m = re.search(rf'\b{mon_pat}\s+(\d{{1,2}})(?:,\s*(\d{{4}}))?\b', t)
    if m:
        mon = _parse_month_name_token(m.group(1))
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else reference.year
        if mon:
            try:
                return _date(year, mon, day)
            except Exception:
                return None

    return None

def _extract_title_from_text(text: str) -> Optional[str]:
    """
    Pull a title from phrases like:
      • "with the title Demo"
      • "titled Demo"
      • "called Demo"
      • "named Demo"
    Returns None if nothing sensible is found.
    """
    if not text:
        return None
    m = re.search(r'(?:with\s+the\s+title|titled|called|named)\s+[“"]?([^"”]+?)[”"]?(?:\s|$)', text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else None


def _parse_month_day_range_text(text: str) -> Optional[tuple[_date, _date]]:
    if not text:
        return None
    patterns = [
        r"\bfrom\s+([a-zA-Z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|through|thru|-|until|till|and)\s*([a-zA-Z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        r"\bbetween\s+([a-zA-Z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*(?:and|to)\s*([a-zA-Z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    ]
    m = None
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            break
    if not m:
        return None
    m1, d1, m2, d2 = m.group(1), m.group(2), m.group(3), m.group(4)
    mi1 = _parse_month_name_token(m1)
    mi2 = _parse_month_name_token(m2)
    if not mi1 or not mi2:
        return None
    year = _date.today().year
    try:
        s = _date(year, mi1, int(d1))
        e = _date(year, mi2, int(d2))
    except Exception:
        return None
    if e < s:
        s, e = e, s
    return s, e


def _parse_weekday_list(text: str) -> List[int]:
    if not text:
        return []
    tl = text.lower()
    if "every" not in tl:
        return []
    seg = tl[tl.find("every"):]
    toks = re.findall(
        r"\b(mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
        seg
    )
    wdays: List[int] = []
    if re.search(r"\bweekdays?\b", seg):
        wdays.extend([0, 1, 2, 3, 4])
    if re.search(r"\bweekends?\b", seg):
        wdays.extend([5, 6])
    for tok in toks:
        key = tok[:3] if len(tok) > 3 else tok
        if key in _weekday_map:
            w = _weekday_map[key]
            if w not in wdays:
                wdays.append(w)
    return wdays


def _parse_time_range_text(text: str) -> Optional[tuple[_time, _time]]:
    if not text:
        return None
    tl = text.lower()
    m = re.search(
        r"\bfrom\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\s*(?:-|to|–|—)\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b",
        tl
    )
    if not m:
        m = re.search(
            r"\bbetween\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\s*(?:and|to)\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b",
            tl
        )
    if not m:
        m = re.search(
            r"\b([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\s*(?:-|to|–|—)\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b",
            tl
        )
    if not m:
        return None
    st = _to_time(m.group(1))
    et = _to_time(m.group(2))
    return (st, et) if (st and et) else None


def _parse_duration_minutes_from_text(text: str) -> Optional[int]:
    if not text:
        return None
    tl = text.lower()

    # 1) Mixed forms: "1h 30m", "2 hours 15 min"
    m = re.search(r"(\d+)\s*h(?:ours?|rs?)?\s*(\d+)\s*m(?:in(?:ute)?s?)?", tl)
    if m:
        try:
            return int(m.group(1)) * 60 + int(m.group(2))
        except Exception:
            return None

    # 2) Decimal hours: "1.5h", "1.5 hours"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hours?|hrs?)\b", tl)
    if m:
        try:
            return max(1, int(round(float(m.group(1)) * 60)))
        except Exception:
            return None

    # 3) Minutes with or without hyphen/space: "60 minutes", "60-minute", "90min", "90 m"
    m = re.search(r"(\d+)\s*[-\s]?(?:minutes?|mins?|m)\b", tl)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None

    # 4) Hours in compact form: "1hr", "2 hrs"
    m = re.search(r"(\d+)\s*[-\s]?(?:hr|hrs)\b", tl)
    if m:
        try:
            return int(m.group(1)) * 60
        except Exception:
            return None

    # 5) Common verbal forms
    if re.search(r"\b(an|one)\s+hour\b", tl):
        return 60
    if re.search(r"\bhalf[-\s]+an?\s+hour\b", tl) or re.search(r"\ban?\s+half[-\s]+hour\b", tl):
        return 30
    if re.search(r"\b(one|1)\s+and\s+a\s+half\s+hours?\b", tl) or re.search(r"\ban?\s+hour\s+and\s+a\s+half\b", tl):
        return 90

    return None


# ---- lead (reminder) parsing helper ----
def _parse_lead_from_text(text: str) -> Optional[int]:
    if not text:
        return None
    tl = text.lower()
    # “1.5 hours before”, “1 hour before”, “10 minutes before”, “day before”, “week before”
    m = re.search(r'(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\s*before', tl)
    if m:
        try:
            return max(1, int(round(float(m.group(1)) * 60)))
        except Exception:
            return None
    m = re.search(r'(\d+)\s*(minutes?|mins?|m)\s*before', tl)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    if 'day before' in tl or 'the day before' in tl:
        return 24 * 60
    if 'week before' in tl:
        return 7 * 24 * 60
    return None


# ---- month helpers ----
from calendar import monthrange
def _month_bounds(year: int, month: int) -> tuple[_date, _date]:
    first = _date(year, month, 1)
    last = _date(year, month, monthrange(year, month)[1])
    return first, last


# ---- datetime/tz helpers ----
def _dt_combine(d: _date, t: _time) -> _dt:
    return _dt(d.year, d.month, d.day, t.hour, t.minute, t.second)

def _local_tz():
    try:
        return _dt.now().astimezone().tzinfo
    except Exception:
        return None

def _normalize_tz(tz: str) -> str:
    if not tz:
        return tz
    m = tz.strip().upper()
    mapping = {
        "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
        "MST": "America/Denver", "MDT": "America/Denver",
        "CST": "America/Chicago", "CDT": "America/Chicago",
        "EST": "America/New_York", "EDT": "America/New_York",
        "GMT": "Etc/GMT", "UTC": "Etc/UTC", "CET": "Europe/Berlin",
        "CEST": "Europe/Berlin", "BST": "Europe/London",
        "IST": "Asia/Kolkata", "JST": "Asia/Tokyo",
        "AEST": "Australia/Sydney", "AEDT": "Australia/Sydney",
    }
    return mapping.get(m, tz)

def _tz_to_local_date_time(d: _date, t: _time, tz_str: str) -> tuple[_date, _time]:
    if ZoneInfo is None:
        return d, t
    try:
        src = ZoneInfo(_normalize_tz(tz_str))
        dst = _local_tz()
        if dst is None:
            return d, t
        src_dt = _dt(d.year, d.month, d.day, t.hour, t.minute, t.second, tzinfo=src)
        dst_dt = src_dt.astimezone(dst)
        return dst_dt.date(), dst_dt.time().replace(microsecond=0)
    except Exception:
        return d, t


def _find_first_free_slot(
    appts: List[Any],
    duration_minutes: int,
    window_start: _time,
    window_end: _time,
) -> Optional[Tuple[_time, _time]]:
    if duration_minutes <= 0:
        return None
    needed = timedelta(minutes=duration_minutes)

    blocks: List[Tuple[_time, _time]] = []
    for a in appts:
        if a.end_time <= window_start or a.start_time >= window_end:
            continue
        s = max(a.start_time, window_start)
        e = min(a.end_time, window_end)
        blocks.append((s, e))

    blocks.sort()
    merged: List[Tuple[_time, _time]] = []
    for s, e in blocks:
        if not merged:
            merged.append((s, e))
        else:
            last_s, last_e = merged[-1]
            if s <= last_e:
                merged[-1] = (last_s, max(last_e, e))
            else:
                merged.append((s, e))

    cursor = window_start
    for s, e in merged:
        gap = _as_delta(cursor, s)
        if gap >= needed:
            return cursor, _add_minutes(cursor, duration_minutes)
        cursor = max(cursor, e)

    if _as_delta(cursor, window_end) >= needed:
        return cursor, _add_minutes(cursor, duration_minutes)

    return None


def _find_all_free_slots(
    appts: List[Any],
    duration_minutes: int,
    window_start: _time,
    window_end: _time,
    *,
    limit: int = 5,
    step_minutes: Optional[int] = None,
) -> List[Tuple[_time, _time]]:
    if duration_minutes <= 0:
        return []
    needed = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=step_minutes if step_minutes is not None else duration_minutes)

    blocks: List[Tuple[_time, _time]] = []
    for a in appts:
        if a.end_time <= window_start or a.start_time >= window_end:
            continue
        s = max(a.start_time, window_start)
        e = min(a.end_time, window_end)
        blocks.append((s, e))
    blocks.sort()

    merged: List[Tuple[_time, _time]] = []
    for s, e in blocks:
        if not merged:
            merged.append((s, e))
        else:
            ls, le = merged[-1]
            if s <= le:
                merged[-1] = (ls, max(le, e))
            else:
                merged.append((s, e))

    proposals: List[Tuple[_time, _time]] = []
    cursor = window_start

    def emit_from_gap(g_start: _time, g_end: _time):
        nonlocal proposals
        st = g_start
        while _as_delta(st, g_end) >= needed and len(proposals) < limit:
            en = _add_minutes(st, duration_minutes)
            proposals.append((st, en))
            st_td = timedelta(hours=st.hour, minutes=st.minute, seconds=st.second) + step
            secs = int(st_td.total_seconds())
            st = _time((secs // 3600) % 24, (secs % 3600) // 60, secs % 60)

    for s, e in merged:
        if cursor < s:
            emit_from_gap(cursor, s)
            if len(proposals) >= limit:
                return proposals
        cursor = max(cursor, e)
    if cursor < window_end:
        emit_from_gap(cursor, window_end)
    return proposals


def _serialize_appt(a) -> Dict[str, Any]:
    try:
        return AppointmentSchema.model_validate(a).model_dump(mode="json")
    except Exception as e:
        print("SERIALIZE_WARNING:", getattr(a, "id", None), e)
        # Graceful fallback to avoid 500s if a corrupted row exists
        return {
            "id": getattr(a, "id", None),
            "date": a.date.isoformat() if getattr(a, "date", None) else None,
            "start_time": a.start_time.isoformat() if getattr(a, "start_time", None) else None,
            "end_time": a.end_time.isoformat() if getattr(a, "end_time", None) else None,
            "description": getattr(a, "description", None),
            "title": getattr(a, "title", getattr(a, "description", None)),
            "invalid": "end_time must be after start_time",
        }

# --- REMINDER SERIALIZATION ---
def _serialize_reminder(r, db=None, *, include_appt: bool = True, appt=None) -> Dict[str, Any]:
    """
    Serialize a Reminder row to JSON, optionally enriching with linked appointment
    title and duration so the UI can render consistently even if appointments are
    not loaded in memory.
    """
    try:
        d: Dict[str, Any] = {
            'id': getattr(r, 'id', None),
            'date': r.date.isoformat() if getattr(r, 'date', None) else None,
            'time': r.time.isoformat() if getattr(r, 'time', None) else None,
            'title': getattr(r, 'title', None),
            'lead_minutes': int(getattr(r, 'lead_minutes', 0) or 0),
            'channel': getattr(r, 'channel', None),
            'active': bool(getattr(r, 'active', True)),
            'delivered': bool(getattr(r, 'delivered', False)),
            'appointment_id': getattr(r, 'appointment_id', None),
        }
        if include_appt and (appt is not None or (db is not None and getattr(r, 'appointment_id', None))):
            try:
                _a = appt or get_appointment_by_id(db, int(r.appointment_id))
                if _a:
                    d['appt_title'] = (_a.description or getattr(_a, 'title', '') or '')[:255]
                    d['appt_duration_minutes'] = _duration_minutes(_a.start_time, _a.end_time)
                    d['appt_start'] = _a.start_time.isoformat() if getattr(_a, 'start_time', None) else None
                    d['appt_end'] = _a.end_time.isoformat() if getattr(_a, 'end_time', None) else None
            except Exception:
                # Non-fatal: keep base reminder payload
                pass
        return d
    except Exception as e:
        # Extremely defensive fallback
        return {
            'id': getattr(r, 'id', None),
            'date': getattr(r, 'date', None).isoformat() if getattr(r, 'date', None) else None,
            'time': getattr(r, 'time', None).isoformat() if getattr(r, 'time', None) else None,
            'title': getattr(r, 'title', None),
            'lead_minutes': int(getattr(r, 'lead_minutes', 0) or 0),
            'channel': getattr(r, 'channel', None),
            'active': bool(getattr(r, 'active', True)),
            'delivered': bool(getattr(r, 'delivered', False)),
            'appointment_id': getattr(r, 'appointment_id', None),
        }


# --- unified helper to compute target reschedule window ---
def _resolve_reschedule_times(appt, new_date: Optional[_date], new_start: Optional[_time], new_end: Optional[_time]) -> tuple[_date, _time, _time]:
    """
    Returns a consistent (date, start, end) triple for rescheduling.
    Rules:
      • If neither new_start nor new_end is provided, keep original start/end and only move the date.
      • If only new_start is provided, keep original duration.
      • If only new_end is provided, keep original duration and back-compute start.
      • If both provided and invalid (end <= start), keep duration from original and treat `new_start` as anchor.
    """
    # Original values
    d = appt.date
    s = appt.start_time
    e = appt.end_time

    if new_date:
        d = new_date

    # Duration in minutes from original appointment (always positive in DB)
    dur = _duration_minutes(s, e)
    if dur <= 0:
        dur = 60  # extremely defensive fallback

    s2 = new_start if new_start else s
    e2 = new_end   if new_end   else e

    if new_start and not new_end:
        e2 = _add_minutes(s2, dur)
    elif new_end and not new_start:
        # Back-compute start from new_end with same duration
        s2 = _add_minutes(new_end, -dur)
    elif new_start and new_end:
        # If end is not after start, repair by preserving duration from original
        if _as_delta(new_start, new_end).total_seconds() <= 0:
            e2 = _add_minutes(new_start, dur)
            s2 = new_start
    # else: neither provided → keep original s/e

    return d, s2, e2


# ---------- route ----------
@app.route('/query', methods=['POST'])
def query_appointments():
    data = request.json or {}
    raw_action = data.get('action') or data.get('op') or data.get('type')
    action = (raw_action.strip().lower() if isinstance(raw_action, str) else None)
    # Debug: surface the incoming action and payload in logs
    if action:
        print("ACTION_DEBUG:", {"raw": raw_action, "normalized": action, "keys": list(data.keys())})

    # 1) Structured actions (backward compatible)
    if action:
        db = SessionLocal()
        today = _date.today()

        # ---- Deleting (structured) ----
        if action in {"delete", "cancel", "remove", "delete_single"}:
            # 1) Try direct id fields commonly sent by UI variants
            appt_id = (
                data.get("id")
                or data.get("appt_id")
                or data.get("appointment_id")
                or data.get("appointmentId")
            )

            # 2) Or a nested selector object
            selector = data.get("selector") or {}
            ci_opt, mr_opt = _match_opts(selector, data)
            if not appt_id and isinstance(selector, dict):
                appt_id = (
                    selector.get("id")
                    or selector.get("appt_id")
                    or selector.get("appointment_id")
                    or selector.get("appointmentId")
                )

            appt = None

            # 3) As a last resort, resolve by (date, start_time, end_time, title)
            if not appt_id:
                sel_date = _to_date(data.get("date") or selector.get("date"))
                sel_start = _to_time(data.get("start_time") or selector.get("start_time"))
                sel_end = _to_time(data.get("end_time") or selector.get("end_time"))
                sel_title = (data.get("title") or selector.get("title") or "").strip() or None
                if sel_date:
                    matches = find_appointments(
                        db,
                        target_date=sel_date,
                        term=sel_title,
                        start_time_=sel_start,
                        end_time_=sel_end,
                        case_insensitive=True if ci_opt is None else bool(ci_opt),
                        min_ratio=mr_opt if mr_opt is not None else 0.60,
                    )
                    if len(matches) == 1:
                        appt = matches[0]
                        appt_id = appt.id

            if appt_id is None:
                db.close()
                return jsonify({"error": "Missing id/appt_id for delete"}), 400

            try:
                appt_id = int(appt_id)
            except Exception:
                db.close()
                return jsonify({"error": "Invalid id"}), 400

            ok = delete_appointment_by_id(db, appt_id)
            db.close()
            if ok:
                return jsonify({"deleted": True, "id": appt_id})
            else:
                return jsonify({"deleted": False, "error": "Not found"}), 404

        # ---- Updating / Rescheduling (structured) ----
        if action in {'update', 'reschedule', 'move'}:
            selector = data.get('selector') or {}
            # Support UI payloads that send updates inside a 'fields' object
            fields = data.get('fields') or {}
            ci_opt, mr_opt = _match_opts(selector, data)
            appt = None

            # 1) Try id first (either top-level or inside selector)
            sel_id = selector.get('id') or data.get('id')
            if sel_id:
                try:
                    appt = get_appointment_by_id(db, int(sel_id))
                except Exception:
                    appt = None

            # 2) Otherwise, try to resolve by (date, time window, optional title)
            if not appt:
                sel_date = _to_date(selector.get('date') or data.get('date'))
                sel_start = _to_time(selector.get('start_time') or data.get('start_time'))
                sel_end = _to_time(selector.get('end_time') or data.get('end_time'))
                sel_title = (selector.get('title') or data.get('title') or data.get('description') or '').strip() or None
                # If UI sent the title inside fields, fold it in as a selector hint
                if not sel_title:
                    sel_title = (fields.get('title') or fields.get('description') or '').strip() or None

                matches = find_appointments(
                    db,
                    target_date=sel_date,
                    term=sel_title,
                    start_time_=sel_start,
                    end_time_=sel_end,
                    case_insensitive=True if ci_opt is None else bool(ci_opt),
                    min_ratio=mr_opt if mr_opt is not None else 0.60,
                ) if sel_date else []
                appt = matches[0] if matches else None

                # Fallback: exact-window scan on that date if provided
                if not appt and sel_date:
                    day_list = get_appointments_by_date(db, sel_date)
                    for a in day_list:
                        same_start = (sel_start is None) or (a.start_time == sel_start)
                        same_end = (sel_end is None) or (a.end_time == sel_end)
                        title_ok = (not sel_title) or _fuzzy_match(
                            (a.description or ''),
                            sel_title,
                            case_insensitive=True if ci_opt is None else bool(ci_opt),
                            min_ratio=mr_opt if mr_opt is not None else 0.60,
                        )
                        if same_start and same_end and title_ok:
                            appt = a
                            break

            # 3) If still not found and only a title is provided, search today then the next 7 days
            if not appt:
                sel_title2 = (selector.get('title') or data.get('title') or data.get('description') or '').strip() or None
                if not sel_title2:
                    sel_title2 = (fields.get('title') or fields.get('description') or '').strip() or None
                if sel_title2:
                    today_local = _date.today()
                    todays = get_appointments_by_date(db, today_local)
                    cand = [a for a in todays if sel_title2.lower() in (a.description or '').lower()]
                    if len(cand) == 1:
                        appt = cand[0]
                    elif len(cand) == 0:
                        win = get_appointments_for_week(db, today_local, today_local + timedelta(days=7))
                        cand2 = [a for a in win if sel_title2.lower() in (a.description or '').lower()]
                        if cand2:
                            cand2.sort(key=lambda a: (a.date, a.start_time))
                            appt = cand2[0]

            if not appt:
                db.close()
                return jsonify({'error': 'No matching appointment found to reschedule.'}), 404

            # If caller is only changing the title/description (no date/time provided), treat as rename
            new_title = (fields.get('title') or fields.get('description') or '').strip()
            provided_time_change = any([
                data.get('new_date'), data.get('date'), fields.get('date'),
                data.get('new_start_time'), data.get('new_start'), data.get('time'),
                fields.get('start_time'), fields.get('start'),
                data.get('new_end_time'), data.get('new_end'),
                fields.get('end_time'), fields.get('end')
            ])
            if new_title and not provided_time_change:
                updated = update_appointment_title(db, appt.id, new_title)
                db.close()
                return jsonify({'updated': _serialize_appt(updated) if updated else None})

            # Compute target window using unified helper (preserve duration safely)
            req_new_date  = _to_date(data.get('new_date') or data.get('date') or fields.get('date'))
            req_new_start = _to_time(
                data.get('new_start_time') or data.get('new_start') or data.get('time') or
                fields.get('start_time')   or fields.get('start')
            )
            req_new_end   = _to_time(
                data.get('new_end_time') or data.get('new_end') or
                fields.get('end_time')   or fields.get('end')
            )
            target_date, target_start, target_end = _resolve_reschedule_times(appt, req_new_date, req_new_start, req_new_end)

            try:
                updated = update_appointment_time(
                    db,
                    appt_id=appt.id,
                    date_=target_date,
                    start_time_=target_start,
                    end_time_=target_end,
                    allow_overlap=False,
                )
                if not updated:
                    db.close()
                    return jsonify({'error': 'Update failed'}), 400
                db.close()
                return jsonify({'updated': _serialize_appt(updated)})
            except ValueError as e:
                # Conflict: return proposals so UI can surface options
                base_dur = _duration_minutes(appt.start_time, appt.end_time)
                dur_min = _duration_minutes(target_start, target_end) if (target_start and target_end) else (base_dur if base_dur > 0 else 60)
                day_appts = get_appointments_by_date(db, target_date)
                props = _find_all_free_slots(day_appts, dur_min, _time(0,0,0), _time(23,59,59), limit=5)
                db.close()
                return jsonify({
                    'error': 'Updated time slot conflicts with existing appointments',
                    'details': str(e),
                    'proposals': [
                        {'date': target_date.isoformat(), 'start_time': s.isoformat(), 'end_time': e.isoformat()}
                        for (s, e) in props
                    ]
                }), 409
            except Exception as e:
                db.close()
                return jsonify({'error': 'Update failed', 'details': str(e)}), 500

        # ---- Scheduling / Creating (structured) ----
        if action == 'create':
            target = _to_date(data.get('date'))
            start_t = _to_time(data.get('start_time') or data.get('time'))
            end_t = _to_time(data.get('end_time'))
            duration = data.get('duration_minutes') or data.get('duration')
            title = (data.get('title') or data.get('description') or "").strip()

            if not target or not start_t or (not end_t and not duration):
                db.close()
                return jsonify({'error': 'Missing date/start_time and end_time or duration_minutes'}), 400
            if not end_t and duration:
                try:
                    end_t = _add_minutes(start_t, int(duration))
                except Exception:
                    pass

            dur_min = int(duration) if duration else _duration_minutes(start_t, end_t)
            if not end_t or dur_min <= 0:
                db.close()
                return jsonify({'error': 'Invalid time window: ensure end_time is after start_time or provide a positive duration_minutes'}), 400

            created, conflicts = create_appointment_if_free(db, target, start_t, end_t, title)
            if created:
                db.close()
                return jsonify({'created': _serialize_appt(created)})

            day_appts = get_appointments_by_date(db, target)
            slot = _find_first_free_slot(day_appts, dur_min, _time(0,0), _time(23,59,59))
            props = _find_all_free_slots(day_appts, dur_min, _time(0,0), _time(23,59,59), limit=5)
            db.close()
            return jsonify({
                'error': 'Time slot conflicts with existing appointments',
                'conflicts': [_serialize_appt(c) for c in conflicts],
                'suggested_slot': {'start': slot[0].isoformat(), 'end': slot[1].isoformat()} if slot else None,
                'proposals': [
                    {'date': target.isoformat(),
                     'start_time': s.isoformat(),
                     'end_time': e.isoformat(),
                     'title': title or 'Proposed slot'}
                    for (s, e) in props
                ]
            }), 409

        if action == 'create_constraint':
            target = _to_date(data.get('date')) or today
            duration = int(data.get('duration_minutes') or 0)
            w_start = _to_time(data.get('window_start') or '00:00:00') or _time(0,0,0)
            w_end = _to_time(data.get('window_end') or '23:59:59') or _time(23,59,59)
            if _as_delta(w_start, w_end).total_seconds() <= 0:
                db.close()
                return jsonify({'error': 'window_start must be before window_end'}), 400
            title = (data.get('title') or data.get('description') or '').strip()

            if duration <= 0:
                db.close()
                return jsonify({'error': 'duration_minutes must be > 0'}), 400

            day_appts = get_appointments_by_date(db, target)
            slot = _find_first_free_slot(day_appts, duration, w_start, w_end)
            if not slot:
                db.close()
                return jsonify({'error': 'No free slot found in the requested window'}), 409

            start_t, end_t = slot
            created = create_appointment(db, target, start_t, end_t, title, allow_overlap=False)
            db.close()
            return jsonify({'created': _serialize_appt(created)})

        if action == 'create_recurring_simple':
            title = (data.get('title') or data.get('description') or '').strip()
            start_date = _to_date(data.get('start_date')) or today
            end_date = _to_date(data.get('end_date')) if data.get('end_date') else None
            count = int(data.get('count') or 0)
            count = max(1, min(count, 100))
            pattern = (data.get('pattern') or 'DAILY').upper()
            base_time = _to_time(data.get('time') or '09:00')
            duration = int(data.get('duration_minutes') or 30)
            interval = int(data.get('interval') or 1)
            by_weekdays = data.get('by_weekdays')
            wday = data.get('weekday')
            if duration <= 0:
                db.close()
                return jsonify({'error': 'duration_minutes must be > 0'}), 400

            if not title or not base_time:
                db.close()
                return jsonify({'error': 'Missing title/time or invalid duration'}), 400

            entries: List[dict] = []
            if end_date:
                for d in _iter_dates_range(
                    start_date, end_date,
                    pattern=pattern,
                    weekday=wday,
                    by_weekdays=by_weekdays,
                    interval=interval,
                ):
                    start_t = base_time
                    end_t = _add_minutes(base_time, duration)
                    if not find_conflicts_for_slot(db, d, start_t, end_t):
                        entries.append({
                            'date': d,
                            'start_time': start_t,
                            'end_time': end_t,
                            'description': title,
                        })
            else:
                cur = start_date
                made = 0
                while made < count:
                    if pattern == 'DAILY':
                        pass
                    elif pattern == 'WEEKDAYS':
                        if cur.weekday() >= 5:
                            cur += timedelta(days=1)
                            continue
                    elif pattern == 'WEEKLY':
                        want = wday
                        if want is not None and int(want) != cur.weekday():
                            cur += timedelta(days=1)
                            continue
                    else:
                        break

                    start_t = base_time
                    end_t = _add_minutes(base_time, duration)
                    if not find_conflicts_for_slot(db, cur, start_t, end_t):
                        entries.append({
                            'date': cur,
                            'start_time': start_t,
                            'end_time': end_t,
                            'description': title,
                        })
                        made += 1
                    cur += timedelta(days=1)

            created = bulk_create_appointments(db, entries, allow_overlap=True) if entries else []
            db.close()
            return jsonify({'created_many': [_serialize_appt(a) for a in created], 'requested': count})

        if action == 'create_from_template':
            if generate_template_blocks is None:
                db.close()
                return jsonify({'error': 'templates module not available'}), 400

            template_key = (data.get('template') or '').upper()
            anchor = _to_date(data.get('anchor_date')) or today
            options = data.get('options') or {}

            blocks = generate_template_blocks(template_key, anchor, options)
            if not blocks:
                db.close()
                return jsonify({'error': 'unknown or empty template'}), 400

            entries = []
            skipped = []
            for b in blocks:
                d = _to_date(b.get('date')) or anchor
                st = _to_time(b.get('start_time'))
                et = _to_time(b.get('end_time'))
                title = (b.get('title') or b.get('description') or '').strip()
                if not d or not st or not et:
                    continue
                if find_conflicts_for_slot(db, d, st, et):
                    skipped.append(b)
                    continue
                entries.append({'date': d, 'start_time': st, 'end_time': et, 'description': title})

            created = bulk_create_appointments(db, entries, allow_overlap=False) if entries else []
            db.close()
            return jsonify({
                'created_many': [_serialize_appt(a) for a in created],
                'skipped_conflicts': skipped
            })

        # ---- Reminders (structured) ----
        if action in {'reminder_create', 'create_reminder'}:
            date_ = _to_date(data.get('date')) or today
            time_ = _to_time(data.get('time') or data.get('at') or '09:00')
            title = (data.get('title') or data.get('description') or 'Reminder').strip()
            lead = int(data.get('lead_minutes') or data.get('lead') or 0)
            channel = (data.get('channel') or 'inapp').strip()
            if not time_:
                db.close()
                return jsonify({'error': 'Missing/invalid time'}), 400
            r = create_reminder(
                db,
                date_=date_,
                time_=time_,
                title=title,
                description=title,
                lead_minutes=lead,
                channel=channel
            )
            payload = _serialize_reminder(r, db)
            db.close()
            return jsonify({'reminder': payload})

        if action in {'reminder_for_appointment', 'create_reminder_for_appt'}:
            appt_id = data.get('appointment_id') or data.get('id')
            lead = int(data.get('lead_minutes') or data.get('lead') or 15)
            channel = (data.get('channel') or 'inapp').strip()
            if not appt_id:
                db.close()
                return jsonify({'error': 'Missing appointment id'}), 400
            appt = get_appointment_by_id(db, int(appt_id))
            if not appt:
                db.close()
                return jsonify({'error': 'Appointment not found'}), 404
            r = create_reminder_for_appointment(
                db,
                appt,
                lead_minutes=lead,
                title=appt.description or 'Upcoming appointment',
                channel=channel
            )
            payload = _serialize_reminder(r, db, appt=appt)
            db.close()
            return jsonify({'reminder': payload})

        if action in {'reminder_list', 'list_reminders'}:
            dr = _parse_date_range_param(data.get('date_range'))
            start = _to_date(data.get('start_date')) if not dr else dr[0]
            end   = _to_date(data.get('end_date'))   if not dr else dr[1]
            active = data.get('active')
            if isinstance(active, str):
                active = active.lower() in ('1', 'true', 'yes', 'y', 'on')
            search = (data.get('search') or data.get('term') or '').strip() or None
            rs = list_reminders(db, start_date=start, end_date=end, active=active, search=search)
            payload = [_serialize_reminder(r, db) for r in rs]
            db.close()
            return jsonify({'reminders': payload})

        if action in {'reminder_update'}:
            rid = data.get('id') or data.get('reminder_id')
            if not rid:
                db.close()
                return jsonify({'error': 'Missing reminder id'}), 400
            r = update_reminder(
                db,
                int(rid),
                date_=_to_date(data.get('date')),
                time_=_to_time(data.get('time')),
                title=(data.get('title') or '').strip() or None,
                description=(data.get('description') or '').strip() or None,
                lead_minutes=(data.get('lead_minutes') or data.get('lead')),
                channel=(data.get('channel') or None),
                active=(data.get('active') if data.get('active') is not None else None),
            )
            if not r:
                db.close()
                return jsonify({'error': 'Not found'}), 404
            payload = _serialize_reminder(r, db)
            db.close()
            return jsonify({'reminder': payload})

        if action in {'reminder_toggle'}:
            rid = data.get('id') or data.get('reminder_id')
            if not rid:
                db.close()
                return jsonify({'error': 'Missing reminder id'}), 400
            r = toggle_reminder(db, int(rid), active=data.get('active'))
            db.close()
            if not r:
                return jsonify({'error': 'Not found'}), 404
            return jsonify({'reminder': {'id': r.id, 'active': r.active}})

        if action in {'reminder_delete'}:
            rid = data.get('id') or data.get('reminder_id')
            if not rid:
                db.close()
                return jsonify({'error': 'Missing reminder id'}), 400
            ok = delete_reminder(db, int(rid))
            db.close()
            if ok:
                return jsonify({'deleted': True, 'id': int(rid)})
            return jsonify({'error': 'Not found'}), 404

        if action in {'reminders_due'}:
            # UI can poll this every ~60s to show in-app toasts
            due = get_due_reminders(db, now=_dt.now(_tz.utc))
            payload = [_serialize_reminder(r, db) for r in due]
            db.close()
            return jsonify({'due_reminders': payload})

        if action in {'reminder_mark_delivered'}:
            rid = data.get('id') or data.get('reminder_id')
            if not rid:
                db.close()
                return jsonify({'error': 'Missing reminder id'}), 400
            r = mark_reminder_delivered(db, int(rid))
            db.close()
            if not r:
                return jsonify({'error': 'Not found'}), 404
            return jsonify({'reminder': {'id': r.id, 'delivered': True}})

        if action in {'reminder_snooze'}:
            rid = data.get('id') or data.get('reminder_id')
            mins = int(data.get('minutes') or 10)
            if not rid:
                db.close()
                return jsonify({'error': 'Missing reminder id'}), 400
            r = snooze_reminder(db, int(rid), minutes=mins)
            if not r:
                db.close()
                return jsonify({'error': 'Not found'}), 404
            payload = _serialize_reminder(r, db)
            db.close()
            return jsonify({'reminder': payload})

        # ---- Retrieval/analytics actions ----
        if action == 'free':
            date_str = data.get('date')
            target = _to_date(date_str) or today
            appts = get_appointments_by_date(db, target)
            dur_req = int(data.get('duration_minutes') or data.get('duration') or 0)
            w_start = _to_time(data.get('window_start') or data.get('start_time') or '00:00:00') or _time(0,0,0)
            w_end = _to_time(data.get('window_end') or data.get('end_time') or '23:59:59') or _time(23,59,59)
            if dur_req > 0:
                props = _find_all_free_slots(appts, dur_req, w_start, w_end, limit=int(data.get('limit') or 5))
                proposals = [
                    {'date': target.isoformat(), 'start_time': s.isoformat(), 'end_time': e.isoformat(),
                     'title': data.get('title') or data.get('description') or 'Proposed slot'}
                    for (s, e) in props
                ]
                db.close()
                return jsonify({'proposals': proposals})
            db.close()
            return jsonify({'free': _compute_free_slots(appts)})

        if action == 'today':
            appts = get_appointments_by_date(db, today)

        elif action == 'this_week':
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            appts = get_appointments_for_week(db, start, end)

        elif action == 'next_upcoming':
            appt = get_next_appointment(db, today)
            db.close()
            return jsonify({'appointment': _serialize_appt(appt) if appt else None})

        elif action == 'search_description':
            term = (data.get('term') or '').strip()
            if not term:
                db.close()
                return jsonify({'error': 'Missing search term'}), 400
            appts = search_appointments_by_description(db, term)
            db.close()
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'list_by_date':
            target = _to_date(data.get('date'))
            if not target:
                db.close()
                return jsonify({'error': 'Missing or invalid date parameter'}), 400
            appts = get_appointments_by_date(db, target)
            db.close()
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'between_tomorrow':
            start_t = _to_time(data.get('start_time'))
            end_t = _to_time(data.get('end_time'))
            if not start_t or not end_t:
                db.close()
                return jsonify({'error': 'Missing or invalid start_time/end_time'}), 400
            tomorrow = today + timedelta(days=1)
            appts = crud_get_appointments_between(db, tomorrow, start_t, end_t)
            db.close()
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'weekend_month':
            year = int(data.get('year', today.year))
            month = int(data.get('month', today.month))
            appts = get_appointments_on_weekends(db, year, month)
            db.close()
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'after_time':
            threshold = _to_time(data.get('time') or '18:00:00')
            if not threshold:
                db.close()
                return jsonify({'error': 'Invalid time format'}), 400
            appts = get_appointments_after_time(db, today, threshold)
            db.close()
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'count_this_month':
            start_month = today.replace(day=1)
            next_month = (start_month.replace(year=start_month.year+1, month=1, day=1)
                          if start_month.month == 12 else
                          start_month.replace(month=start_month.month+1, day=1))
            end_month = next_month - timedelta(days=1)
            cnt = count_appointments_in_range(db, start_month, end_month)
            db.close()
            return jsonify({'count': cnt})

        elif action == 'conflicts':
            target = _to_date(data.get('date')) or today
            conflicts = get_conflicting_appointments(db, target)
            db.close()
            return jsonify({'conflicts': [
                [_serialize_appt(a) for a in pair] for pair in conflicts
            ]})

        else:
            db.close()
            return jsonify({'error': f'Unknown action "{action}"'}), 400

        serialized = [_serialize_appt(a) for a in appts]
        db.close()
        return jsonify({'appointments': serialized})

    # 2) Natural language + LLM router
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({'error': 'No query provided'}), 400

    q_lower = query.lower()

    # Reminders: quick NL paths
    if any(k in q_lower for k in ['remind me', 'notify me', 'alert me', 'ping me', 'nudge me']):
        db = SessionLocal()
        # date/time detection
        m_date = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', q_lower)
        target_date = _to_date(m_date.group(1)) if m_date else None
        m_time = re.search(r'\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', q_lower)
        target_time = _to_time(m_time.group(1)) if m_time else None
        if 'tomorrow' in q_lower and not target_date:
            target_date = _date.today() + timedelta(days=1)
        if 'today' in q_lower and not target_date:
            target_date = _date.today()
        lead = _parse_lead_from_text(q_lower) or 0
        # Task/title: anything after "to ..."
        m_task = re.search(r'\bto\s+(.+)$', query, flags=re.IGNORECASE)
        title = (m_task.group(1).strip() if m_task else 'Reminder')
        if target_time:
            r = create_reminder(
                db,
                date_=(target_date or _date.today()),
                time_=target_time,
                title=title,
                description=title,
                lead_minutes=lead,
                channel='inapp'
            )
            db.close()
            return jsonify({'reminder': _serialize_reminder(r, db)})
        # “before [meeting/title]”
        if 'before' in q_lower:
            lead2 = lead or 15
            # Find quoted text first
            qm = re.search(r'“([^”]+)”|"([^"]+)"|‘([^’]+)’|\'([^\']+)\'', query)
            needle = None
            if qm:
                for g in qm.groups():
                    if g:
                        needle = g
                        break
            if not needle:
                after_before = re.search(r'\bbefore\b\s+(.+)$', query, flags=re.IGNORECASE)
                if after_before:
                    needle = after_before.group(1).strip()
            window = get_appointments_for_week(db, _date.today(), _date.today() + timedelta(days=7))
            cand = [a for a in window if not needle or (needle.lower() in (a.description or '').lower())]
            cand.sort(key=lambda a: (a.date, a.start_time))
            appt = cand[0] if cand else None
            if appt:
                r = create_reminder_for_appointment(
                    db, appt, lead_minutes=lead2,
                    title=appt.description or 'Upcoming appointment',
                    channel='inapp'
                )
                db.close()
                return jsonify({'reminder': _serialize_reminder(r, db)})
        db.close()
        return jsonify({'error': 'Could not parse reminder time. Try “Remind me at 3pm to …”'}), 400

    # ---------- LLM-independent fast paths (work even if parse_query fails) ----------
    # Free/availability (with optional duration + time window in the text)
    if (
        'free' in q_lower or 'free time' in q_lower or 'availability' in q_lower or 'available' in q_lower or
        'open slot' in q_lower or 'open slots' in q_lower or 'free slot' in q_lower or 'free slots' in q_lower or 'avail' in q_lower
    ):
        db = SessionLocal()
        if 'tomorrow' in q_lower:
            target = _date.today() + timedelta(days=1)
        else:
            mdate = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', q_lower)
            target = _to_date(mdate.group(1)) if mdate else _date.today()
        appts = get_appointments_by_date(db, target)
        dur_req = _parse_duration_minutes_from_text(q_lower) or 0
        rng = _parse_time_range_text(q_lower)
        w_start = rng[0] if rng else _time(0,0,0)
        w_end   = rng[1] if rng else _time(23,59,59)
        if dur_req > 0:
            props = _find_all_free_slots(appts, int(dur_req), w_start, w_end, limit=5)
            db.close()
            return jsonify({'proposals': [
                {
                    'date': target.isoformat(),
                    'start_time': s.isoformat(),
                    'end_time': e.isoformat(),
                    'title': 'Proposed slot'
                }
                for (s, e) in props
            ]})
        free = _compute_free_slots(appts)
        db.close()
        return jsonify({'free': free})

    # "How many … this month?"
    if re.search(r'\bhow\s+many\b', q_lower) and 'month' in q_lower:
        db = SessionLocal()
        today = _date.today()
        start_month = today.replace(day=1)
        next_month = (start_month.replace(year=start_month.year+1, month=1, day=1)
                      if start_month.month == 12 else start_month.replace(month=start_month.month+1, day=1))
        end_month = next_month - timedelta(days=1)
        cnt = count_appointments_in_range(db, start_month, end_month)
        db.close()
        return jsonify({'count': cnt})

    # "After 6pm today …"
    m_after = re.search(r'\bafter\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)', q_lower)
    if m_after and 'today' in q_lower:
        db = SessionLocal()
        threshold = _to_time(m_after.group(1)) or _time(18,0,0)
        appts = get_appointments_after_time(db, _date.today(), threshold)
        db.close()
        return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

    # --- NL create fallback: "schedule/make/book an appointment ... at 5:40 [today/tomorrow/on ...]" ---
    if re.search(r'\b(schedule|make|create|book)\b.*\b(appointment|meeting)\b', q_lower):
        db = SessionLocal()
        # 1) date
        target = None
        if 'today' in q_lower:
            target = _date.today()
        elif 'tomorrow' in q_lower:
            target = _date.today() + timedelta(days=1)
        else:
            m_iso = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', q_lower)
            target = _to_date(m_iso.group(1)) if m_iso else _parse_human_date(query)

        # 2) time
        m_time = re.search(r'\b(?:at|@)\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b', q_lower)
        start_t = _to_time(m_time.group(1)) if m_time else None

        # 3) duration and title
        duration = _parse_duration_minutes_from_text(q_lower) or 60
        title = _extract_title_from_text(query) or 'New appointment'

        if not target or not start_t:
            db.close()
            return jsonify({
                'error': 'Missing date/time for create',
                'hint': 'Try: "Schedule an appointment today at 5:40 pm called Demo"'
            })

        end_t = _add_minutes(start_t, int(duration))
        created, conflicts = create_appointment_if_free(db, target, start_t, end_t, title)
        if created:
            db.close()
            return jsonify({'created': _serialize_appt(created)})

        # If conflict, suggest a few free options that day
        day_appts = get_appointments_by_date(db, target)
        props = _find_all_free_slots(day_appts, int(duration), _time(0,0,0), _time(23,59,59), limit=5)
        db.close()
        return jsonify({
            'error': 'Time slot conflicts with existing appointments',
            'proposals': [
                {'date': target.isoformat(), 'start_time': s.isoformat(), 'end_time': e.isoformat(), 'title': title or 'Proposed slot'}
                for (s, e) in props
            ]
        })

    # --- NEW: Spoken-style date like "29th August" / "Aug 29" ---
    human_d = _parse_human_date(query)
    if human_d and any(k in q_lower for k in ['appointment', 'appointments', 'meeting', 'meetings', 'what', 'show']):
        db = SessionLocal()
        appts = get_appointments_by_date(db, human_d)
        db.close()
        return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

    # "Show appointments on 2025-08-12"
    m_on = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', q_lower)
    if m_on and ('show' in q_lower or 'appointments' in q_lower or 'meeting' in q_lower):
        target = _to_date(m_on.group(1))
        if target:
            db = SessionLocal()
            appts = get_appointments_by_date(db, target)
            db.close()
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

    # Call LLM only after safety-nets
    try:
        llm = parse_query(query)
    except Exception as e:
        print("PARSE_ERROR:", e)
        llm = None

    if isinstance(llm, dict) and 'intent' in llm:
        intent = (llm.get('intent') or '').upper()
        params: Dict[str, Any] = llm.get('params') or {}
        db = SessionLocal()
        # Debug: observe what the router decided
        try:
            print("LLM_DEBUG:", {'intent': intent, 'params': params})
        except Exception:
            pass

        # Heuristic: answer free-time requests directly (with proposals if asked)
        if (
            'free' in q_lower or 'free time' in q_lower or 'availability' in q_lower or 'available' in q_lower or
            'open slot' in q_lower or 'open slots' in q_lower or 'free slot' in q_lower or 'free slots' in q_lower or 'avail' in q_lower
        ):
            if intent in {'RETRIEVE_TODAY', 'TODAY'}:
                target = _date.today()
            elif intent in {'RETRIEVE_TOMORROW', 'TOMORROW'}:
                target = _date.today() + timedelta(days=1)
            elif intent in {'RETRIEVE_DATE', 'ON_DATE'}:
                target = _to_date(params.get('date')) or _date.today()
            else:
                target = _to_date(params.get('date')) or _date.today()
            appts = get_appointments_by_date(db, target)
            want_proposals = ('propos' in q_lower) or ('option' in q_lower) or ('slot' in q_lower)
            dur_req = params.get('duration_minutes') or params.get('duration') or _parse_duration_minutes_from_text(q_lower) or 0
            rng = _parse_time_range_text(q_lower)
            w_start = _to_time(params.get('window_start') or params.get('start_time')) or (rng[0] if rng else _time(0,0,0))
            w_end = _to_time(params.get('window_end') or params.get('end_time')) or (rng[1] if rng else _time(23,59,59))
            if int(dur_req) > 0 and want_proposals:
                props = _find_all_free_slots(appts, int(dur_req), w_start, w_end, limit=5)
                proposals = [
                    {
                        'date': target.isoformat(),
                        'start_time': s.isoformat(),
                        'end_time': e.isoformat(),
                        'title': (params.get('title') or params.get('description') or 'Proposed slot')
                    }
                    for (s, e) in props
                ]
                db.close()
                return jsonify({'proposals': proposals})
            free = _compute_free_slots(appts)
            db.close()
            return jsonify({'free': free})

        # helper to close & jsonify
        def J(appts_list):
            db.close()
            return jsonify({'appointments': [_serialize_appt(a) for a in appts_list]})

        # ----- Creating intents (same as before) -----
        if intent in {'CREATE_SINGLE', 'CREATE', 'BOOK'}:
            target = _to_date(params.get('date'))
            start_t = _to_time(params.get('start_time') or params.get('time'))
            end_t = _to_time(params.get('end_time'))
            duration = params.get('duration_minutes') or params.get('duration')
            title = (params.get('title') or params.get('description') or '').strip()

            # If the user's text sounds like a *move/reschedule*, try to UPDATE an existing
            # appointment (by title) instead of creating a new one. This fixes cases where
            # the router returned CREATE for phrases like "move/reschedule/postpone".
            move_like = any(k in q_lower for k in ['move', 'reschedule', 'postpone', 'bring forward', 'shift', 'push back', 'pushback'])
            if move_like and title and target and start_t:
                try:
                    # Compute end if only duration provided.
                    end_for_update = end_t
                    if not end_for_update:
                        try:
                            dur_for_update = int(duration) if duration else 0
                        except Exception:
                            dur_for_update = 0
                        if dur_for_update <= 0 and start_t:
                            # fall back to 60 minutes if duration was not provided
                            dur_for_update = 60
                        end_for_update = _add_minutes(start_t, int(dur_for_update))

                    # Prefer a unique match *today* by title substring.
                    today_local = _date.today()
                    todays = get_appointments_by_date(db, today_local)
                    cand = [a for a in todays if title.lower() in (a.description or '').lower()]

                    chosen = None
                    if len(cand) == 1:
                        chosen = cand[0]
                    elif len(cand) == 0:
                        # Try in the next 7 days, pick the earliest upcoming by title.
                        win = get_appointments_for_week(db, today_local, today_local + timedelta(days=7))
                        cand2 = [a for a in win if title.lower() in (a.description or '').lower()]
                        if cand2:
                            cand2.sort(key=lambda a: (a.date, a.start_time))
                            chosen = cand2[0]

                    if chosen:
                        updated = update_appointment_time(
                            db,
                            appt_id=chosen.id,
                            date_=target,
                            start_time_=start_t,
                            end_time_=end_for_update,
                            allow_overlap=False,
                        )
                        if updated:
                            db.close()
                            return jsonify({'updated': _serialize_appt(updated)})
                except ValueError as e:
                    # Conflict while updating — return proposals just like the reschedule path.
                    dur_min = int(duration) if duration else (_duration_minutes(start_t, end_t) if (start_t and end_t) else 60)
                    day_appts = get_appointments_by_date(db, target)
                    props = _find_all_free_slots(day_appts, dur_min, _time(0,0,0), _time(23,59,59), limit=5)
                    db.close()
                    return jsonify({
                        'error': 'Updated time slot conflicts with existing appointments',
                        'details': str(e),
                        'proposals': [
                            {'date': target.isoformat(), 'start_time': s.isoformat(), 'end_time': e.isoformat()}
                            for (s, e) in props
                        ]
                    }), 409
                except Exception as e:
                    # If anything goes wrong, fall back to normal create flow below.
                    print('CREATE->RESCHEDULE bridge failed:', e)

            # If it still looks like a move but we couldn't identify the source, don't create a duplicate.
            if move_like:
                # Collect likely candidates to help the UI/user disambiguate instead of creating a new one.
                today_local = _date.today()
                window = get_appointments_for_week(
                    db,
                    today_local - timedelta(days=3),
                    today_local + timedelta(days=10)
                )
                cand3 = [a for a in window if title and title.lower() in (a.description or '').lower()]
                cand3.sort(key=lambda a: (a.date, a.start_time))
                out = [_serialize_appt(a) for a in cand3[:10]]
                db.close()
                if not cand3:
                    return jsonify({
                        'error': 'Could not find an existing appointment to move with that title.',
                        'hint': 'Tell me the original date/time or provide the appointment id.'
                    }), 404
                else:
                    return jsonify({
                        'error': 'Ambiguous source appointment for move.',
                        'candidates': out,
                        'hint': 'Specify which one (id, or date + time).'
                    }), 409

            if not target or not start_t or (not end_t and not duration):
                db.close()
                return jsonify({'error': 'Missing date/start_time and end_time or duration_minutes'}), 400
            if not end_t and duration:
                try:
                    end_t = _add_minutes(start_t, int(duration))
                except Exception:
                    pass

            dur_min = int(duration) if duration else _duration_minutes(start_t, end_t)
            if not end_t or dur_min <= 0:
                db.close()
                return jsonify({'error': 'Invalid time window: ensure end_time is after start_time or provide a positive duration_minutes'}), 400

            created, conflicts = create_appointment_if_free(db, target, start_t, end_t, title)
            if created:
                db.close()
                return jsonify({'created': _serialize_appt(created)})

            day_appts = get_appointments_by_date(db, target)
            slot = _find_first_free_slot(day_appts, dur_min, _time(0, 0), _time(23, 59, 59))
            db.close()
            return jsonify({
                'error': 'Time slot conflicts with existing appointments',
                'conflicts': [_serialize_appt(c) for c in conflicts],
                'suggested_slot': {'start': slot[0].isoformat(), 'end': slot[1].isoformat()} if slot else None
            }), 409

        # ----- MODIFYING / RESCHEDULING -----
        if intent in {'UPDATE_RESCHEDULE', 'RESCHEDULE', 'MOVE'}:
            # selector: by id OR by date + time (+ optional title)
            selector = params.get('selector') or {}
            print("RESCHEDULE_DEBUG selector=", selector, "params=", params)
            ci_opt, mr_opt = _match_opts(selector, params)
            appt = None

            # try id first
            sel_id = selector.get('id') or params.get('id')
            if sel_id:
                appt = get_appointment_by_id(db, int(sel_id))

            if not appt:
                sel_date = _to_date(selector.get('date') or params.get('date'))
                sel_start = _to_time(selector.get('start_time') or params.get('start_time'))
                sel_end = _to_time(selector.get('end_time') or params.get('end_time'))
                sel_title = (selector.get('title') or params.get('title') or '').strip() or None
                # narrow by date/time and fuzzy by title if given
                matches = find_appointments(
                    db,
                    target_date=sel_date,
                    term=sel_title,
                    start_time_=sel_start,
                    end_time_=sel_end,
                    case_insensitive=True if ci_opt is None else bool(ci_opt),
                    min_ratio=mr_opt if mr_opt is not None else 0.60,
                ) if sel_date else []
                appt = matches[0] if matches else None
                # Fallback exact-window match if not found (avoids parser quirks)
                if not appt and sel_date:
                    day_list = get_appointments_by_date(db, sel_date)
                    for a in day_list:
                        same_start = (sel_start is None) or (a.start_time == sel_start)
                        same_end = (sel_end is None) or (a.end_time == sel_end)
                        title_ok = (not sel_title) or _fuzzy_match(
                            (a.description or ''),
                            sel_title,
                            case_insensitive=True if ci_opt is None else bool(ci_opt),
                            min_ratio=mr_opt if mr_opt is not None else 0.60,
                        )
                        if same_start and same_end and title_ok:
                            appt = a
                            break

            # Fallback: if no date was provided, but we have a title, search today
            # then the next 7 days for the nearest matching appointment by title.
            if not appt:
                sel_title2 = (selector.get('title') or params.get('title') or '').strip() or None
                if sel_title2:
                    today_local = _date.today()
                    todays = get_appointments_by_date(db, today_local)
                    cand = [a for a in todays if sel_title2.lower() in (a.description or '').lower()]
                    if len(cand) == 1:
                        appt = cand[0]
                    elif len(cand) == 0:
                        win = get_appointments_for_week(db, today_local, today_local + timedelta(days=7))
                        cand2 = [a for a in win if sel_title2.lower() in (a.description or '').lower()]
                        if cand2:
                            cand2.sort(key=lambda a: (a.date, a.start_time))
                            appt = cand2[0]

            if not appt:
                db.close()
                return jsonify({'error': 'No matching appointment found to reschedule.'}), 404

            # Compute target window using unified helper (preserve duration safely)
            req_new_date  = _to_date(params.get('new_date') or params.get('date'))
            req_new_start = _to_time(params.get('new_start_time') or params.get('new_start') or params.get('time'))
            req_new_end   = _to_time(params.get('new_end_time')   or params.get('new_end'))
            target_date, target_start, target_end = _resolve_reschedule_times(appt, req_new_date, req_new_start, req_new_end)

            try:
                updated = update_appointment_time(
                    db,
                    appt_id=appt.id,
                    date_=target_date,
                    start_time_=target_start,
                    end_time_=target_end,
                    allow_overlap=False,
                )
                if not updated:
                    db.close()
                    return jsonify({'error': 'Update failed'}), 400
                db.close()
                return jsonify({'updated': _serialize_appt(updated)})
            except ValueError as e:
                print("RESCHEDULE_DEBUG conflict:", e)
                base_dur = _duration_minutes(appt.start_time, appt.end_time)
                dur_min = _duration_minutes(target_start, target_end) if (target_start and target_end) else (base_dur if base_dur > 0 else 60)
                day_appts = get_appointments_by_date(db, target_date)
                props = _find_all_free_slots(day_appts, dur_min, _time(0,0,0), _time(23,59,59), limit=5)
                db.close()
                return jsonify({
                    'error': 'Updated time slot conflicts with existing appointments',
                    'details': str(e),
                    'proposals': [
                        {'date': target_date.isoformat(), 'start_time': s.isoformat(), 'end_time': e.isoformat()}
                        for (s, e) in props
                    ]
                }), 409
            except Exception as e:
                print("RESCHEDULE_DEBUG failure:", e)
                db.close()
                return jsonify({'error': 'Update failed', 'details': str(e)}), 500

        if intent in {'UPDATE_TITLE', 'UPDATE_RENAME', 'RENAME', 'CHANGE_TITLE'}:
            selector = params.get('selector') or {}
            ci_opt, mr_opt = _match_opts(selector, params)
            new_title = (params.get('new_title') or params.get('title') or '').strip()
            if not new_title:
                db.close()
                return jsonify({'error': 'Missing new title'}), 400

            appt = None
            sel_id = selector.get('id') or params.get('id')
            if sel_id:
                appt = get_appointment_by_id(db, int(sel_id))
            if not appt:
                sel_date = _to_date(selector.get('date') or params.get('date'))
                sel_start = _to_time(selector.get('start_time') or params.get('start_time'))
                sel_end = _to_time(selector.get('end_time') or params.get('end_time'))
                sel_title = (selector.get('title') or params.get('title') or params.get('old_title') or '').strip() or None

                matches = find_appointments(
                    db,
                    target_date=sel_date,
                    term=sel_title,
                    start_time_=sel_start,
                    end_time_=sel_end,
                    case_insensitive=True if ci_opt is None else bool(ci_opt),
                    min_ratio=mr_opt if mr_opt is not None else 0.60,
                ) if sel_date else []
                appt = matches[0] if matches else None

                # Fallback: if date was missing or we still have no hit, search today and the next 7 days by fuzzy title
                if not appt and sel_title:
                    today_local = _date.today()
                    # today
                    todays = get_appointments_by_date(db, today_local)
                    cand = [a for a in todays if _fuzzy_match(
                        a.description or '',
                        sel_title,
                        case_insensitive=True if ci_opt is None else bool(ci_opt),
                        min_ratio=mr_opt if mr_opt is not None else 0.60,
                    )]
                    if len(cand) == 1:
                        appt = cand[0]
                    if not appt:
                        win = get_appointments_for_week(db, today_local, today_local + timedelta(days=7))
                        cand2 = [a for a in win if _fuzzy_match(
                            a.description or '',
                            sel_title,
                            case_insensitive=True if ci_opt is None else bool(ci_opt),
                            min_ratio=mr_opt if mr_opt is not None else 0.60,
                        )]
                        if cand2:
                            cand2.sort(key=lambda a: (a.date, a.start_time))
                            appt = cand2[0]

            if not appt:
                db.close()
                return jsonify({'error': 'No matching appointment found to rename.'}), 404

            updated = update_appointment_title(db, appt.id, new_title)
            db.close()
            return jsonify({'updated': _serialize_appt(updated) if updated else None})

        if intent in {'MOVE_DAY_ALL', 'MOVE_DAY', 'MOVE_ALL_FROM_DATE'}:
            from_date = _to_date(params.get('from_date') or params.get('date'))
            to_date = _to_date(params.get('to_date') or params.get('new_date'))
            if not from_date or not to_date:
                db.close()
                return jsonify({'error': 'Missing from_date/to_date'}), 400
            updated, skipped = move_day_appointments(db, from_date, to_date, keep_times=True)
            db.close()
            return jsonify({
                'moved': [_serialize_appt(a) for a in updated],
                'skipped_conflicts': [_serialize_appt(a) for a in skipped],
            })

        if intent in {'CONVERT_TO_RECURRING', 'MAKE_RECURRING'}:
            # very simple: take a selected appointment and create weekly copies
            selector = params.get('selector') or {}
            count = int(params.get('count') or 6)
            appt = None
            sel_id = selector.get('id') or params.get('id')
            if sel_id:
                appt = get_appointment_by_id(db, int(sel_id))
            if not appt:
                sel_date = _to_date(selector.get('date') or params.get('date'))
                sel_start = _to_time(selector.get('start_time') or params.get('start_time'))
                sel_end = _to_time(selector.get('end_time') or params.get('end_time'))
                matches = find_appointments(db, target_date=sel_date, start_time_=sel_start, end_time_=sel_end) if sel_date else []
                appt = matches[0] if matches else None
            if not appt:
                db.close()
                return jsonify({'error': 'No matching appointment to convert.'}), 404

            duration = _duration_minutes(appt.start_time, appt.end_time)
            entries = []
            d = appt.date
            made = 0
            while made < max(0, count - 1):  # exclude original
                d = d + timedelta(days=7)
                if not find_conflicts_for_slot(db, d, appt.start_time, appt.end_time):
                    entries.append({
                        'date': d,
                        'start_time': appt.start_time,
                        'end_time': _add_minutes(appt.start_time, duration),
                        'description': appt.description,
                    })
                    made += 1
            created = bulk_create_appointments(db, entries, allow_overlap=False) if entries else []
            db.close()
            return jsonify({'created_many': [_serialize_appt(a) for a in created], 'base': _serialize_appt(appt)})

        # ----- CANCELLING / DELETING -----
        if intent in {'CANCEL_SINGLE', 'DELETE_SINGLE', 'DELETE'}:
            selector = params.get('selector') or {}
            ci_opt, mr_opt = _match_opts(selector, params)
            appt = None
            sel_id = selector.get('id') or params.get('id')
            if sel_id:
                appt = get_appointment_by_id(db, int(sel_id))
            if not appt:
                sel_date = _to_date(selector.get('date') or params.get('date'))
                sel_start = _to_time(selector.get('start_time') or params.get('start_time'))
                sel_end = _to_time(selector.get('end_time') or params.get('end_time'))
                sel_title = (selector.get('title') or params.get('title') or '').strip() or None
                matches = find_appointments(
                    db,
                    target_date=sel_date,
                    term=sel_title,
                    start_time_=sel_start,
                    end_time_=sel_end,
                    case_insensitive=True if ci_opt is None else bool(ci_opt),
                    min_ratio=mr_opt if mr_opt is not None else 0.60,
                ) if sel_date else []
                appt = matches[0] if matches else None
            if not appt:
                db.close()
                return jsonify({'error': 'No matching appointment found to delete.'}), 404

            ok = delete_appointment_by_id(db, appt.id)
            db.close()
            return jsonify({'deleted': bool(ok), 'id': appt.id})

        if intent in {'DELETE_ON_DATE', 'CANCEL_ON_DATE'}:
            target = _to_date(params.get('date')) or _date.today()
            term = (params.get('term') or params.get('title') or '').strip() or None
            victims = delete_on_date(db, target, term=term)
            db.close()
            return jsonify({'deleted_many': [_serialize_appt(a) for a in victims]})

        if intent in {'DELETE_BY_TERM', 'DELETE_BY_TEXT'}:
            term = (params.get('term') or params.get('title') or '').strip()
            if not term:
                db.close()
                return jsonify({'error': 'Missing term'}), 400
            victims = delete_by_search(db, term)
            db.close()
            return jsonify({'deleted_many': [_serialize_appt(a) for a in victims]})

        if intent in {'DELETE_BY_LABEL'}:
            label = (params.get('label') or '').strip()
            if not label:
                db.close()
                return jsonify({'error': 'Missing label'}), 400
            victims = delete_by_label(db, label)
            db.close()
            return jsonify({'deleted_many': [_serialize_appt(a) for a in victims]})

        # ----- Retrieval intents (unchanged) -----
        if intent in {'RETRIEVE_TODAY', 'TODAY'}:
            return J(get_appointments_by_date(db, _date.today()))

        if intent in {'RETRIEVE_TOMORROW', 'TOMORROW'}:
            return J(get_appointments_by_date(db, _date.today() + timedelta(days=1)))

        if intent in {'RETRIEVE_WEEK', 'THIS_WEEK'}:
            today = _date.today()
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            return J(get_appointments_for_week(db, start, end))

        if intent in {'RETRIEVE_NEXT_WEEK', 'NEXT_WEEK'}:
            today = _date.today()
            this_mon = today - timedelta(days=today.weekday())
            next_mon = this_mon + timedelta(days=7)
            next_sun = next_mon + timedelta(days=6)
            return J(get_appointments_for_week(db, next_mon, next_sun))

        if intent in {'RETRIEVE_MONTH', 'THIS_MONTH', 'LIST_MONTH'}:
            today = _date.today()
            year = int(params.get('year', today.year))
            month = int(params.get('month', today.month))
            m_start, m_end = _month_bounds(year, month)
            return J(get_appointments_for_week(db, m_start, m_end))

        if intent in {'RETRIEVE_MONTH_TZ', 'THIS_MONTH_TZ'}:
            today = _date.today()
            year = int(params.get('year', today.year))
            month = int(params.get('month', today.month))
            tz = _normalize_tz((params.get('timezone') or params.get('tz') or '').strip())
            m_start, m_end = _month_bounds(year, month)
            if not tz:
                return J(get_appointments_for_week(db, m_start, m_end))
            noon = _time(12, 0, 0)
            local_start, _ = _tz_to_local_date_time(m_start, noon, tz)
            local_end, _ = _tz_to_local_date_time(m_end, noon, tz)
            if local_end < local_start:
                local_start, local_end = local_end, local_start
            return J(get_appointments_for_week(db, local_start, local_end))

        if intent in {'RETRIEVE_DATE', 'ON_DATE'}:
            target = _to_date(params.get('date')) or _date.today()
            return J(get_appointments_by_date(db, target))

        if intent in {'RETRIEVE_BETWEEN', 'BETWEEN_TIMES'}:
            target = _to_date(params.get('date')) or _date.today()
            start_t = _to_time(params.get('start_time')) or _time(0, 0)
            end_t = _to_time(params.get('end_time')) or _time(23, 59, 59)

            dr = _parse_date_range_param(params.get('date_range'))
            if dr:
                start_d, end_d = dr
                return J(get_appointments_for_week(db, start_d, end_d))

            if 'next 24' in q_lower.replace('hours', 'h') or 'next24' in q_lower.replace(' ', ''):
                now_dt = _dt.now().replace(microsecond=0)
                end_dt = now_dt + timedelta(hours=24)
                appts = get_appointments_for_week(db, now_dt.date(), end_dt.date())
                win = []
                for a in appts:
                    a_start = _dt_combine(a.date, a.start_time)
                    a_end = _dt_combine(a.date, a.end_time)
                    if a_end > now_dt and a_start < end_dt:
                        win.append(a)
                return J(win)

            if end_t <= start_t:
                day_end = _time(23, 59, 59)
                day_start = _time(0, 0, 0)
                part1 = crud_get_appointments_between(db, target, start_t, day_end)
                part2 = crud_get_appointments_between(db, target + timedelta(days=1), day_start, end_t)
                seen = set()
                merged = []
                for a in part1 + part2:
                    if a.id not in seen:
                        seen.add(a.id)
                        merged.append(a)
                return J(merged)

            return J(crud_get_appointments_between(db, target, start_t, end_t))

        if intent in {'RETRIEVE_NOW', 'NOW', 'CURRENT', 'ONGOING', 'RIGHT_NOW', 'CURRENTLY'}:
            today = _date.today()
            now_t = _dt.now().time().replace(microsecond=0)
            todays = get_appointments_by_date(db, today)
            ongoing = [a for a in todays if a.start_time <= now_t < a.end_time]
            return J(ongoing)

        if intent in {'RETRIEVE_NEXT_24H', 'NEXT_24H', 'ROLLING_DAY'}:
            now_dt = _dt.now().replace(microsecond=0)
            end_dt = now_dt + timedelta(hours=24)
            appts = get_appointments_for_week(db, now_dt.date(), end_dt.date())
            win = []
            for a in appts:
                a_start = _dt_combine(a.date, a.start_time)
                a_end = _dt_combine(a.date, a.end_time)
                if a_end > now_dt and a_start < end_dt:
                    win.append(a)
            return J(win)

        if intent in {'RETRIEVE_BETWEEN_TZ', 'BETWEEN_TZ', 'RETRIEVE_DATE_TZ', 'ON_DATE_TZ'}:
            tz = _normalize_tz((params.get('timezone') or params.get('tz') or '').strip())
            target = _to_date(params.get('date')) or _date.today()
            dr = _parse_date_range_param(params.get('date_range'))
            if dr:
                s, e = dr
                if tz:
                    noon = _time(12, 0, 0)
                    s_local, _ = _tz_to_local_date_time(s, noon, tz)
                    e_local, _ = _tz_to_local_date_time(e, noon, tz)
                    if e_local < s_local:
                        s_local, e_local = e_local, s_local
                    return J(get_appointments_for_week(db, s_local, e_local))
                else:
                    return J(get_appointments_for_week(db, s, e))
            st = _to_time(params.get('start_time')) if params.get('start_time') else None
            et = _to_time(params.get('end_time')) if params.get('end_time') else None
            if not tz:
                if st and et:
                    if et <= st:
                        day_end = _time(23, 59, 59)
                        day_start = _time(0, 0, 0)
                        part1 = crud_get_appointments_between(db, target, st, day_end)
                        part2 = crud_get_appointments_between(db, target + timedelta(days=1), day_start, et)
                        seen = set()
                        merged = []
                        for a in part1 + part2:
                            if a.id not in seen:
                                seen.add(a.id)
                                merged.append(a)
                        return J(merged)
                    return J(crud_get_appointments_between(db, target, st, et))
                else:
                    if 'month' in q_lower:
                        today = _date.today()
                        m_start, m_end = _month_bounds(today.year, today.month)
                        return J(get_appointments_for_week(db, m_start, m_end))
                    return J(get_appointments_by_date(db, target))
            if st and et:
                ld, lt = _tz_to_local_date_time(target, st, tz)
                rd, rt = _tz_to_local_date_time(target, et, tz)
                if ld == rd:
                    return J(crud_get_appointments_between(db, ld, lt, rt))
                else:
                    day_end = _time(23, 59, 59)
                    day_start = _time(0, 0, 0)
                    part1 = crud_get_appointments_between(db, ld, lt, day_end)
                    part2 = crud_get_appointments_between(db, rd, day_start, rt)
                    seen = set()
                    merged = []
                    for a in part1 + part2:
                        if a.id not in seen:
                            seen.add(a.id)
                            merged.append(a)
                    return J(merged)
            else:
                noon = _time(12, 0, 0)
                local_date, _ = _tz_to_local_date_time(target, noon, tz)
                return J(get_appointments_by_date(db, local_date))

        if intent in {'RETRIEVE_RANGE', 'DATE_RANGE', 'RANGE'}:
            start = _to_date(params.get('start_date') or params.get('from'))
            end = _to_date(params.get('end_date') or params.get('to'))
            if not start or not end:
                db.close()
                return jsonify({'error': 'Missing start_date/end_date'}), 400
            if start > end:
                start, end = end, start
            return J(get_appointments_for_week(db, start, end))

        if intent in {'RETRIEVE_NEXT_72H', 'NEXT_72H', 'NEXT_3_DAYS'}:
            start = _date.today()
            end = start + timedelta(days=2)
            return J(get_appointments_for_week(db, start, end))

        if intent in {'COUNT_WEEK', 'RETRIEVE_COUNT_WEEK'}:
            today = _date.today()
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            cnt = count_appointments_in_range(db, start, end)
            db.close()
            return jsonify({'count': cnt})

        if 'WEEKEND' in intent:
            today = _date.today()
            year = int(params.get('year', today.year))
            month = int(params.get('month', today.month))
            return J(get_appointments_on_weekends(db, year, month))

        if 'AFTER_TIME' in intent or intent == 'AFTER':
            today = _date.today()
            threshold = _to_time(params.get('time')) or _time(18, 0)
            return J(get_appointments_after_time(db, today, threshold))

        if 'NEXT_UPCOMING' in intent or intent == 'NEXT':
            appt = get_next_appointment(db, _date.today())
            db.close()
            return jsonify({'appointment': _serialize_appt(appt) if appt else None})

        if 'COUNT_MONTH' in intent or ('COUNT' in intent and 'MONTH' in (params.get('scope', '') or '').upper()):
            today = _date.today()
            start_month = today.replace(day=1)
            next_month = (start_month.replace(year=start_month.year+1, month=1, day=1)
                          if start_month.month == 12 else
                          start_month.replace(month=start_month.month+1, day=1))
            end_month = next_month - timedelta(days=1)
            cnt = count_appointments_in_range(db, start_month, end_month)
            db.close()
            return jsonify({'count': cnt})

        if 'SEARCH' in intent or 'DESCRIPTION' in intent:
            term = (params.get('term') or '').strip()
            appts = search_appointments_by_description(db, term) if term else []
            return J(appts)

        if 'FREE_TIME' in intent or 'FREE' in intent or 'AVAIL' in intent:
            target = _to_date(params.get('date')) or _date.today()
            appts = get_appointments_by_date(db, target)
            free = _compute_free_slots(appts)
            db.close()
            return jsonify({'free': free})

        if 'CONFLICT' in intent or 'OVERLAP' in intent:
            target = _to_date(params.get('date')) or _date.today()
            conflicts = get_conflicting_appointments(db, target)
            db.close()
            return jsonify({'conflicts': [[_serialize_appt(a) for a in pair] for pair in conflicts]})

        db.close()

    # --- legacy tuple path ---
    date_obj, start_time, end_time = llm if isinstance(llm, tuple) and len(llm) == 3 else (None, None, None)
    if date_obj:
        db = SessionLocal()
        if start_time and end_time:
            appts = crud_get_appointments_between(db, date_obj, start_time, end_time)
        else:
            appts = get_appointments_by_date(db, date_obj)
        db.close()
        return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

    # --- robust naive fallback for recurring weekly phrases (now supports "at 7pm for 30 minutes") ---
    wdays = _parse_weekday_list(query)
    time_rng = _parse_time_range_text(query)
    dr_m = _parse_month_day_range_text(query)
    title_m = re.search(r"(?:title|called|named)\s*[\"']?([^\"']+)[\"']?", query, flags=re.IGNORECASE)

    # Also accept "at 7pm" + duration ("for 30 minutes") as a time spec
    at_m = re.search(r"\bat\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b", q_lower)
    st = et = None
    if time_rng:
        st, et = time_rng
    else:
        if at_m:
            st_candidate = _to_time(at_m.group(1))
            dur = _parse_duration_minutes_from_text(q_lower) or 0
            if st_candidate and dur > 0:
                st = st_candidate
                et = _add_minutes(st_candidate, int(dur))

    if wdays and dr_m and st and et:
        s_date, e_date = dr_m
        title = title_m.group(1).strip() if title_m else 'Untitled'

        db = SessionLocal()
        entries: List[dict] = []
        for d in _iter_dates_range(s_date, e_date, pattern='WEEKLY', by_weekdays=wdays):
            if not find_conflicts_for_slot(db, d, st, et):
                entries.append({'date': d, 'start_time': st, 'end_time': et, 'description': title})
        created = bulk_create_appointments(db, entries, allow_overlap=True) if entries else []
        db.close()
        return jsonify({'created_many': [_serialize_appt(a) for a in created], 'requested': len(entries), 'mode': 'fallback_recurring'})

    # Final fallback — no hard error code; include hint for the UI
    return jsonify({
        'error': 'Unable to parse query',
        'hint': 'Examples: "What appointments do I have on 28 Aug", "Schedule an appointment today at 5:40 pm called Demo".'


    })



if __name__ == '__main__':
    app.run(debug=True)
