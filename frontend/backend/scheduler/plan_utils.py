from __future__ import annotations
from datetime import date as _date, time as _time, datetime as _dt, timedelta
from typing import List, Tuple, Optional, Dict, Iterable

# Types
TimeSlot = Tuple[_time, _time]           # (start_time, end_time)
DTSlot   = Tuple[_dt, _dt]               # (start_dt, end_dt)


def _as_dt(d: _date, t: _time) -> _dt:
    return _dt.combine(d, t)


def _clip_time(t: _time, lo: _time, hi: _time) -> _time:
    if t < lo:
        return lo
    if t > hi:
        return hi
    return t


def _slot_minutes(start_t: _time, end_t: _time) -> int:
    """Duration of a same-day (start<=end) slot in minutes."""
    s = _dt.combine(_date.today(), start_t)
    e = _dt.combine(_date.today(), end_t)
    return int((e - s).total_seconds() // 60)


def window_preset(name: Optional[str]) -> Optional[Tuple[_time, _time]]:
    """
    Useful presets for fuzzy windows.
    morning   = 08:00–12:00
    afternoon = 12:00–17:00
    evening   = 17:00–21:00
    workday   = 09:00–17:00
    anytime   = 00:00–23:59:59
    """
    if not name:
        return None
    n = name.strip().lower()
    if n == "morning":
        return (_time(8, 0), _time(12, 0))
    if n == "afternoon":
        return (_time(12, 0), _time(17, 0))
    if n == "evening":
        return (_time(17, 0), _time(21, 0))
    if n == "workday":
        return (_time(9, 0), _time(17, 0))
    if n in ("anytime", "all day", "allday"):
        return (_time(0, 0), _time(23, 59, 59))
    return None


def compute_free_slots_for_date(
    appts: Iterable,
    day_start: _time = _time(0, 0),
    day_end: _time = _time(23, 59, 59),
    min_minutes: int = 0,
    window_start: Optional[_time] = None,
    window_end: Optional[_time] = None
) -> List[TimeSlot]:
    """
    Given appointments for a single day (objects with .start_time/.end_time),
    return sorted free time slots as [(start_time, end_time), ...],
    optionally intersected with a daily window and filtered by minimum duration.
    """
    # Normalize + sort
    appts_sorted = sorted(list(appts), key=lambda a: (a.start_time, a.end_time))

    # Merge-overlap sweep using 'prev_end'
    free: List[TimeSlot] = []
    prev_end = day_start
    for a in appts_sorted:
        st = max(a.start_time, day_start)
        et = min(a.end_time, day_end)
        if et <= day_start or st >= day_end:
            # out of the day bounds
            continue

        if st > prev_end:
            free.append((prev_end, st))
        if et > prev_end:
            prev_end = et

    if prev_end < day_end:
        free.append((prev_end, day_end))

    # Intersect with optional window
    if window_start and window_end:
        wstart = max(window_start, day_start)
        wend = min(window_end, day_end)
        clipped: List[TimeSlot] = []
        for s, e in free:
            cs = max(s, wstart)
            ce = min(e, wend)
            if cs < ce:
                clipped.append((cs, ce))
        free = clipped

    # Filter by min duration
    if min_minutes and min_minutes > 0:
        free = [(s, e) for (s, e) in free if _slot_minutes(s, e) >= min_minutes]

    return free


def add_buffers(
    start_t: _time,
    end_t: _time,
    pre_min: int = 0,
    post_min: int = 0,
    day_start: _time = _time(0, 0),
    day_end: _time = _time(23, 59, 59)
) -> TimeSlot:
    """
    Apply buffers before/after a slot and clamp within the day bounds.
    """
    s_dt = _dt.combine(_date.today(), start_t) - timedelta(minutes=pre_min)
    e_dt = _dt.combine(_date.today(), end_t) + timedelta(minutes=post_min)
    s = _clip_time(s_dt.time(), day_start, day_end)
    e = _clip_time(e_dt.time(), day_start, day_end)
    if e <= s:
        # Degenerate after clamping; return original as fallback
        return (start_t, end_t)
    return (s, e)


def first_fit_in_slots(
    slots: List[TimeSlot],
    duration_minutes: int
) -> Optional[TimeSlot]:
    """
    Pick the earliest slot that can fit 'duration_minutes'.
    """
    for s, e in sorted(slots):
        if _slot_minutes(s, e) >= duration_minutes:
            # Allocate at the start of the slot
            end_dt = (_dt.combine(_date.today(), s) + timedelta(minutes=duration_minutes)).time()
            return (s, end_dt)
    return None


def find_first_slot_in_range(
    db_session,
    start_date: _date,
    end_date: _date,
    duration_minutes: int,
    window_start: Optional[_time] = None,
    window_end: Optional[_time] = None,
    skip_weekends: bool = False,
    day_start: _time = _time(0, 0),
    day_end: _time = _time(23, 59, 59),
    get_appts_for_date_callable=None,
) -> Optional[Tuple[_date, _time, _time]]:
    """
    Iterate from start_date to end_date, compute daily free slots (respecting optional
    window + min duration), and return the first day/time that can host the meeting.

    Returns: (date, start_time, end_time) or None if no fit found.
    """
    if get_appts_for_date_callable is None:
        # Lazy import to avoid circulars; caller can also pass a custom function
        from crud import get_appointments_by_date as _get_by_date
        get_appts_for_date_callable = _get_by_date

    d = start_date
    while d <= end_date:
        if skip_weekends and d.isoweekday() in (6, 7):
            d += timedelta(days=1)
            continue

        appts = get_appts_for_date_callable(db_session, d)
        free = compute_free_slots_for_date(
            appts,
            day_start=day_start,
            day_end=day_end,
            min_minutes=duration_minutes,
            window_start=window_start,
            window_end=window_end,
        )
        fit = first_fit_in_slots(free, duration_minutes)
        if fit:
            s, e = fit
            return (d, s, e)
        d += timedelta(days=1)
    return None


def expand_window_keyword(window: Optional[str]) -> Tuple[Optional[_time], Optional[_time]]:
    """
    Convenience helper: 'morning'|'afternoon'|'evening'|'workday'|'anytime' -> (start_t,end_t)
    Returns (None, None) if unknown.
    """
    preset = window_preset(window)
    if preset:
        return preset
    return (None, None)


def total_booked_minutes_for_date(appts: Iterable) -> int:
    """Aggregate total minutes already booked for a given day (simple helper)."""
    total = 0
    for a in appts:
        total += _slot_minutes(a.start_time, a.end_time)
    return total