import re
from datetime import date as _date, time as _time, timedelta
from typing import Optional, Tuple, List

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


def _parse_month_name_token(tok: str) -> Optional[int]:
    if not tok:
        return None
    return _month_map.get(tok.strip().lower())


def _strip_ordinals(s: str) -> str:
    return re.sub(r'\b(\d{1,2})(st|nd|rd|th)\b', r'\1', s, flags=re.IGNORECASE)


def _parse_human_date(text: str, *, reference: Optional[_date] = None) -> Optional[_date]:
    if not text:
        return None
    reference = reference or _date.today()

    def _strip_ordinals_local(s: str) -> str:
        s = re.sub(r'\b(\d{1,2})(st|nd|rd|th)\b', r'\1', s, flags=re.IGNORECASE)
        s = re.sub(r'\s+', ' ', s)
        return s

    t = _strip_ordinals_local(text.strip().lower())
    mon_pat = r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'

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
    if not text:
        return None
    m = re.search(r'(?:with\s+the\s+title|titled|called|named)\s+[“"]?([^""]+?)[""]?(?:\s|$)', text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else None


def _parse_month_day_range_text(text: str) -> Optional[Tuple[_date, _date]]:
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
    order = [0,1,2,3,4,5,6]
    wset = {w for w in wdays}
    return [w for w in order if w in wset]


def _parse_time_range_text(text: str) -> Optional[Tuple[_time, _time]]:
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

    m = re.search(r"(\d+)\s*h(?:ours?|rs?)?\s*(\d+)\s*m(?:in(?:ute)?s?)?", tl)
    if m:
        try:
            return int(m.group(1)) * 60 + int(m.group(2))
        except Exception:
            return None

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hours?|hrs?)\b", tl)
    if m:
        try:
            return max(1, int(round(float(m.group(1)) * 60)))
        except Exception:
            return None

    m = re.search(r"(\d+)\s*[-\s]?(?:minutes?|mins?|m)\b", tl)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None

    m = re.search(r"(\d+)\s*[-\s]?(?:hr|hrs)\b", tl)
    if m:
        try:
            return int(m.group(1)) * 60
        except Exception:
            return None

    if re.search(r"\b(an|one)\s+hour\b", tl):
        return 60
    if re.search(r"\bhalf[-\s]+an?\s+hour\b", tl) or re.search(r"\ban?\s+half[-\s]+hour\b", tl):
        return 30
    if re.search(r"\b(one|1)\s+and\s+a\s+half\s+hours?\b", tl) or re.search(r"\ban?\s+hour\s+and\s+a\s+half\b", tl):
        return 90

    return None


def _parse_lead_from_text(text: str) -> Optional[int]:
    if not text:
        return None
    tl = text.lower()
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
