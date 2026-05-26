# scheduler/templates.py
"""
Lightweight template engine for multi-event plans in your AI scheduler.

This module is OPTIONAL. It does NOT change current behavior unless you import
and call it. It returns *proposed* blocks (date/start/end/title/etc) that your
app can either display to the user or persist as appointments.

Features:
- Built-in templates (Pitch prep, Interview loop, Deep work sprint, Pomodoro stack)
- Register your own templates at runtime
- Simple windowing (morning/afternoon/evening) + fixed times
- Optional "is_free" callback so you can respect existing calendar availability
- No DB writes here—pure planning utilities
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, time, timedelta, datetime
from typing import Callable, Dict, List, Optional, Tuple, Any
import re

# -----------------------------
# Types & registry
# -----------------------------

WindowName = str  # 'morning' | 'afternoon' | 'evening'
IsFreeFn = Callable[[date, time, time], bool]  # returns True if slot is free

# Map friendly windows to default ranges (24h)
WINDOWS: Dict[WindowName, Tuple[str, str]] = {
    "morning": ("08:00", "12:00"),
    "afternoon": ("12:00", "17:00"),
    "evening": ("17:00", "21:00"),
}

@dataclass
class Step:
    title: str
    duration_min: int
    day_offset: int = 0
    # Either give a fixed 'time' (e.g., '17:00') OR a 'window' (e.g., 'afternoon')
    time_str: Optional[str] = None
    window: Optional[WindowName] = None
    label: Optional[str] = None        # category/tag
    location: Optional[str] = None
    modality: Optional[str] = None     # 'zoom', 'in-person', etc.
    tentative: bool = False
    buffer_before_min: int = 0
    buffer_after_min: int = 0
    notes: Optional[str] = None

@dataclass
class TemplateDef:
    name: str
    steps: List[Step] = field(default_factory=list)
    default_label: Optional[str] = None
    default_location: Optional[str] = None
    default_modality: Optional[str] = None

# Global registry (you can add more at runtime)
_TEMPLATE_REGISTRY: Dict[str, TemplateDef] = {}

def register_template(tpl: TemplateDef) -> None:
    _TEMPLATE_REGISTRY[tpl.name.lower()] = tpl

def list_templates() -> List[str]:
    return sorted(_TEMPLATE_REGISTRY.keys())

def get_template(name: str) -> Optional[TemplateDef]:
    return _TEMPLATE_REGISTRY.get(name.lower())

# -----------------------------
# Time helpers
# -----------------------------

_TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?$")

def _parse_time(s: str) -> time:
    """
    Accepts 'H:MM', 'HH:MM', or 'HH:MM:SS' (24h).
    """
    m = _TIME_RE.match(s.strip())
    if not m:
        raise ValueError(f"Invalid time string: {s}")
    hh = int(m.group(1)); mm = int(m.group(2) or 0); ss = int(m.group(3) or 0)
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        raise ValueError(f"Invalid time: {s}")
    return time(hh, mm, ss)

def _to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute

def _from_minutes(m: int) -> time:
    m = max(0, min(m, 23*60 + 59))
    return time(m // 60, m % 60, 0)

def _add_minutes(t: time, delta_min: int) -> time:
    return _from_minutes(_to_minutes(t) + delta_min)

def _overlaps(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return a_start < b_end and b_start < a_end

# -----------------------------
# Core planner
# -----------------------------

def expand_template(
    template_name: str,
    anchor_date: date,
    *,
    work_hours: Tuple[str, str] = ("08:00", "18:00"),
    windows: Optional[Dict[WindowName, Tuple[str, str]]] = None,
    step_granularity_min: int = 5,
    is_free: Optional[IsFreeFn] = None,
) -> List[Dict[str, Any]]:
    """
    Expand a template into concrete proposed blocks.

    Returns a list of dicts with keys:
      - date (iso str)
      - start_time (iso str)
      - end_time (iso str)
      - title
      - label, location, modality, tentative, notes (if provided)

    Parameters:
      template_name: key from registry
      anchor_date: date to start from (steps use day_offset relative to this)
      work_hours: overall allowable daily range ('HH:MM', 'HH:MM')
      windows: override default WINDOWS if desired
      step_granularity_min: search step for fitting within a window
      is_free: optional callback(date, start, end) -> bool to respect calendar
               availability; if None, we only avoid collisions with blocks
               we place in this expansion call.
    """
    tpl = get_template(template_name)
    if not tpl:
        raise ValueError(f"Unknown template: '{template_name}'. Registered: {list_templates()}")

    win = windows or WINDOWS
    work_start = _parse_time(work_hours[0])
    work_end   = _parse_time(work_hours[1])

    # In-memory schedule to avoid self-overlap while placing steps
    scheduled_by_day: Dict[date, List[Tuple[time, time]]] = {}

    def _day_list(d: date) -> List[Tuple[time, time]]:
        return scheduled_by_day.setdefault(d, [])

    proposed: List[Dict[str, Any]] = []

    for s in tpl.steps:
        d = anchor_date + timedelta(days=s.day_offset)

        # Determine target time range for this step
        if s.time_str:
            start_candidate = _parse_time(s.time_str)
            latest_end = _add_minutes(start_candidate, s.duration_min)
            # Include buffers on the block itself
            block_start = _add_minutes(start_candidate, -s.buffer_before_min)
            block_end   = _add_minutes(latest_end, s.buffer_after_min)

            # Work-hours clamp
            if block_start < work_start or block_end > work_end:
                # If fixed time violates work hours, we still place it, but you could
                # choose to clamp; here we proceed as-is to honor the instruction.
                pass

            # Check overlaps with already planned blocks and optional is_free
            if any(_overlaps(block_start, block_end, a, b) for a, b in _day_list(d)):
                # Try to nudge forward by granularity until it fits within work hours
                start_candidate = _nudge_to_fit(
                    d, start_candidate, s.duration_min, _day_list, step_granularity_min,
                    work_start, work_end, s.buffer_before_min, s.buffer_after_min, is_free
                )
                latest_end = _add_minutes(start_candidate, s.duration_min)
                block_start = _add_minutes(start_candidate, -s.buffer_before_min)
                block_end   = _add_minutes(latest_end, s.buffer_after_min)

            # Final check with is_free
            if is_free and not is_free(d, block_start, block_end):
                # nudge until free or fail
                start_candidate = _nudge_to_fit(
                    d, start_candidate, s.duration_min, _day_list, step_granularity_min,
                    work_start, work_end, s.buffer_before_min, s.buffer_after_min, is_free
                )
                latest_end = _add_minutes(start_candidate, s.duration_min)
                block_start = _add_minutes(start_candidate, -s.buffer_before_min)
                block_end   = _add_minutes(latest_end, s.buffer_after_min)

            _day_list(d).append((block_start, block_end))
            proposed.append(_block_dict(d, start_candidate, latest_end, s, tpl))
            continue

        # Windowed placement
        win_name = (s.window or "morning").lower()
        if win_name not in win:
            raise ValueError(f"Unknown window '{s.window}'. Use one of {list(win.keys())}")

        win_start = _parse_time(win[win_name][0])
        win_end   = _parse_time(win[win_name][1])
        # Clip window to work hours
        window_start = max(win_start, work_start)
        window_end   = min(win_end, work_end)

        start_candidate = _fit_in_window(
            d, s.duration_min, _day_list, step_granularity_min,
            window_start, window_end, s.buffer_before_min, s.buffer_after_min, is_free
        )
        if start_candidate is None:
            # Could not fit within window—attempt within the whole work hours as fallback
            start_candidate = _fit_in_window(
                d, s.duration_min, _day_list, step_granularity_min,
                work_start, work_end, s.buffer_before_min, s.buffer_after_min, is_free
            )
            if start_candidate is None:
                # Give up; return proposed as-is (caller can notify)
                continue

        latest_end = _add_minutes(start_candidate, s.duration_min)
        block_start = _add_minutes(start_candidate, -s.buffer_before_min)
        block_end   = _add_minutes(latest_end, s.buffer_after_min)
        _day_list(d).append((block_start, block_end))
        proposed.append(_block_dict(d, start_candidate, latest_end, s, tpl))

    # Sort for nice output
    proposed.sort(key=lambda x: (x["date"], x["start_time"]))
    return proposed

def _fit_in_window(
    day: date,
    duration_min: int,
    day_list_fn,
    step_granularity_min: int,
    win_start: time,
    win_end: time,
    buf_before: int,
    buf_after: int,
    is_free: Optional[IsFreeFn],
) -> Optional[time]:
    """Find the earliest start time within [win_start, win_end] that fits."""
    cur = win_start
    while _add_minutes(cur, duration_min + buf_before + buf_after) <= win_end:
        block_start = _add_minutes(cur, -buf_before)
        block_end   = _add_minutes(_add_minutes(cur, duration_min), buf_after)
        if all(not _overlaps(block_start, block_end, a, b) for a, b in day_list_fn(day)):
            if not is_free or is_free(day, block_start, block_end):
                return cur
        cur = _add_minutes(cur, step_granularity_min)
    return None

def _nudge_to_fit(
    day: date,
    start_candidate: time,
    duration_min: int,
    day_list_fn,
    step_granularity_min: int,
    work_start: time,
    work_end: time,
    buf_before: int,
    buf_after: int,
    is_free: Optional[IsFreeFn],
) -> time:
    """Move forward in small steps until a non-overlapping slot is found or we hit work_end."""
    cur = max(start_candidate, work_start)
    while _add_minutes(cur, duration_min + buf_before + buf_after) <= work_end:
        block_start = _add_minutes(cur, -buf_before)
        block_end   = _add_minutes(_add_minutes(cur, duration_min), buf_after)
        if all(not _overlaps(block_start, block_end, a, b) for a, b in day_list_fn(day)):
            if not is_free or is_free(day, block_start, block_end):
                return cur
        cur = _add_minutes(cur, step_granularity_min)
    return start_candidate  # fallback (caller may still handle)

def _block_dict(d: date, start_t: time, end_t: time, s: Step, tpl: TemplateDef) -> Dict[str, Any]:
    return {
        "date": d.isoformat(),
        "start_time": start_t.isoformat(timespec="minutes"),
        "end_time": end_t.isoformat(timespec="minutes"),
        "title": s.title,
        "label": s.label or tpl.default_label,
        "location": s.location or tpl.default_location,
        "modality": s.modality or tpl.default_modality,
        "tentative": bool(s.tentative),
        "notes": s.notes,
    }

# -----------------------------
# Built-in templates
# -----------------------------

# 1) Pitch prep plan
register_template(TemplateDef(
    name="pitch_prep",
    steps=[
        Step(title="Research", duration_min=60, day_offset=0, window="afternoon", label="Work"),
        Step(title="Draft", duration_min=120, day_offset=1, window="morning", label="Work"),
        Step(title="Rehearsal", duration_min=45, day_offset=1, time_str="17:00", label="Work", tentative=True),
    ],
    default_label="Work",
))

# 2) Interview loop
register_template(TemplateDef(
    name="interview_loop",
    steps=[
        Step(title="Intro", duration_min=15, day_offset=0, time_str="09:00", modality="zoom"),
        Step(title="Technical Screen", duration_min=60, day_offset=0, time_str="10:00", modality="zoom",
             buffer_after_min=10, notes="Allow transition"),
        Step(title="Portfolio Review", duration_min=45, day_offset=0, time_str="11:15", modality="zoom"),
        Step(title="Debrief", duration_min=30, day_offset=0, time_str="13:00", modality="zoom"),
    ],
    default_label="Hiring",
))

# 3) Deep work sprint (3 mornings)
register_template(TemplateDef(
    name="deep_work_sprint",
    steps=[
        Step(title="Deep Work Block", duration_min=90, day_offset=0, window="morning", label="Focus"),
        Step(title="Deep Work Block", duration_min=90, day_offset=1, window="morning", label="Focus"),
        Step(title="Deep Work Block", duration_min=90, day_offset=2, window="morning", label="Focus"),
    ],
    default_label="Focus",
))

# 4) Pomodoro stack (2x25 with 5-minute breaks automatically implied by caller)
register_template(TemplateDef(
    name="pomodoro_stack",
    steps=[
        Step(title="Pomodoro 1", duration_min=25, day_offset=0, window="afternoon", label="Task"),
        Step(title="Pomodoro 2", duration_min=25, day_offset=0, window="afternoon", label="Task",
             buffer_before_min=5),
    ],
    default_label="Task",
))