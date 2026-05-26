"""
nl_creation_flow.py

Natural-language → structured creation payloads for Scheduler API.

This module is designed to ALIGN with app.py's expectations:

- For single events, it produces payloads like:
    {
        "action": "create",
        "date": "2025-08-12",
        "start_time": "17:40:00",
        "duration_minutes": 60,
        "title": "Demo"
    }

- For recurring events, it produces:
    {
        "action": "create_recurring_simple",  # or create_recurring_preview
        "title": "Demo",
        "start_date": "2025-08-01",
        "end_date": "2025-08-31",
        "pattern": "WEEKLY",
        "by_weekdays": [3],       # 0=Mon..6=Sun
        "time": "18:00:00",
        "duration_minutes": 60,
        "interval": 1
    }

You can POST these payloads directly to /query on your Flask app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as _date, time as _time, datetime as _dt, timedelta
from typing import Any, Dict, List, Optional, Tuple


# ---------- basic helpers (mirroring app.py style) ----------

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
        try:
            return _time(hh, mm, ss)
        except Exception:
            return None
    return None


def _add_minutes(t: _time, minutes: int) -> _time:
    base = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
    res = base + timedelta(minutes=minutes)
    total_seconds = int(res.total_seconds())
    hh = (total_seconds // 3600) % 24
    mm = (total_seconds % 3600) // 60
    ss = total_seconds % 60
    return _time(hh, mm, ss)


# ---- month/weekday maps (match app.py) ----

_month_map = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_weekday_map = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


def _parse_month_name_token(tok: str) -> Optional[int]:
    if not tok:
        return None
    return _month_map.get(tok.strip().lower())


# ---------- human date parsing (mirrors _parse_human_date in app.py) ----------

def _strip_ordinals_local(s: str) -> str:
    s = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _parse_human_date(text: str, *, reference: Optional[_date] = None) -> Optional[_date]:
    """
    Parse spoken-ish dates like:
      - "29th August"
      - "Aug 29"
      - "Aug 29, 2025"
      - "29 Aug 2025"
      - "on the 28th of August"
    If year is missing, assume reference.year (default = today).
    """
    if not text:
        return None
    reference = reference or _date.today()
    t = _strip_ordinals_local(text.strip().lower())
    mon_pat = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

    # Pattern A: "28 august [2025]" and "on the 28 of august"
    m = re.search(
        rf"\b(?:on\s+the\s+|on\s+)?(\d{{1,2}})\s+(?:of\s+)?{mon_pat}(?:\s+(\d{{4}}))?\b",
        t,
        flags=re.IGNORECASE,
    )
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
    m = re.search(
        rf"\b{mon_pat}\s+(\d{{1,2}})(?:,\s*(\d{{4}}))?\b",
        t,
        flags=re.IGNORECASE,
    )
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


# ---------- time & duration in text ----------

def _parse_time_range_text(text: str) -> Optional[Tuple[_time, _time]]:
    if not text:
        return None
    tl = text.lower()
    m = re.search(
        r"\bfrom\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\s*(?:-|to|–|—)\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b",
        tl,
    )
    if not m:
        m = re.search(
            r"\bbetween\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\s*(?:and|to)\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b",
            tl,
        )
    if not m:
        m = re.search(
            r"\b([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\s*(?:-|to|–|—)\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b",
            tl,
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

    # 3) Minutes: "60 minutes", "60-minute", "90min", "90 m"
    m = re.search(r"(\d+)\s*[-\s]?(?:minutes?|mins?|m)\b", tl)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None

    # 4) Hour compact: "1hr", "2 hrs"
    m = re.search(r"(\d+)\s*[-\s]?(?:hr|hrs)\b", tl)
    if m:
        try:
            return int(m.group(1)) * 60
        except Exception:
            return None

    # 5) Verbal forms
    if re.search(r"\b(an|one)\s+hour\b", tl):
        return 60
    if re.search(r"\bhalf[-\s]+an?\s+hour\b", tl) or re.search(
        r"\ban?\s+half[-\s]+hour\b", tl
    ):
        return 30
    if re.search(r"\b(one|1)\s+and\s+a\s+half\s+hours?\b", tl) or re.search(
        r"\ban?\s+hour\s+and\s+a\s+half\b", tl
    ):
        return 90

    return None


# ---------- weekday & range parsing (aligned with app.py recurring logic) ----------

def _parse_weekday_list(text: str) -> List[int]:
    if not text:
        return []
    tl = text.lower()
    if "every" not in tl and "each" not in tl:
        return []
    # General scan for weekday names
    toks = re.findall(
        r"\b(mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
        tl,
    )
    wdays: List[int] = []

    # support "weekdays" / "weekends"
    if re.search(r"\bweekdays?\b", tl):
        wdays.extend([0, 1, 2, 3, 4])
    if re.search(r"\bweekends?\b", tl):
        wdays.extend([5, 6])

    for tok in toks:
        key = tok.lower()
        if key in _weekday_map:
            w = _weekday_map[key]
        else:
            key3 = key[:3]
            w = _weekday_map.get(key3)
        if w is not None and w not in wdays:
            wdays.append(w)

    order = [0, 1, 2, 3, 4, 5, 6]
    wset = set(wdays)
    return [w for w in order if w in wset]


def _parse_month_day_range_text(text: str) -> Optional[Tuple[_date, _date]]:
    """
    Match phrases like:
        "from Oct 1 to Oct 31"
        "between September 5 and Oct 10"
    (Year assumed = current year if missing)
    """
    if not text:
        return None

    patterns = [
        r"\bfrom\s+([a-zA-Z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|through|thru|until|till|and)\s*([a-zA-Z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b",
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


# ---------- title extraction (same style as app.py's _extract_title_from_text) ----------

def _extract_title_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(
        r"(?:with\s+the\s+title|with\s+title|titled|called|named)\s+[“\"]?([^\"”]+?)[”\"]?(?:\s|$)",
        text,
        flags=re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def _fallback_title(text: str) -> str:
    """
    Fallback: if nothing like "with the title X" is present,
    try to grab something after the word 'called' or 'title'.
    If nothing, return 'New appointment'.
    """
    t = text.strip()
    m = re.search(
        r"\btitle\s+([^\n]+?)(?:[.!?,]\s*|$)",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().strip('\'"“”‘’')
    m2 = re.search(
        r"\bcalled\s+([^\n]+?)(?:[.!?,]\s*|$)",
        t,
        flags=re.IGNORECASE,
    )
    if m2:
        return m2.group(1).strip().strip('\'"“”‘’')
    return "New appointment"


# ---------- dataclasses for structured outputs ----------

@dataclass
class CreationPayload:
    action: str
    body: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.body)
        d["action"] = self.action
        return d


# ---------- SINGLE APPOINTMENT CREATION ----------

def build_single_creation_payload(query: str, *, default_duration: int = 60) -> CreationPayload:
    """
    Build a /query payload for a ONE-OFF appointment.

    Returns CreationPayload(action="create", body={...}) with keys:
      - date (YYYY-MM-DD)
      - start_time (HH:MM:SS)
      - duration_minutes
      - title

    This mirrors app.py's 'create' structured block and NL fast-path.
    """
    q = (query or "").strip()
    q_lower = q.lower()
    today = _date.today()

    # 1) date
    target: Optional[_date] = None
    if "today" in q_lower:
        target = today
    elif "tomorrow" in q_lower:
        target = today + timedelta(days=1)
    else:
        # ISO date in text
        m_iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", q_lower)
        if m_iso:
            target = _to_date(m_iso.group(1))
        if not target:
            # human-ish date
            target = _parse_human_date(q)

    # 2) start time
    m_time = re.search(
        r"\b(?:at|@)\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b",
        q_lower,
    )
    start_t = _to_time(m_time.group(1)) if m_time else None

    # 3) duration
    duration = _parse_duration_minutes_from_text(q) or default_duration

    # 4) title
    title = _extract_title_from_text(q) or _fallback_title(q)
    title = title.strip().strip('\'"“”‘’').strip()
    if not title:
        title = "New appointment"

    # If any required piece is missing, we still return a structured payload
    # but the caller can choose to handle 'None' values.
    body: Dict[str, Any] = {
        "date": target.isoformat() if target else None,
        "start_time": start_t.isoformat() if start_t else None,
        "duration_minutes": int(duration),
        "title": title,
    }
    return CreationPayload(action="create", body=body)


# ---------- RECURRING CREATION ----------

def _parse_weeks_and_occurrences(q_lower: str) -> Tuple[int, int]:
    """
    Parse "for 4 weeks" and "for 6 occurrences".
    Returns (weeks_count, occurrences_count).
    """
    weeks_count = 0
    occ_count = 0

    m_weeks = re.search(r"\b(?:for|up\s*to|upto|next)\s+(\d+)\s+weeks?\b", q_lower)
    if m_weeks:
        try:
            weeks_count = max(1, int(m_weeks.group(1)))
        except Exception:
            weeks_count = 0

    m_occ = re.search(r"\bfor\s+(\d+)\s+(?:occurrence|occurrences|times)\b", q_lower)
    if m_occ:
        try:
            occ_count = max(1, int(m_occ.group(1)))
        except Exception:
            occ_count = 0

    return weeks_count, occ_count


def build_recurring_creation_payload(
    query: str,
    *,
    default_duration: int = 60,
    preview_only: Optional[bool] = None,
) -> CreationPayload:
    """
    Build a /query payload for a RECURRING appointment.

    Returns CreationPayload(action="create_recurring_simple" or
    "create_recurring_preview", body={...}) with keys aligned to:

      action: create_recurring_simple / create_recurring_preview
      body:
        title
        start_date (YYYY-MM-DD)
        end_date (YYYY-MM-DD)  [optional if count/weeks used]
        pattern: DAILY | WEEKLY | WEEKDAYS
        by_weekdays: [0..6]    [if weekly]
        weekday: int           [optional shorthand]
        time: "HH:MM:SS"
        duration_minutes
        interval

    The parsing logic is consistent with your app.py recurring NL fast-paths.
    """
    q = (query or "").strip()
    q_lower = q.lower()
    today = _date.today()

    # Decide preview mode
    if preview_only is None:
        preview_only = "preview" in q_lower

    # Weekdays / "every ..."
    by_weekdays = _parse_weekday_list(q)

    # Time: "at 6 pm" or "at 18:00" or "8 pm"
    time_rng = _parse_time_range_text(q)
    st: Optional[_time] = None
    et: Optional[_time] = None

    if time_rng:
        st, et = time_rng
    else:
        at_m = re.search(
            r"\b(?:at\s*|@)?\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm))\b",
            q_lower,
        ) or re.search(
            r"\b([0-9]{1,2})(?::([0-9]{2}))?(am|pm)\b",
            q_lower,
        )
        if at_m:
            st_candidate = _to_time(at_m.group(1))
            dur = _parse_duration_minutes_from_text(q) or default_duration
            if st_candidate:
                st = st_candidate
                et = _add_minutes(st_candidate, int(dur))

    duration = _parse_duration_minutes_from_text(q) or (
        default_duration if st and not time_rng else default_duration
    )

    # Title
    title = _extract_title_from_text(q) or _fallback_title(q)
    title = title.strip().strip('\'"“”‘’').strip()
    if not title:
        title = "New event"

    # Date bounds: parse explicit "from X to Y" or "between ... and ..."
    dr = _parse_month_day_range_text(q)
    start_date = today
    end_date: Optional[_date] = None
    if dr:
        start_date, end_date = dr

    # "until <date>"
    m_until_iso = re.search(r"\buntil\s+(20\d{2}-\d{2}-\d{2})\b", q_lower)
    if m_until_iso:
        end_date = _to_date(m_until_iso.group(1))
    else:
        m_until_h = re.search(
            r"\buntil\s+([A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?)",
            q,
            flags=re.IGNORECASE,
        )
        if m_until_h and not end_date:
            maybe = _parse_human_date(m_until_h.group(1))
            if maybe:
                end_date = maybe

    # "from X" without explicit end
    if not dr:
        m_from = re.search(
            r"\bfrom\s+([A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?)",
            q,
            flags=re.IGNORECASE,
        )
        if m_from:
            maybe_start = _parse_human_date(m_from.group(1))
            if maybe_start:
                start_date = maybe_start

    # Weeks & occurrences
    weeks_count, occ_count = _parse_weeks_and_occurrences(q_lower)

    # Interval: "every 2 weeks/days"
    interval = 1
    m_int = re.search(r"\bevery\s+(\d{1,3})\s+(weeks?|days?)\b", q_lower)
    if m_int:
        try:
            interval = max(1, min(365, int(m_int.group(1))))
        except Exception:
            interval = 1

    # pattern
    if by_weekdays:
        pattern = "WEEKLY"
    else:
        # If we explicitly said "weekdays"
        if re.search(r"\bweekdays?\b", q_lower):
            pattern = "WEEKDAYS"
        else:
            pattern = "DAILY"

    # Derive end_date if not present:
    if not end_date:
        if weeks_count > 0:
            end_date = start_date + timedelta(days=7 * weeks_count)
        elif occ_count > 0:
            # Let server treat count; we won't set end_date for count-limited series.
            end_date = None
        else:
            # default preview horizon if nothing is given: 4 weeks
            if preview_only:
                end_date = start_date + timedelta(days=28)

    # time string for body
    base_time = st or _to_time("09:00")
    if not base_time:
        base_time = _time(9, 0, 0)

    body: Dict[str, Any] = {
        "title": title,
        "start_date": start_date.isoformat(),
        "pattern": pattern,
        "time": base_time.isoformat(),
        "duration_minutes": int(duration),
        "interval": int(interval),
    }

    if by_weekdays:
        body["by_weekdays"] = by_weekdays
        # shorthand for server: weekday can be the first
        body["weekday"] = by_weekdays[0]

    if end_date:
        body["end_date"] = end_date.isoformat()

    if occ_count > 0:
        body["count"] = int(occ_count)

    action = "create_recurring_preview" if preview_only else "create_recurring_simple"
    return CreationPayload(action=action, body=body)


# ---------- TOP-LEVEL ROUTER ----------

def build_creation_payload(query: str) -> CreationPayload:
    """
    Decide whether this looks like a ONE-OFF or RECURRING creation request
    and build the corresponding structured payload.

    Heuristics:
      - If the text contains 'every' or clear weekday phrase → recurring
      - Otherwise → single create

    Example:

        >>> build_creation_payload("Schedule an appointment tomorrow at 5pm called Demo").to_dict()
        {
          "action": "create",
          "date": "2025-08-12",
          "start_time": "17:00:00",
          "duration_minutes": 60,
          "title": "Demo"
        }

        >>> build_creation_payload("every Thursday at 6pm for 4 weeks titled Demo").to_dict()
        {
          "action": "create_recurring_simple",
          "title": "Demo",
          "start_date": "2025-08-14",
          "end_date": "2025-09-11",
          "pattern": "WEEKLY",
          "by_weekdays": [3],
          "weekday": 3,
          "time": "18:00:00",
          "duration_minutes": 60,
          "interval": 1
        }
    """
    q_lower = (query or "").lower()
    if "every" in q_lower or "each" in q_lower or _parse_weekday_list(query):
        return build_recurring_creation_payload(query)
    return build_single_creation_payload(query)


# ---------- small CLI for quick manual tests ----------

if __name__ == "__main__":
    import json

    print("nl_creation_flow CLI: type a sentence, get JSON payload for /query.")
    print("Ctrl+C or empty line to exit.")
    while True:
        try:
            txt = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not txt:
            break
        payload = build_creation_payload(txt)
        print(json.dumps(payload.to_dict(), indent=2, default=str))
