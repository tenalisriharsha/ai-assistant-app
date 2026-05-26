from datetime import date as _date, time as _time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .dates import _as_delta, _add_minutes, _duration_minutes


def _compute_free_slots(appts):
    day_start = _time(0, 0)
    day_end = _time(23, 59, 59)
    free = []
    items = []
    for a in appts or []:
        try:
            items.append((a.start_time, a.end_time))
        except Exception:
            continue
    items = [(s, e) for (s, e) in items if s and e and e > s]
    items.sort(key=lambda x: x[0])

    merged = []
    for s, e in items:
        if not merged:
            merged.append((s, e))
        else:
            ps, pe = merged[-1]
            if s <= pe:
                merged[-1] = (ps, max(pe, e))
            else:
                merged.append((s, e))

    prev_end = day_start
    for s, e in merged:
        if s > prev_end:
            free.append({"start": prev_end.isoformat(), "end": s.isoformat()})
        if e > prev_end:
            prev_end = e
    if prev_end < day_end:
        free.append({"start": prev_end.isoformat(), "end": day_end.isoformat()})
    return free


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


def _resolve_reschedule_times(appt, new_date: Optional[_date], new_start: Optional[_time], new_end: Optional[_time]) -> tuple[_date, _time, _time]:
    d = appt.date
    s = appt.start_time
    e = appt.end_time

    if new_date:
        d = new_date

    dur = _duration_minutes(s, e)
    if dur <= 0:
        dur = 60

    s2 = new_start if new_start else s
    e2 = new_end   if new_end   else e

    if new_start and not new_end:
        e2 = _add_minutes(s2, dur)
    elif new_end and not new_start:
        s2 = _add_minutes(new_end, -dur)
    elif new_start and new_end:
        if _as_delta(new_start, new_end).total_seconds() <= 0:
            e2 = _add_minutes(new_start, dur)
            s2 = new_start

    return d, s2, e2
