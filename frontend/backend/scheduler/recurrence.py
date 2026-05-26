# scheduler/recurrence.py
"""
Minimal recurrence helpers for an AI scheduler.

This module is OPTIONAL. Your current app.py works without it.
Use these helpers only when you want more advanced recurrence
(such as "first Friday of each month", "every 2 weeks", etc).

All functions return a list[date] for the *dates* on which
events should occur. You can then attach times/durations in app.py.
"""

from __future__ import annotations
from datetime import date, timedelta
from typing import List, Optional

# Python weekday(): Monday=0 .. Sunday=6
WEEKDAY_NAME_TO_INT = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

def _clamp_to_weekday(d: date, weekday: int) -> date:
    """Return the next date on/after d that is the given weekday."""
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset)

def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> Optional[date]:
    """
    Return the n-th weekday of the month (n=1..4) or last (n=-1).
    Example: first Friday (weekday=4, n=1), last Thursday (3, -1).
    """
    if n == -1:  # last weekday of month
        # go to next month, step back until weekday matches
        if month == 12:
            d = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            d = date(year, month + 1, 1) - timedelta(days=1)
        while d.weekday() != weekday:
            d -= timedelta(days=1)
        return d

    if n < 1 or n > 4:
        return None

    # first day of month -> first occurrence of weekday
    first = date(year, month, 1)
    first_target = _clamp_to_weekday(first, weekday)
    # n-th is + 7*(n-1) days after first occurrence
    return first_target + timedelta(days=7 * (n - 1))

def expand_daily(start_date: date, count: int, interval_days: int = 1) -> List[date]:
    """DAILY every 'interval_days' days."""
    out: List[date] = []
    d = start_date
    for _ in range(max(0, count)):
        out.append(d)
        d += timedelta(days=max(1, interval_days))
    return out

def expand_weekdays(start_date: date, count: int) -> List[date]:
    """Weekdays only (Mon–Fri)."""
    out: List[date] = []
    d = start_date
    while len(out) < max(0, count):
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out

def expand_weekly(start_date: date, count: int, weekday: int, interval_weeks: int = 1) -> List[date]:
    """
    WEEKLY on a given weekday, repeating every 'interval_weeks' (>=1).
    Example: every 2 weeks on Tuesday -> interval_weeks=2, weekday=1.
    """
    out: List[date] = []
    first = _clamp_to_weekday(start_date, weekday)
    step = timedelta(weeks=max(1, interval_weeks))
    d = first
    for _ in range(max(0, count)):
        out.append(d)
        d += step
    return out

def expand_monthly_byday(start_date: date, count: int, weekday: int, bysetpos: int) -> List[date]:
    """
    MONTHLY on the nth (or last) weekday of each month.
    weekday: Monday=0..Sunday=6
    bysetpos: 1,2,3,4 or -1 for 'last'
    Starts from start_date's month.
    """
    out: List[date] = []
    y, m = start_date.year, start_date.month

    for _ in range(max(0, count)):
        d = _nth_weekday_of_month(y, m, weekday, bysetpos)
        if d and d >= start_date:
            out.append(d)
        elif d and d < start_date:
            # if this month's occurrence already passed, skip it
            pass

        # next month
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1

    # If the very first month was skipped (because it was before start_date),
    # we might be short one; keep loop simple for now.
    return out

def weekday_from_name(name: str) -> Optional[int]:
    """Map 'Mon', 'Monday', etc. to 0..6; returns None if unknown."""
    return WEEKDAY_NAME_TO_INT.get(name.strip().lower())


# ---------- New helpers (count or date-bounded variants) ----------

def expand_daily_until(start_date: date, until_date: date, interval_days: int = 1) -> List[date]:
    """
    DAILY every 'interval_days' days, inclusive of both start_date and until_date.
    If until_date < start_date, the dates are swapped.
    """
    if until_date < start_date:
        start_date, until_date = until_date, start_date
    out: List[date] = []
    step = max(1, interval_days)
    d = start_date
    while d <= until_date:
        out.append(d)
        d += timedelta(days=step)
    return out

def expand_weekly_until(start_date: date, until_date: date, weekday: int, interval_weeks: int = 1) -> List[date]:
    """
    WEEKLY on a given weekday, repeating every 'interval_weeks' weeks, inclusive.
    Supports phrases like: "every Thursday ... until Oct 25".
    """
    if until_date < start_date:
        start_date, until_date = until_date, start_date
    out: List[date] = []
    first = _clamp_to_weekday(start_date, weekday % 7)
    step = timedelta(weeks=max(1, interval_weeks))
    d = first
    while d <= until_date:
        out.append(d)
        d += step
    return out

def expand_range_by_weekdays(start_date: date, end_date: date, weekdays: List[int]) -> List[date]:
    """
    Return all dates in [start_date, end_date] whose weekday is in `weekdays`.
    Useful for: "between Oct 1 and Oct 31 every Mon/Wed/Fri".
    """
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    wset = {int(w) % 7 for w in (weekdays or [])}
    if not wset:
        return []
    out: List[date] = []
    d = start_date
    while d <= end_date:
        if d.weekday() in wset:
            out.append(d)
        d += timedelta(days=1)
    return out

def expand_monthly_byday_until(start_date: date, until_date: date, weekday: int, bysetpos: int) -> List[date]:
    """
    MONTHLY on the nth (or last) weekday of each month, up to `until_date` (inclusive).
    bysetpos: 1,2,3,4 or -1 for 'last'.
    Example: first Friday of the month until Dec 2025.
    """
    if until_date < start_date:
        start_date, until_date = until_date, start_date
    out: List[date] = []
    # iterate month-by-month starting from the start month
    y, m = start_date.year, start_date.month
    # anchor to the first of the starting month
    cur = date(y, m, 1)
    while cur <= until_date:
        cand = _nth_weekday_of_month(cur.year, cur.month, weekday % 7, bysetpos)
        if cand and start_date <= cand <= until_date:
            out.append(cand)
        # increment one month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return out