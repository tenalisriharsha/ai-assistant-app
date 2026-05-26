from datetime import date as _date, time as _time, timedelta, datetime as _dt
from calendar import monthrange
from typing import Optional, Tuple, List


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


def _month_bounds(year: int, month: int) -> Tuple[_date, _date]:
    first = _date(year, month, 1)
    last = _date(year, month, monthrange(year, month)[1])
    return first, last


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


def _tz_to_local_date_time(d: _date, t: _time, tz_str: str) -> Tuple[_date, _time]:
    try:
        from zoneinfo import ZoneInfo
    except Exception:
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


def _parse_date_range_param(dr) -> Optional[Tuple[_date, _date]]:
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


# forward reference for _to_date used in _parse_date_range_param
from .parsing import _to_date
