# openai_handler.py
import os
import json
import re
import requests
from datetime import date as _date, time as _time, datetime as _dt, timedelta

from typing import Any, Dict, List, Optional

# --- lightweight normalization & quick rename detectors ---

def _normalize_leading_tokens(s: str) -> str:
    """
    Remove leading list numbers/bullets like:
      '1. ', '2) ', '- ', '* ', '• ', '– '
    and collapse double spaces.
    """
    if not s:
        return s
    s = s.lstrip()
    s = re.sub(r"^\s*(?:\d+[\.\)]\s+|[-*•–]\s+)+", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()

# Helper to trim trailing punctuation from titles
def _strip_trailing_punct(s: str) -> str:
    """Trim trailing sentence punctuation that LLMs often include in quoted titles."""
    if not s:
        return s
    return re.sub(r'[.,;:!?]+$', '', s).strip()


def _iso(d: _date) -> str:
    return d.isoformat()


def _pick_date_from_text(t: str) -> str | None:
    tl = (t or "").lower()
    if "today" in tl:
        return _iso(_date.today())
    if "tomorrow" in tl:
        return _iso(_date.today() + timedelta(days=1))
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t or "")
    if m:
        return m.group(1)
    return None


def _try_parse_rename(t: str):
    """
    Best-effort extraction for:
      - rename "Old" to "New"
      - change title of "Old" to "New"
      - retitle "Old" as "New"
      - rename lunch break to chai break   (unquoted)
    Returns dict or None.
    """
    tl = (t or "").lower()
    if not any(k in tl for k in ["rename", "retitle", "change the title", "change title"]):
        return None

    quoted = re.findall(r"[\"“]([^\"”]+)[\"”]", t or "")
    old_title = new_title = None
    if len(quoted) >= 2:
        old_title, new_title = quoted[0].strip(), quoted[-1].strip()
    else:
        m = re.search(r"\b(?:rename|retitle|change(?:\s+the)?\s+title(?:\s+of)?)\s+(.+?)\s+(?:to|as)\s+(.+)$", t or "", flags=re.IGNORECASE)
        if m:
            old_title = m.group(1).strip().strip('"“”')
            new_title = m.group(2).strip().strip('"“”')

    # Clean up any trailing punctuation that might sneak in
    if old_title:
        old_title = _strip_trailing_punct(old_title)
    if new_title:
        new_title = _strip_trailing_punct(new_title)

    if not old_title or not new_title:
        return None

    date_str = _pick_date_from_text(t or "")
    selector = {"title": old_title}
    if date_str:
        selector["date"] = date_str
    # Ensure downstream fuzzy, case-insensitive matching (duplicated at top-level, too)
    selector.setdefault("case_insensitive", True)
    selector.setdefault("min_ratio", 0.60)

    # Return canonical UPDATE_TITLE so app.py doesn't need a new intent.
    return {
        "intent": "UPDATE_TITLE",
        "params": {
            "selector": selector,
            "new_title": new_title,
            "old_title": old_title,
            # Also expose options at the top-level; app.py reads either place.
            "case_insensitive": True,
            "min_ratio": 0.60,
        },
    }

# Read API key from environment. (Do NOT paste secrets into code.)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


# ------------------------ utilities ------------------------
def _extract_json(text: str) -> str:
    """
    Best effort to extract a single JSON object from LLM text.
    Falls back to raw text if no braces found.
    """
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


def _parse_time_str(s: str | None) -> _time | None:
    """
    '14:30', '14:30:00', '2 pm', '2:30 PM' -> datetime.time
    """
    if not s:
        return None
    t = s.strip()

    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", t)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        ss = int(m.group(3) or 0)
        if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
            return _time(hh, mm, ss)

    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", t, re.I)
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


def _parse_date_str(s: str | None, today: _date) -> _date | None:
    """
    Try to parse ISO first; then a few common fuzzy formats used by earlier prompts.
    """
    if not s:
        return None
    s = s.strip()

    # ISO first
    try:
        return _date.fromisoformat(s)
    except Exception:
        pass

    # 'August 11' (assume current year)
    try:
        return _dt.strptime(f"{s} {today.year}", "%B %d %Y").date()
    except Exception:
        pass

    # 'Aug 11'
    try:
        return _dt.strptime(f"{s} {today.year}", "%b %d %Y").date()
    except Exception:
        pass

    # '8/11' (assume MM/DD/current year)
    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", s)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        yy = int(m.group(3)) if m.group(3) else today.year
        if yy < 100:
            yy += 2000
        try:
            return _date(yy, mm, dd)
        except Exception:
            return None

    return None


# ------------------------ GROQ normalization helpers ------------------------
_WEEKDAY_ICAL_TO_IDX: Dict[str, int] = {
    'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 'FR': 4, 'SA': 5, 'SU': 6,
}
_WEEKDAY_NAME_TO_IDX: Dict[str, int] = {
    'MON': 0, 'MONDAY': 0,
    'TUE': 1, 'TUES': 1, 'TUESDAY': 1,
    'WED': 2, 'WEDNESDAY': 2,
    'THU': 3, 'THUR': 3, 'THURS': 3, 'THURSDAY': 3,
    'FRI': 4, 'FRIDAY': 4,
    'SAT': 5, 'SATURDAY': 5,
    'SUN': 6, 'SUNDAY': 6,
}


def _canon_intent(name: Optional[str]) -> str:
    n = (name or '').upper()
    mapping = {
        # retrieve synonyms
        'RETRIEVE_ON_DATE': 'RETRIEVE_DATE',
        'ON_DATE': 'RETRIEVE_DATE',
        'DATE': 'RETRIEVE_DATE',
        'BETWEEN': 'RETRIEVE_BETWEEN',
        'BETWEEN_TIMES': 'RETRIEVE_BETWEEN',
        'BETWEEN_TZ': 'RETRIEVE_BETWEEN_TZ',
        'ON_DATE_TZ': 'RETRIEVE_DATE_TZ',
        # time-relative synonyms
        'NOW': 'RETRIEVE_NOW',
        'CURRENT': 'RETRIEVE_NOW',
        'RIGHT_NOW': 'RETRIEVE_NOW',
        'THIS_WEEK': 'RETRIEVE_WEEK',
        'NEXT_WEEK': 'RETRIEVE_NEXT_WEEK',
        'THIS_MONTH': 'RETRIEVE_MONTH',
        'LIST_MONTH': 'RETRIEVE_MONTH',
        # creation synonyms
        'CREATE': 'CREATE_SINGLE',
        'BOOK': 'CREATE_SINGLE',
        # update / modify synonyms
        'RESCHEDULE': 'UPDATE_RESCHEDULE',
        'MOVE': 'UPDATE_RESCHEDULE',
        'MOVE_APPOINTMENT': 'UPDATE_RESCHEDULE',
        'CHANGE': 'UPDATE_APPOINTMENT',
        'MODIFY': 'UPDATE_APPOINTMENT',
        'UPDATE': 'UPDATE_APPOINTMENT',
        'RENAME': 'UPDATE_TITLE',
        'CHANGE_TITLE': 'UPDATE_TITLE',
        'RETITLE': 'UPDATE_TITLE',
        'MOVE_DAY': 'MOVE_DAY',
        'MOVE_ALL_DAY': 'MOVE_DAY',
        'MAKE_RECURRING': 'CONVERT_TO_RECURRING',
        'CONVERT_TO_RECURRING': 'CONVERT_TO_RECURRING',
        # cancel/delete synonyms
        'CANCEL': 'CANCEL_DELETE',
        'DELETE': 'CANCEL_DELETE',
        'REMOVE': 'CANCEL_DELETE',
        # free time / availability synonyms
        'FREE': 'FREE_TIME',
        'FREE_TIME': 'FREE_TIME',
        'FREE_SLOTS': 'FREE_TIME',
        'OPEN_SLOTS': 'FREE_TIME',
        'OPEN_SLOT': 'FREE_TIME',
        'AVAILABILITY': 'FREE_TIME',
        'AVAILABLE': 'FREE_TIME',
    }
    return mapping.get(n, n)



def _infer_duration_minutes(st: Optional[str], et: Optional[str]) -> Optional[int]:
    """If both start_time and end_time are strings, return positive minutes difference."""
    if not st or not et:
        return None

    def _to_time_local(s: str) -> Optional[_time]:
        s = s.strip().lower()
        m = re.match(r'^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?$', s)
        if not m:
            return None
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        ss = int(m.group(3) or 0)
        ap = m.group(4)
        if ap == 'pm' and hh != 12:
            hh += 12
        if ap == 'am' and hh == 12:
            hh = 0
        return _time(hh % 24, mm, ss)

    t1 = _to_time_local(st)
    t2 = _to_time_local(et)
    if not t1 or not t2:
        return None
    total = (t2.hour * 3600 + t2.minute * 60 + t2.second) - (t1.hour * 3600 + t1.minute * 60 + t1.second)
    return max(0, total // 60)


# Helper: parse duration in minutes from natural language phrases
def _parse_duration_minutes_from_text(text: str) -> Optional[int]:
    """
    Robustly parse a duration in minutes from natural language.
    Examples:
      "for 30 minutes", "90 min", "45-minute", "90m",
      "1 hour", "2 hours", "1hr", "1.5 hours", "1.5h",
      "1h 30m", "1h30m", "2hr 15m", "2h15",
      "an hour", "half an hour", "quarter hour", "an hour and a half",
      "two hours", "forty five minutes".
    """
    if not text:
        return None
    tl = text.lower().strip()

    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
        "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
        "thirty": 30, "forty": 40, "fifty": 50
    }

    def _word_to_int(fragment: str) -> Optional[int]:
        frag = fragment.strip().lower()
        if frag in words:
            return int(words[frag])
        tot = 0
        for p in frag.split():
            if p in words:
                tot += words[p]
        return tot or None

    m = re.search(r'(\d+(?:\.\d+)?)\s*h(?:\s*(\d{1,2})\s*m)?', tl)
    if m:
        hours = float(m.group(1))
        mins = int(m.group(2) or 0)
        return int(round(hours * 60)) + mins

    m = re.search(r'(\d+(?:\.\d+)?)\s*[-\s]?(?:minutes?|mins?|m)\b', tl)
    if m:
        return int(round(float(m.group(1))))

    m = re.search(r'(\d+(?:\.\d+)?)\s*[-\s]?(?:hours?|hrs?|h)\b', tl)
    if m:
        return int(round(float(m.group(1)) * 60))

    if re.search(r'\ban?\s+hour\s+and\s+a\s+half\b', tl) or re.search(r'\b(one|1)\s+and\s+a\s+half\s+hours?\b', tl):
        return 90
    if re.search(r'\bhalf\s+(?:of\s+)?an?\s+hour\b', tl) or re.search(r'\bhalf-hour\b', tl):
        return 30
    if re.search(r'\bquarter\s+(?:of\s+)?an?\s+hour\b', tl) or re.search(r'\bquarter-hour\b', tl):
        return 15
    if re.search(r'\ban?\s+hour\b', tl):
        return 60

    m = re.search(r'\b([a-z]+)\s+hours?\b', tl)
    if m:
        n = _word_to_int(m.group(1))
        if n:
            return n * 60
    m = re.search(r'\b([a-z]+)\s+minutes?\b', tl)
    if m:
        n = _word_to_int(m.group(1))
        if n:
            return n
    return None

# Helper: parse time window/range from text like "between 1pm and 5pm", "after 6pm", "before 2:15 pm"
def _parse_time_range_text(text: str) -> Optional[tuple[_time, _time]]:
    """
    Extract a time window from phrases like:
      - "between 1pm and 5pm", "from 09:00 to 13:30"
      - "after 6pm", "before 2:15 pm"
    Returns (start_time, end_time) as datetime.time, or None if not found.
    """
    if not text:
        return None
    s = text.strip()
    m = re.search(
        r'\b(?:between|from)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:and|to|-)\s*'
        r'(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b',
        s, flags=re.I
    )
    if m:
        t1 = _parse_time_str(m.group(1))
        t2 = _parse_time_str(m.group(2))
        if t1 and t2:
            return (t1, t2)
    m = re.search(r'\bafter\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', s, flags=re.I)
    if m:
        t1 = _parse_time_str(m.group(1))
        if t1:
            return (t1, _time(23, 59, 59))
    m = re.search(r'\bbefore\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', s, flags=re.I)
    if m:
        t2 = _parse_time_str(m.group(1))
        if t2:
            return (_time(0, 0, 0), t2)
    return None


# --- Fuzzy selector and rename helpers ---
def _add_fuzzy_options_to_selector(sel: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure downstream search is case-insensitive and allows fuzzy matching.
    Consumers (app.py) can read:
      - selector.case_insensitive: bool
      - selector.min_ratio: float in [0,1] (e.g., 0.60 means 60% match)
    """
    if not isinstance(sel, dict):
        sel = {}
    sel.setdefault("case_insensitive", True)
    # prefer 0..1 scale for clarity
    if "min_ratio" not in sel and "threshold" not in sel:
        sel["min_ratio"] = 0.60
    return sel


def _parse_rename_from_text(text: str, today: _date) -> Optional[Dict[str, Any]]:
    """
    Robustly parse rename / change title requests from free text.
    Returns a canonical {intent:'UPDATE_TITLE', params:{selector:{...}, new_title:'...'}} or None.
    """
    if not text:
        return None

    s = text.strip()
    tl = s.lower()

    if not re.search(r'\b(rename|retitle|change\s+(?:the\s+)?title)\b', tl):
        return None

    # NEW TITLE (quoted preferred)
    new_q = re.search(r'\bto\s+[\'"]([^\'"]+)[\'"]', s, flags=re.I)
    if not new_q:
        # unquoted fallback: everything after "to "
        new_q = re.search(r'\bto\s+(.+)$', s, flags=re.I)
    new_title = new_q.group(1).strip() if new_q else None
    if new_title:
        new_title = _strip_trailing_punct(new_title)

    # OLD TITLE
    old_title = None
    # explicit "title 'X'"
    m_title = re.search(r"title\s*[\'\"]([^\'\"]+)[\'\"]", s, flags=re.I)
    if m_title:
        old_title = m_title.group(1).strip()
        if old_title:
            old_title = _strip_trailing_punct(old_title)
    else:
        quoted = re.findall(r"[\'\"]([^\'\"]+)[\'\"]", s)
        if len(quoted) >= 2:
            old_title = quoted[0].strip()
            if old_title:
                old_title = _strip_trailing_punct(old_title)
            if not new_title:
                new_title = quoted[-1].strip()
                if new_title:
                    new_title = _strip_trailing_punct(new_title)
        else:
            # no quotes; try to capture a token preceding 'to'
            m2 = re.search(
                r"\brename\b.*?\b(?:today|tomorrow|\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\s+\d{1,2})?\s*"
                r"(?:at\s+\d{1,2}:\d{2}(?:\s*[ap]m)?)?\s*"
                r"([A-Za-z][A-Za-z0-9 _\-/]{1,60})\s*\bto\b",
                s,
                flags=re.I,
            )
            if m2:
                old_title = m2.group(1).strip()
                if old_title:
                    old_title = _strip_trailing_punct(old_title)

    # DATE (optional)
    date_str = None
    if 'today' in tl:
        date_str = today.isoformat()
    elif 'tomorrow' in tl:
        date_str = (today + timedelta(days=1)).isoformat()
    else:
        dm = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', s)
        if dm:
            date_str = dm.group(1)
        else:
            # month name forms like "Aug 21" or "August 21"
            dm2 = re.search(r'\b([A-Za-z]{3,9}\s+\d{1,2})\b', s)
            if dm2:
                d_try = _parse_date_str(dm2.group(1), today)
                if d_try:
                    date_str = d_try.isoformat()

    # TIME (optional)
    tm = re.search(r'\b(\d{1,2}:\d{2}(?:\s*[ap]m)?)\b', s, flags=re.I)
    start_time = tm.group(1) if tm else None

    if new_title and (old_title or date_str or start_time):
        selector: Dict[str, Any] = {}
        if date_str:
            selector["date"] = date_str
        if start_time:
            selector["start_time"] = start_time
        if old_title:
            selector["title"] = old_title
            selector["term"] = old_title  # allow downstream matching by term too
        selector = _add_fuzzy_options_to_selector(selector)
        return {
            "intent": "UPDATE_TITLE",
            "params": {"selector": selector, "new_title": new_title, "old_title": old_title},
        }
    return None


def _weekday_token_to_index(tok: str | None) -> int | None:
    if not tok:
        return None
    key = tok.strip().upper()
    if key in _WEEKDAY_ICAL_TO_IDX:
        return _WEEKDAY_ICAL_TO_IDX[key]
    return _WEEKDAY_NAME_TO_IDX.get(key) or _WEEKDAY_NAME_TO_IDX.get(key[:3])


def _flatten_recurrence(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize nested recurrence:
      {frequency:'weekly'|'daily'|'weekdays',
       byday:'SA'|['MO','WE']|'sat'|['mon','wed'],
       interval:int, count:int, until:'YYYY-MM-DD', start: 'YYYY-MM-DD'}
    -> pattern, weekday/by_weekdays, interval, count, end_date, start_date
    """
    out: Dict[str, Any] = {}
    if not isinstance(rec, dict):
        return out

    freq = str(rec.get('frequency') or rec.get('freq') or '').upper()
    if freq in {'DAILY', 'DAY'}:
        out['pattern'] = 'DAILY'
    elif freq in {'WEEKDAYS', 'BUSINESS', 'BUSINESS_DAYS'}:
        out['pattern'] = 'WEEKDAYS'
    elif freq in {'WEEKLY', 'WEEK'}:
        out['pattern'] = 'WEEKLY'

    if rec.get('interval') is not None:
        try:
            out['interval'] = int(rec['interval'])
        except Exception:
            pass
    if rec.get('count') is not None:
        try:
            out['count'] = int(rec['count'])
        except Exception:
            pass
    if rec.get('until'):
        out['end_date'] = rec['until']

    # explicit start on recurrence object (rare but appears)
    startd = rec.get('start') or rec.get('start_date') or rec.get('from')
    if startd:
        out['start_date'] = startd

    # byday -> weekday indices
    byday = rec.get('byday') or rec.get('byDay') or rec.get('by_day') or rec.get('days')
    if byday:
        byday_list = [byday] if isinstance(byday, str) else list(byday)
        idxs: List[int] = []
        for item in byday_list:
            if not item:
                continue
            idx = _weekday_token_to_index(str(item))
            if idx is not None and idx not in idxs:
                idxs.append(idx)
        if len(idxs) == 1:
            out['weekday'] = idxs[0]
        elif idxs:
            out['by_weekdays'] = idxs
    return out


def _normalize_groq_params(params: dict, today: _date) -> dict:
    """
    Flatten common Groq shapes into the fields app.py already understands.
    - start_time/end_time -> time + duration_minutes
    - recurrence.{frequency,byday,until,interval} -> pattern / weekday|by_weekdays / end_date / interval
    - normalize date_range (list or 'YYYY-MM-DD/YYYY-MM-DD')
    """
    if not isinstance(params, dict):
        return {}
    p = dict(params)  # shallow copy

    # ---- accept 'time' and map to start_time; normalize both ----
    # normalize time -> 'HH:MM'
    if p.get("time") and not p.get("start_time"):
        t = _parse_time_str(str(p["time"]))
        if t:
            p["start_time"] = t.strftime("%H:%M")
            p["time"] = p["start_time"]

    start_t = _parse_time_str(p.get("start_time")) if p.get("start_time") else None
    end_t = _parse_time_str(p.get("end_time")) if p.get("end_time") else None
    if "time" not in p and start_t:
        p["time"] = start_t.strftime("%H:%M")
    if "duration_minutes" not in p and start_t and end_t:
        dur = int((_dt.combine(today, end_t) - _dt.combine(today, start_t)).total_seconds() // 60)
        if dur > 0:
            p["duration_minutes"] = dur

    # ---- accept alternate duration keys -> duration_minutes ----
    if "duration_minutes" not in p:
        # numeric-like keys
        for alt in ("duration_minutes", "duration_min", "duration_mins"):
            if alt in p and str(p[alt]).strip() != "":
                try:
                    p["duration_minutes"] = int(p[alt])
                    break
                except Exception:
                    pass
        # generic "duration" that could be text like "1h 30m" or "90m"
        if "duration_minutes" not in p and p.get("duration") is not None:
            val = str(p["duration"])
            parsed = _parse_duration_minutes_from_text(val)
            if parsed:
                p["duration_minutes"] = int(parsed)

    # ---- accept window/time_window -> start_time/end_time ----
    win = p.get("window") or p.get("time_window")
    if isinstance(win, dict):
        st = _parse_time_str(str(win.get("start"))) if win.get("start") else None
        et = _parse_time_str(str(win.get("end"))) if win.get("end") else None
        if st and "start_time" not in p:
            p["start_time"] = st.strftime("%H:%M")
        if et and "end_time" not in p:
            p["end_time"] = et.strftime("%H:%M")
    elif isinstance(win, str) and "-" in win and ("start_time" not in p or "end_time" not in p):
        parts = [w.strip() for w in win.split("-", 1)]
        if len(parts) == 2:
            st = _parse_time_str(parts[0]); et = _parse_time_str(parts[1])
            if st and "start_time" not in p:
                p["start_time"] = st.strftime("%H:%M")
            if et and "end_time" not in p:
                p["end_time"] = et.strftime("%H:%M")

    # ---- accept 'datetime' and split to date + start_time ----
    if p.get("datetime") and (not p.get("date") or not p.get("start_time")):
        try:
            # tolerate both 'YYYY-MM-DDTHH:MM' and with seconds
            dt = _dt.fromisoformat(str(p["datetime"]).strip().replace("Z", "+00:00"))
            p.setdefault("date", dt.date().isoformat())
            p.setdefault("start_time", dt.time().replace(microsecond=0).strftime("%H:%M"))
            p.setdefault("time", p["start_time"])
        except Exception:
            pass

    # ---- accept simple 'relative' hints ----
    rel = (p.get("relative") or p.get("when") or "").strip().lower()
    if not p.get("date") and rel in ("today", "tod", "now"):
        p["date"] = today.isoformat()
    elif not p.get("date") and rel in ("tomorrow", "tmrw", "tmr"):
        p["date"] = (today + timedelta(days=1)).isoformat()

    # ---- recurrence -> pattern / weekdays / end_date / interval ----
    rec = p.get("recurrence") or {}
    if isinstance(rec, dict):
        flat = _flatten_recurrence(rec)
        p.update({k: v for k, v in flat.items() if k not in p})
        # We don't need the nested object anymore
        p.pop("recurrence", None)

    # ---- date_range normalization ----
    dr = p.get("date_range") or p.get("range") or p.get("between")
    if isinstance(dr, list) and len(dr) == 2:
        p["date_range"] = dr
    elif isinstance(dr, str) and "/" in dr and "date_range" not in p:
        p["date_range"] = dr

    # ---- normalize "new_*" fields for update/reschedule flows ----
    if p.get("new_time") and not p.get("new_start_time"):
        t_new = _parse_time_str(str(p["new_time"]))
        if t_new:
            p["new_start_time"] = t_new.strftime("%H:%M")

    if p.get("new_datetime") and (not p.get("new_date") or not p.get("new_start_time")):
        try:
            dt_new = _dt.fromisoformat(str(p["new_datetime"]).strip().replace("Z", "+00:00"))
            p.setdefault("new_date", dt_new.date().isoformat())
            p.setdefault("new_start_time", dt_new.time().replace(microsecond=0).strftime("%H:%M"))
        except Exception:
            pass

    # accept common alternate field names for the target slot
    for alt_key in ("move_date", "to_date", "date_to", "newdate"):
        if alt_key in p and not p.get("new_date"):
            d_alt = _parse_date_str(str(p[alt_key]), today)
            if d_alt:
                p["new_date"] = d_alt.isoformat()
                break
    for alt_key in ("move_time", "to_time", "newtime"):
        if alt_key in p and not p.get("new_start_time"):
            t_alt = _parse_time_str(str(p[alt_key]))
            if t_alt:
                p["new_start_time"] = t_alt.strftime("%H:%M")
                break

    # If we know new_start_time and a duration, infer new_end_time
    if p.get("new_start_time") and p.get("duration_minutes") and not p.get("new_end_time"):
        t0 = _parse_time_str(p["new_start_time"])  # HH:MM
        if t0:
            try:
                end_dt = _dt.combine(today, t0) + timedelta(minutes=int(p["duration_minutes"]))
                p["new_end_time"] = end_dt.time().replace(microsecond=0).strftime("%H:%M")
            except Exception:
                pass

    # ---- normalize selector/filter (what to modify/delete) ----
    sel = p.get("selector") or p.get("filter")
    if isinstance(sel, dict):
        # coerce basic date/time strings
        if sel.get("date"):
            d = _parse_date_str(str(sel["date"]), today)
            if d:
                sel["date"] = d.isoformat()
        if sel.get("start_time"):
            ts = _parse_time_str(str(sel["start_time"]))
            if ts:
                sel["start_time"] = ts.strftime("%H:%M")
        if sel.get("end_time"):
            te = _parse_time_str(str(sel["end_time"]))
            if te:
                sel["end_time"] = te.strftime("%H:%M")
        sel = _add_fuzzy_options_to_selector(sel)
        p["selector"] = sel
    elif sel is not None:
        # non-dict selector -> promote into a simple search term
        p["selector"] = _add_fuzzy_options_to_selector({"term": str(sel)})

    return p


def _infer_dates_from_text(original_text: str, today: _date) -> Dict[str, str]:
    """
    Heuristic: pull start_date/end_date from phrases like
      'from Aug 15 to Aug 30', 'between 2025-08-15 and 2025-08-30', 'until Aug 30'
    Returns dict with optional 'start_date' and/or 'end_date' (ISO).
    """
    out: Dict[str, str] = {}
    text = (original_text or "").strip()

    # from X to/until/through Y
    m = re.search(
        r'\bfrom\s+([A-Za-z0-9/ ,\-]+?)\s+(?:to|until|through|thru)\s+([A-Za-z0-9/ ,\-]+)\b',
        text, flags=re.I
    )
    if m:
        s = _parse_date_str(m.group(1), today)
        e = _parse_date_str(m.group(2), today)
        if s:
            out['start_date'] = s.isoformat()
        if e:
            out['end_date'] = e.isoformat()
        return out

    # until Y (no explicit start)
    m2 = re.search(r'\buntil\s+([A-Za-z0-9/ ,\-]+)\b', text, flags=re.I)
    if m2:
        e = _parse_date_str(m2.group(1), today)
        if e:
            out['end_date'] = e.isoformat()

    # starting/on X (explicit start)
    m3 = re.search(r'\b(start(?:ing)?|on)\s+([A-Za-z0-9/ ,\-]+)\b', text, flags=re.I)
    if m3:
        s = _parse_date_str(m3.group(2), today)
        if s:
            out['start_date'] = s.isoformat()

    return out


def _normalize_groq_output(raw: Any, original_text: str) -> Any:
    """
    Coerce many GROQ shapes into { 'intent': UPPER, 'params': {...} }.
    Leave legacy (date,start,end) tuples alone for the old codepath.
    """
    # Already canonical
    if isinstance(raw, dict) and 'intent' in raw:
        params = dict(raw.get('params') or {})
        params = _normalize_groq_params(params, _date.today())
        intent = _canon_intent(raw.get('intent'))

        # Heuristic: if user text clearly says "reschedule"/"move" but model chose a CREATE_*, fix to UPDATE_RESCHEDULE.
        text_l = (original_text or "").lower()
        if any(tok in text_l for tok in ("reschedul", "move ")) and intent.startswith("CREATE"):
            intent = "UPDATE_RESCHEDULE"
        # Heuristic: if it clearly says "cancel/delete/remove", force CANCEL_DELETE.
        if any(tok in text_l for tok in ("cancel", "delete", "remove")):
            intent = "CANCEL_DELETE"
        # Heuristic: free/availability/open-slot requests should map to FREE_TIME
        if any(tok in text_l for tok in ("free", "availability", "available", "open slot", "open slots", "free slot", "free slots", "avail")) and not intent.startswith("CREATE") and intent != "CANCEL_DELETE":
            intent = "FREE_TIME"

        # Try to infer dates from the user's text if missing
        inferred = _infer_dates_from_text(original_text, _date.today())
        for k, v in inferred.items():
            params.setdefault(k, v)

        # If FREE_TIME, enrich missing fields from the original text
        if intent == "FREE_TIME":
            if not params.get("date"):
                d = _pick_date_from_text(original_text)
                if d:
                    params["date"] = d
            if not params.get("duration_minutes"):
                dur = _parse_duration_minutes_from_text(original_text or "")
                if dur:
                    params["duration_minutes"] = int(dur)
            if not (params.get("start_time") and params.get("end_time")):
                rng = _parse_time_range_text(original_text or "")
                if rng:
                    st, et = rng
                    params.setdefault("start_time", st.strftime("%H:%M"))
                    params.setdefault("end_time", et.strftime("%H:%M"))

        # Ensure both directions are available
        if 'start_time' not in params and params.get('time'):
            t = _parse_time_str(params['time'])
            if t:
                params['start_time'] = t.strftime("%H:%M")
        if 'time' not in params and params.get('start_time'):
            params['time'] = params.get('start_time')
        if 'duration_minutes' not in params and params.get('start_time') and params.get('end_time'):
            dur = _infer_duration_minutes(params.get('start_time'), params.get('end_time'))
            if dur and dur > 0:
                params['duration_minutes'] = int(dur)

        # Ensure new_* symmetry for update flows
        if 'new_start_time' not in params and params.get('new_time'):
            t_new = _parse_time_str(params['new_time'])
            if t_new:
                params['new_start_time'] = t_new.strftime("%H:%M")
        if 'new_time' not in params and params.get('new_start_time'):
            params['new_time'] = params.get('new_start_time')

        # If rescheduling and selector/new_date missing, try to infer from raw text:
        if intent == "UPDATE_RESCHEDULE":
            # infer selector date from "from X" or "on X"
            if not isinstance(params.get("selector"), dict):
                params["selector"] = {}
            sel = params["selector"]
            if "date" not in sel:
                m_from = re.search(r"\bfrom\s+([A-Za-z0-9/ ,\-]+)", original_text or "", flags=re.I)
                if m_from:
                    d_from = _parse_date_str(m_from.group(1), _date.today())
                    if d_from:
                        sel["date"] = d_from.isoformat()
                else:
                    m_on = re.search(r"\bon\s+([A-Za-z0-9/ ,\-]+)", original_text or "", flags=re.I)
                    if m_on:
                        d_on = _parse_date_str(m_on.group(1), _date.today())
                        if d_on:
                            sel["date"] = d_on.isoformat()
                    elif "today" in (original_text or "").lower():
                        sel["date"] = _date.today().isoformat()
            params["selector"] = sel
            # make selection robust (case-insensitive, fuzzy)
            params["selector"] = _add_fuzzy_options_to_selector(params["selector"])

            # infer new_date from "to X" or "tomorrow"
            if not params.get("new_date"):
                m_to = re.search(r"\bto\s+([A-Za-z0-9/ ,\-]+)", original_text or "", flags=re.I)
                if m_to:
                    d_to = _parse_date_str(m_to.group(1), _date.today())
                    if d_to:
                        params["new_date"] = d_to.isoformat()
                elif "tomorrow" in (original_text or "").lower():
                    params["new_date"] = (_date.today() + timedelta(days=1)).isoformat()

        # If the user clearly asked to rename but the model chose a different intent,
        # try our local rename extractor and return that structure.
        if any(tok in (original_text or "").lower() for tok in ("rename", "retitle", "change the title")) and intent != "UPDATE_TITLE":
            parsed = _parse_rename_from_text(original_text, _date.today())
            if parsed:
                return parsed

        # If retrieval intent lacks explicit times but the user said "between X and Y", infer from text
        if intent in ("RETRIEVE_BETWEEN", "RETRIEVE_BETWEEN_TZ", "RETRIEVE_DATE", "RETRIEVE_DATE_TZ") and not (params.get("start_time") and params.get("end_time")):
            rng = _parse_time_range_text(original_text or "")
            if rng:
                st, et = rng
                params.setdefault("start_time", st.strftime("%H:%M"))
                params.setdefault("end_time", et.strftime("%H:%M"))

        return {'intent': intent, 'params': params}

    # Flat dict with date/start_time/etc. and no intent
    if isinstance(raw, dict):
        params = _normalize_groq_params(dict(raw), _date.today())

        # Date inference from raw text if not supplied
        inferred = _infer_dates_from_text(original_text, _date.today())
        for k, v in inferred.items():
            params.setdefault(k, v)

        if 'date_range' in params:
            intent = 'RETRIEVE_RANGE'
        elif params.get('date') and (params.get('start_time') or params.get('end_time')):
            intent = 'RETRIEVE_BETWEEN'
        elif params.get('date'):
            intent = 'RETRIEVE_DATE'
        else:
            return raw  # unknown shape; let caller handle
        return {'intent': _canon_intent(intent), 'params': params}

    # JSON string? Try to parse and normalize
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
            return _normalize_groq_output(obj, original_text)
        except Exception:
            return raw

    return raw


# ------------------------ naive fallback (used when no API key or error) ------------------------
def _naive_intents(query: str, today: _date):
    """
    Very small intent recognizer used ONLY when the GROQ key is missing.
    Returns a dict like {"intent": "...", "params": {...}} for a few cases,
    otherwise returns None and lets the legacy tuple parser run.
    """
    q = query.lower().strip()

    # rename/change title (naive)
    if re.search(r"\b(rename|retitle|change\s+(?:the\s+)?title)\b", q):
        parsed = _parse_rename_from_text(query, today)
        if parsed:
            return parsed

    # free time / availability / open slots
    if any(tok in q for tok in ("free", "availability", "available", "open slot", "open slots", "free slot", "free slots", "avail")):
        params: Dict[str, Any] = {}
        d = _pick_date_from_text(query)
        params["date"] = d or today.isoformat()
        dur = _parse_duration_minutes_from_text(query)
        if dur:
            params["duration_minutes"] = int(dur)
        rng = _parse_time_range_text(query)
        if rng:
            st, et = rng
            params["start_time"] = st.strftime("%H:%M")
            params["end_time"] = et.strftime("%H:%M")
        return {"intent": "FREE_TIME", "params": params}

    # "how many ... this month"
    if re.search(r'\bhow\s+many\b', q) and "month" in q:
        return {"intent": "RETRIEVE_MONTH", "params": {"aggregate": "count"}}

    # "now" / "right now" / "currently"
    if re.search(r"\b(now|right now|currently|ongoing)\b", q):
        return {"intent": "RETRIEVE_NOW", "params": {}}

    # "next 24h" / "next 24 hours" / "in the next 24 hours"
    if re.search(r"\bnext\s*24\s*(h|hours)\b", q) or "in the next 24 hours" in q:
        return {"intent": "RETRIEVE_NEXT_24H", "params": {}}

    # If user explicitly mentions a timezone label like "CET", "PST", "IST" alongside "between"
    # we surface a BETWEEN_TZ intent with raw strings; app.py will resolve & convert.
    m_between = re.search(
        r'between\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:and|to)\s*'
        r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', q, re.I
    )
    tz_match = re.search(r'\b([A-Z]{2,4})\b', q)  # crude abbrev grab; app.py validates
    if m_between and tz_match:
        # Build the original strings (do NOT convert here)
        s_h, s_m, s_mer = m_between.group(1), m_between.group(2), m_between.group(3)
        e_h, e_m, e_mer = m_between.group(4), m_between.group(5), m_between.group(6)
        start_str = f"{s_h}:{s_m or '00'} {s_mer or ''}".strip()
        end_str = f"{e_h}:{e_m or '00'} {e_mer or ''}".strip()

        # Prefer a loose date keyword; else leave date null (app.py can default).
        date_val = None
        if "tomorrow" in q:
            date_val = (today + timedelta(days=1)).isoformat()
        elif "today" in q:
            date_val = today.isoformat()

        return {
            "intent": "RETRIEVE_BETWEEN_TZ",
            "params": {
                "date": date_val,
                "start_time": start_str,
                "end_time": end_str,
                "timezone": tz_match.group(1)
            }
        }
    # simple cancel/delete detection: "cancel/delete/remove ... on <date>" or by label/term
    if re.search(r"\b(cancel|delete|remove)\b", q):
        mdate = re.search(r"\b(on|for)\s+([A-Za-z0-9/ ,\-]+)", q)
        d = _parse_date_str(mdate.group(2), today) if mdate else None
        if d:
            return {"intent": "CANCEL_DELETE", "params": {"date": d.isoformat()}}
        mlabel = re.search(r"label(?:ed)?\s+'([^']+)'|label(?:ed)?\s+\"([^\"]+)\"", q)
        if mlabel:
            term = mlabel.group(1) or mlabel.group(2)
            return {"intent": "CANCEL_DELETE", "params": {"label": term}}
        mwith = re.search(r"\bwith\s+([A-Za-z][\w .\-]+)\b", q)
        if mwith:
            return {"intent": "CANCEL_DELETE", "params": {"term": mwith.group(1).strip()}}
        return {"intent": "CANCEL_DELETE", "params": {}}

    # simple reschedule detection: "reschedule/move ... from/on <date> to <date/tomorrow> at <time> for <duration>"
    if re.search(r"\breschedul", q) or re.search(r"\bmove\b", q):
        params: Dict[str, Any] = {}

        # Try to capture a descriptive term ("dentist appointment", "meeting with John")
        m_title = re.search(r"(?:reschedul\w*|move)\s+(?:my\s+)?(.+?)(?:\s+(?:from|on|to|at)\b|$)", q)
        if m_title:
            term_raw = m_title.group(1).strip().strip(".")
            # avoid capturing generic words only
            if term_raw and not re.match(r"^(appointment|meeting|event|call)$", term_raw):
                params.setdefault("selector", {})["term"] = term_raw

        # Also capture "with John"
        m_with = re.search(r"\bwith\s+([A-Za-z][\w .\-]+)\b", q)
        if m_with:
            params.setdefault("selector", {})["term"] = m_with.group(1).strip()

        # Selector date: prefer 'from X', else 'on X', else 'today' if present
        m_from = re.search(r"\bfrom\s+([A-Za-z0-9/ ,\-]+)", q, re.I)
        m_on = re.search(r"\bon\s+([A-Za-z0-9/ ,\-]+)", q, re.I)
        d_from = _parse_date_str(m_from.group(1), today) if m_from else None
        d_on = _parse_date_str(m_on.group(1), today) if m_on else None
        if d_from:
            params.setdefault("selector", {})["date"] = d_from.isoformat()
        elif d_on:
            params.setdefault("selector", {})["date"] = d_on.isoformat()
        elif "today" in q:
            params.setdefault("selector", {})["date"] = today.isoformat()

        # New date: prefer 'to X', else 'tomorrow' if present
        m_to = re.search(r"\bto\s+([A-Za-z0-9/ ,\-]+)", q, re.I)
        d_to = _parse_date_str(m_to.group(1), today) if m_to else None
        if d_to:
            params["new_date"] = d_to.isoformat()
        elif "tomorrow" in q:
            params["new_date"] = (today + timedelta(days=1)).isoformat()

        # New time
        m_at = re.search(r"\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", q, re.I)
        t_to = _parse_time_str(m_at.group(1)) if m_at else None
        if t_to:
            params["new_start_time"] = t_to.strftime("%H:%M")

        # Duration (optional) and infer new_end_time if possible
        dur = _parse_duration_minutes_from_text(q)
        if dur:
            params["duration_minutes"] = dur
            if t_to and not params.get("new_end_time"):
                try:
                    end_dt = _dt.combine(today, t_to) + timedelta(minutes=int(dur))
                    params["new_end_time"] = end_dt.time().replace(microsecond=0).strftime("%H:%M")
                except Exception:
                    pass

        if "selector" in params:
            params["selector"] = _add_fuzzy_options_to_selector(params["selector"])
        return {"intent": "UPDATE_RESCHEDULE", "params": params}


def _naive_parse(query: str, today: _date):
    """
    Minimal local fallback if GROQ is unavailable:
      - 'between X and Y today/tomorrow'
      - 'today' or 'tomorrow' (date-only)
    Returns (date | None, start_time | None, end_time | None) for backward compat.
    """
    q = query.lower()

    # between X and Y ...
    m = re.search(
        r'between\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:and|to)\s*'
        r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?',
        q, re.I
    )
    target_date = None
    if "tomorrow" in q:
        target_date = today + timedelta(days=1)
    elif "today" in q:
        target_date = today

    if m and target_date:
        s_h = int(m.group(1)); s_m = int(m.group(2) or 0); s_mer = (m.group(3) or "").lower()
        if s_mer == "pm" and s_h != 12:
            s_h += 12
        if s_mer == "am" and s_h == 12:
            s_h = 0
        start_t = _time(s_h % 24, s_m)

        e_h = int(m.group(4)); e_m = int(m.group(5) or 0); e_mer = (m.group(6) or "").lower()
        if e_mer == "pm" and e_h != 12:
            e_h += 12
        if e_mer == "am" and e_h == 12:
            e_h = 0
        end_t = _time(e_h % 24, e_m)

        return (target_date, start_t, end_t)

    if "today" in q:
        return (today, None, None)
    if "tomorrow" in q:
        return (today + timedelta(days=1), None, None)

    return (None, None, None)


# ------------------------ main entry ------------------------
def parse_query(query: str):
    """
    Ask the LLM to return strict JSON describing the user's calendar request.

    BACKWARD COMPATIBILITY:
    - If the reply contains only (date/start_time/end_time), this returns the legacy tuple:
        (date_obj | None, start_time | None, end_time | None)
    - If the reply contains 'intent' and 'params', this returns a dict:
        { "intent": "...", "params": {...} }

    If the API key is missing or the call fails, we use the naive local parser
    (the legacy flows you already have keep working).
    """
    today = _date.today()

    # Normalize leading numbering/bullets and whitespace
    original_query = query
    t = _normalize_leading_tokens((query or "").strip())
    if not t:
        return None

    tl = t.lower()

    # --- Reminders intents (fast path) ---
    if any(k in tl for k in ['remind me', 'notify me', 'alert me', 'ping me', 'nudge me']):
        import re
        m_time = re.search(r'\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', tl)
        m_date = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', tl)
        def lead_from_text(s: str):
            m = re.search(r'(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours)\s*before', s)
            if m:
                try:
                    return int(round(float(m.group(1))*60))
                except Exception:
                    pass
            m = re.search(r'(\d+)\s*(m|min|mins|minute|minutes)\s*before', s)
            if m:
                return int(m.group(1))
            if 'day before' in s:
                return 1440
            if 'week before' in s:
                return 10080
            return 0
        lead = lead_from_text(tl)
        # Extract task after "to ..."
        m_task = re.search(r'\bto\s+(.+)$', original_query, flags=re.IGNORECASE)
        title = (m_task.group(1).strip() if m_task else 'Reminder')
        return {
            'intent': 'REMINDER_CREATE' if m_time else 'REMINDER_FOR_APPOINTMENT',
            'params': {
                'date': m_date.group(1) if m_date else None,
                'time': m_time.group(1) if m_time else None,
                'lead_minutes': lead,
                'title': title,
            }
        }

    # No key => try a light intent recognizer, then fall back to legacy tuple parser
    if not GROQ_API_KEY:
        print("[openai_handler] GROQ_API_KEY not set – using naive intent/tuple parser.")
        # Early: handle simple rename locally even without the model
        early = _try_parse_rename(t)
        if early:
            return early
        naive_intent = _naive_intents(t, today)
        if naive_intent:
            return naive_intent
        return _naive_parse(t, today)

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    # Prompt: supports both retrieval AND creation. Always return a SINGLE JSON object.
    system_rules = (
        "You are a calendar intent parser. "
        "Return ONLY a single JSON object and NOTHING else. "
        "Two valid schemas:\n"
        "A) {\"intent\": string, \"params\": object}\n"
        "   - Use for creating/scheduling, modifying, cancelling, reminders, "
        "     or advanced retrieval (free time, summaries).\n"
        "   - Recognized intents include (examples):\n"
        "     CREATE_SINGLE, CREATE_RECURRING, CREATE_CONSTRAINT_SLOT, CREATE_MULTI_BLOCKS, CREATE_TEMPLATED_PLAN,\n"
        "     UPDATE_RESCHEDULE, UPDATE_APPOINTMENT, UPDATE_TITLE, MOVE_DAY, CONVERT_TO_RECURRING,\n"
        "     CANCEL_DELETE, HOLD_TENTATIVE, and retrieval like FREE_TIME, RETRIEVE_NOW, RETRIEVE_NEXT_24H, RETRIEVE_BETWEEN_TZ, RETRIEVE_DATE_TZ.\n"
        "   - For updates use fields: selector (object with keys like id, date, start_time, title, term, label),\n"
        "     and new_date, new_start_time, new_end_time, or new_datetime.\n"
        "   - For cancel/delete use fields: selector or date/term/label/id.\n"
        "   - For reschedule, prefer new_date and new_start_time; include duration_minutes or new_end_time if known.\n"
        "   - params may include: title, date, start_time, end_time, duration_min, "
        "date_range, relative, window, timezone, location, modality, attendees, "
        "label, color, tentative, buffers, constraints, recurrence, template, "
        "blocks, fallback, multi_attendee.\n"
        "B) {\"date\": ISO, \"start_time\": 'HH:MM'|'HH:MM:SS'|null, "
        "\"end_time\": 'HH:MM'|'HH:MM:SS'|null}\n"
        "   - Use this simpler form for classic retrieval like "
        "'between 2 and 4 pm tomorrow' or 'what's on Aug 11'.\n"
        "Rules:\n"
        " - date must be ISO 'YYYY-MM-DD' when present.\n"
        " - start_time/end_time must be 24h 'HH:MM' or 'HH:MM:SS' when present.\n"
        " - If the user supplies a timezone (e.g., 'CET', 'PST', 'Asia/Kolkata'), include it in params.timezone.\n"
        " - Never include markdown or extra text, only JSON.\n"
    )

    payload = {
        "model": "llama3-70b-8192",
        "messages": [
            {"role": "system", "content": system_rules},
            {"role": "system", "content": f"Today's date is {today.isoformat()}."},
            {"role": "user", "content": t},
        ],
        "temperature": 0.0,
    }

    try:
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=25)
        resp.raise_for_status()
        result = resp.json()
        text = result["choices"][0]["message"]["content"].strip()
        print("GROQ LLM RESPONSE:\n", text)

        data = json.loads(_extract_json(text))

        # Normalize GROQ shapes into canonical {intent, params}
        norm = _normalize_groq_output(data, original_query)

        # Preferred normalized intent form
        if isinstance(norm, dict) and "intent" in norm:
            params = norm.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            return {"intent": str(norm.get("intent") or "").strip(), "params": params}

        # Fallback: handle legacy tuple-like dicts directly
        if isinstance(data, dict) and ("date" in data or "start_time" in data or "end_time" in data):
            date_obj = _parse_date_str(data.get("date"), today)
            start_t = _parse_time_str(data.get("start_time"))
            end_t = _parse_time_str(data.get("end_time"))
            return (date_obj, start_t, end_t)

        # If the model returned something unexpected, fall back to naive
        return _naive_parse(t, today)

    except Exception as e:
        print("[openai_handler] parse_query error:", e)
        return _naive_parse(t, today)