"""NL fast-path handlers — pure functions that return Optional[Response].

Each handler receives (db, query, q_lower, data) and either:
  - returns a Flask Response (matched)
  - returns None (fall through to next handler)
"""

import re
from typing import Any, Dict, List, Optional
from datetime import date as _date, time as _time, timedelta, datetime as _dt
from flask import jsonify

from utils import (
    _to_date, _to_time, _parse_human_date, _extract_title_from_text,
    _parse_month_day_range_text, _parse_weekday_list, _parse_time_range_text,
    _parse_duration_minutes_from_text, _parse_lead_from_text,
    _add_minutes, _duration_minutes, _month_bounds, _dt_combine,
    _normalize_tz, _tz_to_local_date_time, _parse_date_range_param,
    _iter_dates_range,
    _compute_free_slots, _find_first_free_slot, _find_all_free_slots,
    _serialize_appt, _serialize_reminder,
    _fuzzy_match, _match_opts, _resolve_reschedule_times,
)
from crud import (
    get_appointment_by_id, get_appointments_by_date, get_appointments_for_week,
    get_appointments_between as crud_get_appointments_between,
    get_next_appointment, search_appointments_by_description,
    get_appointments_on_weekends, get_appointments_after_time,
    count_appointments_in_range, get_conflicting_appointments,
    create_appointment_if_free, bulk_create_appointments, bulk_create_appointments_lenient,
    create_appointment, find_conflicts_for_slot,
    find_appointments, update_appointment_time, update_appointment_title,
    delete_appointment_by_id,
    create_reminder, create_reminder_for_appointment,
)

# Optional recurrence helpers
try:
    from scheduler.recurrence import expand_range_by_weekdays
    HAVE_RECURRENCE_HELPERS = True
except Exception:
    HAVE_RECURRENCE_HELPERS = False
    expand_range_by_weekdays = None


# ---------------------------------------------------------------------------
# 1) NL delete / cancel (LLM-independent fast path)
# ---------------------------------------------------------------------------
def handle_nl_delete_cancel(db, query, q_lower, data):
    if not re.search(r'\b(delete|cancel|remove)\b', q_lower):
        return None

    # 1) If an explicit numeric id is present (e.g., "id 123" or "#123"), use it.
    m_id = re.search(r'\b(?:id|#)\s*(\d+)\b', q_lower)
    if m_id:
        try:
            appt = get_appointment_by_id(db, int(m_id.group(1)))
        except Exception:
            appt = None
        if not appt:
            return jsonify({'error': 'Not found'}), 404
        ok = delete_appointment_by_id(db, int(appt.id))
        if ok:
            return jsonify({'deleted': True, 'id': int(appt.id)})
        return jsonify({'error': 'Not found'}), 404

    # 2) Try to extract a title from natural language
    title = _extract_title_from_text(query)

    # Also accept quoted phrases as the title (e.g., delete "walk")
    if not title:
        qm = re.search(r'"([^"]+)"|\'([^\']+)\'', query)
        if qm:
            for g in qm.groups():
                if g:
                    title = g.strip()
                    break

    # As a last resort, accept "with the title X" without quotes even if not caught above
    if not title:
        m_named = re.search(r'(?:with\s+the\s+title|titled|called|named)\s+(.+)$', q_lower)
        if m_named:
            title = m_named.group(1).strip()

    # 3) Resolve the target date or search window
    target_date = None
    # ISO date in text
    m_iso = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', q_lower)
    if m_iso:
        target_date = _to_date(m_iso.group(1))
    # Spoken date forms like "29th August"
    if not target_date:
        try:
            target_date = _parse_human_date(query)
        except Exception:
            target_date = None
    if not target_date and 'today' in q_lower:
        target_date = _date.today()
    if not target_date and 'tomorrow' in q_lower:
        target_date = _date.today() + timedelta(days=1)

    # 4) Build candidates and delete
    matches = []
    try:
        if target_date:
            # Search only on that day using fuzzy title (if provided)
            matches = find_appointments(
                db,
                target_date=target_date,
                term=(title or None),
                case_insensitive=True,
                min_ratio=0.60,
            ) or []
        else:
            # No date given: try today first; if no unique match, widen to next 7 days
            today_local = _date.today()
            todays = get_appointments_by_date(db, today_local)
            if title:
                todays = [a for a in todays if _fuzzy_match(a.description or '', title, case_insensitive=True, min_ratio=0.60)]
            if len(todays) == 1:
                matches = todays
            else:
                win = get_appointments_for_week(db, today_local, today_local + timedelta(days=7))
                if title:
                    win = [a for a in win if _fuzzy_match(a.description or '', title, case_insensitive=True, min_ratio=0.60)]
                matches = win
    except Exception:
        matches = []

    # No matches → 404
    if not matches:
        return jsonify({
            'error': 'No matching appointment found to delete.',
            'hint': 'Try including a date (YYYY-MM-DD) or the exact title in quotes.'
        }), 404

    # Multiple matches → surface candidates so the UI can disambiguate by id
    if len(matches) > 1:
        out = [
            {
                'id': a.id,
                'date': a.date.isoformat(),
                'start_time': a.start_time.isoformat(),
                'end_time': a.end_time.isoformat(),
                'title': (a.description or getattr(a, 'title', '') or '')[:255],
            }
            for a in sorted(matches, key=lambda x: (x.date, x.start_time, x.id or 0))
        ]
        return jsonify({'error': 'Ambiguous selector matched multiple appointments.', 'candidates': out}), 409

    # Exactly one → delete it
    target = matches[0]
    try:
        ok = delete_appointment_by_id(db, int(target.id))
    except Exception as e:
        return jsonify({'error': 'Delete failed', 'details': str(e)}), 500

    if ok:
        return jsonify({'deleted': True, 'id': int(target.id)})
    return jsonify({'error': 'Not found'}), 404


# ---------------------------------------------------------------------------
# 2) Reminders quick NL paths
# ---------------------------------------------------------------------------
def handle_nl_reminders(db, query, q_lower, data):
    if not any(k in q_lower for k in ['remind me', 'notify me', 'alert me', 'ping me', 'nudge me']):
        return None

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
        return jsonify({'reminder': _serialize_reminder(r, db)})
    # "before [meeting/title]"
    if 'before' in q_lower:
        lead2 = lead or 15
        # Find quoted text first
        qm = re.search(r'"([^"]+)"|\'([^\']+)\'', query)
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
            return jsonify({'reminder': _serialize_reminder(r, db)})
    return jsonify({'error': 'Could not parse reminder time. Try "Remind me at 3pm to …"'}), 400


# ---------------------------------------------------------------------------
# 3) Free/availability
# ---------------------------------------------------------------------------
def handle_nl_free_availability(db, query, q_lower, data):
    if not (
        'free' in q_lower or 'free time' in q_lower or 'availability' in q_lower or 'available' in q_lower or
        'open slot' in q_lower or 'open slots' in q_lower or 'free slot' in q_lower or 'free slots' in q_lower or 'avail' in q_lower
    ):
        return None

    if 'tomorrow' in q_lower:
        target = _date.today() + timedelta(days=1)
    else:
        mdate = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', q_lower)
        target = _to_date(mdate.group(1)) if mdate else _date.today()
    appts = get_appointments_by_date(db, target)
    dur_req = _parse_duration_minutes_from_text(q_lower) or 0
    rng = _parse_time_range_text(q_lower)
    w_start = rng[0] if rng else _time(0, 0, 0)
    w_end = rng[1] if rng else _time(23, 59, 59)
    if dur_req > 0:
        props = _find_all_free_slots(appts, int(dur_req), w_start, w_end, limit=5)
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
    return jsonify({'free': free})


# ---------------------------------------------------------------------------
# 4) "How many … this month?"
# ---------------------------------------------------------------------------
def handle_nl_count_month(db, query, q_lower, data):
    if not (re.search(r'\bhow\s+many\b', q_lower) and 'month' in q_lower):
        return None
    today = _date.today()
    start_month = today.replace(day=1)
    next_month = (start_month.replace(year=start_month.year + 1, month=1, day=1)
                  if start_month.month == 12 else start_month.replace(month=start_month.month + 1, day=1))
    end_month = next_month - timedelta(days=1)
    cnt = count_appointments_in_range(db, start_month, end_month)
    return jsonify({'count': cnt})


# ---------------------------------------------------------------------------
# 5) Title+timeframe queries
# ---------------------------------------------------------------------------
def _extract_title_timeframe(q_lower, query):
    """Shared regex for title+timeframe handlers."""
    m = re.search(
        r'(?:with\s+title|titled|called|named)\s*["\'\u201c\u201d]?(.+?)["\'\u201c\u201d]?(?=\s+(?:today|tomorrow|this\s+week|this\s+month|next\s+month)\b|[?.!,]|$)',
        q_lower
    )
    return m


def handle_nl_title_month(db, query, q_lower, data):
    m = _extract_title_timeframe(q_lower, query)
    if not (m and 'month' in q_lower):
        return None
    term = m.group(1).strip()
    term = re.sub(r'\b(?:today|tomorrow|this\s+week|this\s+month|next\s+month)\b.*$', '', term).strip()
    today = _date.today()
    start_month = today.replace(day=1)
    next_month = (start_month.replace(year=start_month.year + 1, month=1, day=1)
                  if start_month.month == 12 else
                  start_month.replace(month=start_month.month + 1, day=1))
    end_month = next_month - timedelta(days=1)
    appts = get_appointments_for_week(db, start_month, end_month)
    filtered = [a for a in appts if _fuzzy_match(
        a.description or '', term, case_insensitive=True, min_ratio=0.6
    )]
    print("TITLE_MONTH_FILTER_DEBUG:", {
        'term': term, 'count': len(filtered),
        'start_month': start_month.isoformat(), 'end_month': end_month.isoformat()
    })
    return jsonify({'appointments': [_serialize_appt(a) for a in filtered]})


def handle_nl_title_week(db, query, q_lower, data):
    m = _extract_title_timeframe(q_lower, query)
    if not (m and 'week' in q_lower):
        return None
    term = m.group(1).strip()
    term = re.sub(r'\b(?:today|tomorrow|this\s+week|this\s+month|next\s+month)\b.*$', '', term).strip()
    today = _date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    appts = get_appointments_for_week(db, start, end)
    filtered = [a for a in appts if _fuzzy_match(
        a.description or '', term, case_insensitive=True, min_ratio=0.6
    )]
    print("TITLE_WEEK_FILTER_DEBUG:", {
        'term': term, 'count': len(filtered),
        'start': start.isoformat(), 'end': end.isoformat()
    })
    return jsonify({'appointments': [_serialize_appt(a) for a in filtered]})


def handle_nl_title_next_month(db, query, q_lower, data):
    m = _extract_title_timeframe(q_lower, query)
    if not (m and 'next month' in q_lower):
        return None
    term = m.group(1).strip()
    term = re.sub(r'\b(?:today|tomorrow|this\s+week|this\s+month|next\s+month)\b.*$', '', term).strip()
    today = _date.today()
    start_month = (today.replace(year=today.year + 1, month=1, day=1)
                   if today.month == 12 else today.replace(month=today.month + 1, day=1))
    next_month = (start_month.replace(year=start_month.year + 1, month=1, day=1)
                  if start_month.month == 12 else start_month.replace(month=start_month.month + 1, day=1))
    end_month = next_month - timedelta(days=1)
    appts = get_appointments_for_week(db, start_month, end_month)
    filtered = [a for a in appts if _fuzzy_match(
        a.description or '', term, case_insensitive=True, min_ratio=0.6
    )]
    print("TITLE_NEXT_MONTH_FILTER_DEBUG:", {
        'term': term, 'count': len(filtered),
        'start_month': start_month.isoformat(), 'end_month': end_month.isoformat()
    })
    return jsonify({'appointments': [_serialize_appt(a) for a in filtered]})


def handle_nl_title_today(db, query, q_lower, data):
    m = _extract_title_timeframe(q_lower, query)
    if not (m and 'today' in q_lower):
        return None
    term = m.group(1).strip()
    term = re.sub(r'\b(?:today|tomorrow|this\s+week|this\s+month|next\s+month)\b.*$', '', term).strip().strip("'\"\u201c\u201d\u2018\u2019")
    today_d = _date.today()
    appts = get_appointments_by_date(db, today_d)
    filtered = [a for a in appts if _fuzzy_match(
        a.description or '', term, case_insensitive=True, min_ratio=0.6
    )]
    print("TITLE_TODAY_FILTER_DEBUG:", {
        'term': term, 'count': len(filtered), 'date': today_d.isoformat()
    })
    return jsonify({'appointments': [_serialize_appt(a) for a in filtered]})


def handle_nl_title_tomorrow(db, query, q_lower, data):
    m = _extract_title_timeframe(q_lower, query)
    if not (m and 'tomorrow' in q_lower):
        return None
    term = m.group(1).strip()
    term = re.sub(r'\b(?:today|tomorrow|this\s+week|this\s+month|next\s+month)\b.*$', '', term).strip().strip("'\"\u201c\u201d\u2018\u2019")
    tomorrow_d = _date.today() + timedelta(days=1)
    appts = get_appointments_by_date(db, tomorrow_d)
    filtered = [a for a in appts if _fuzzy_match(
        a.description or '', term, case_insensitive=True, min_ratio=0.6
    )]
    print("TITLE_TOMORROW_FILTER_DEBUG:", {
        'term': term, 'count': len(filtered), 'date': tomorrow_d.isoformat()
    })
    return jsonify({'appointments': [_serialize_appt(a) for a in filtered]})


def handle_nl_title_any(db, query, q_lower, data):
    # Title-only search (no timeframe specified)
    m_title_any = re.search(
        r'(?:with\s+title|titled|called|named)\s*["\'\u201c\u201d]?(.+?)["\'\u201c\u201d]?(?:\s*[?.!,]\s*|$)',
        query,
        flags=re.IGNORECASE
    )
    if not m_title_any:
        return None
    if any(kw in q_lower for kw in ['today', 'tomorrow', 'this week', 'this month', 'next month']):
        return None
    term = m_title_any.group(1).strip()
    term = re.sub(r'\b(?:today|tomorrow|this\s+week|this\s+month|next\s+month)\b.*$', '', term, flags=re.IGNORECASE).strip()
    term = term.strip("'\"\u201c\u201d\u2018\u2019").strip()
    appts = search_appointments_by_description(db, term) if term else []
    return jsonify({'appointments': [_serialize_appt(a) for a in appts]})


# ---------------------------------------------------------------------------
# 6) "How many … in the next 7 days / next week?"
# ---------------------------------------------------------------------------
def handle_nl_count_next_n_days(db, query, q_lower, data):
    m_how_many = re.search(r'\bhow\s+many\b', q_lower)
    if not m_how_many:
        return None
    if not (
        'next week' in q_lower or
        re.search(r'\bnext\s+(?:seven|7)\s+days\b', q_lower) or
        re.search(r'\bin\s+the\s+next\s+(?:seven|7)\s+days\b', q_lower) or
        re.search(r'\bnext\s+(\d{1,3})\s+days\b', q_lower)
    ):
        return None
    today = _date.today()
    days = 7
    m_num = re.search(r'\bnext\s+(\d{1,3})\s+days\b', q_lower)
    if m_num:
        try:
            days = max(1, min(365, int(m_num.group(1))))
        except Exception:
            days = 7
    elif 'next week' in q_lower:
        days = 7
    end = today + timedelta(days=days - 1)
    cnt = count_appointments_in_range(db, today, end)
    print('COUNT_NEXT_N_DAYS_DEBUG:', {'days': days, 'start': today.isoformat(), 'end': end.isoformat(), 'count': cnt})
    return jsonify({'count': cnt, 'start_date': today.isoformat(), 'end_date': end.isoformat(), 'scope': f'next_{days}_days'})


# ---------------------------------------------------------------------------
# 7) "After 6pm today …"
# ---------------------------------------------------------------------------
def handle_nl_after_time(db, query, q_lower, data):
    m_after = re.search(r'\bafter\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)', q_lower)
    if not (m_after and 'today' in q_lower):
        return None
    threshold = _to_time(m_after.group(1)) or _time(18, 0, 0)
    appts = get_appointments_after_time(db, _date.today(), threshold)
    return jsonify({'appointments': [_serialize_appt(a) for a in appts]})


# ---------------------------------------------------------------------------
# 8) NL rename / retitle
# ---------------------------------------------------------------------------
def handle_nl_rename(db, query, q_lower, data):
    if not re.search(r'\b(rename|retitle|change\s+title)\b', q_lower):
        return None

    raw = (query or "").strip()
    old_title = ""
    new_title = ""

    # 1) Quoted pattern: rename "gym" to "walk"
    m = re.search(
        r'(?:rename|retitle|change\s+title)\s+(?:my\s+)?(?:appointment\s+)?["\u201c\u201d\']([^"\u201c\u201d\']+)["\u201c\u201d\']\s*(?:to|->)\s*["\u201c\u201d\']([^"\u201c\u201d\']+)["\u201c\u201d\']',
        raw,
        flags=re.IGNORECASE,
    )
    if m:
        old_title = m.group(1).strip()
        new_title = m.group(2).strip()
    else:
        # 2) Generic unquoted form: "rename ... X ... to Y"
        raw_lower = raw.lower()
        idx_to = raw_lower.rfind(' to ')
        if idx_to != -1:
            new_title = raw[idx_to + 4:].strip().strip('.?!,\'"\u201c\u201d\u2018\u2019')
            lhs = raw[:idx_to]
        else:
            lhs = raw

        m2 = re.search(r'(?:rename|retitle|change\s+title)\b(.*)$', lhs, flags=re.IGNORECASE)
        segment = m2.group(1) if m2 else lhs

        m3 = re.search(
            r'(?:with\s+the\s+title|with\s+title|titled|called|named)\s+(.+)$',
            segment,
            flags=re.IGNORECASE,
        )
        if m3:
            old_title_raw = m3.group(1).strip()
        else:
            old_title_raw = segment.strip()

        old_title = re.sub(
            r'\b(today|tomorrow|this week|this month|next month|appointment|my|the|at|on|to)\b',
            ' ',
            old_title_raw,
            flags=re.IGNORECASE,
        )
        old_title = re.sub(r'\s+', ' ', old_title).strip().strip("'\"\u201c\u201d\u2018\u2019").strip()

    new_title = (new_title or '').strip().strip("'\"\u201c\u201d\u2018\u2019").strip()

    try:
        print("RENAME_FASTPATH_PARSED", {'raw': query, 'old_title': old_title, 'new_title': new_title})
    except Exception:
        pass

    if not new_title:
        return jsonify({'error': 'Missing new title'}), 400

    appt = None
    if old_title:
        today_local = _date.today()
        todays = get_appointments_by_date(db, today_local)
        cand = [
            a for a in todays
            if _fuzzy_match(a.description or '', old_title, case_insensitive=True, min_ratio=0.60)
        ]
        if not cand:
            win = get_appointments_for_week(db, today_local - timedelta(days=2), today_local + timedelta(days=14))
            cand = [
                a for a in win
                if _fuzzy_match(a.description or '', old_title, case_insensitive=True, min_ratio=0.60)
            ]
        if len(cand) == 1:
            appt = cand[0]
        elif len(cand) > 1:
            cand.sort(key=lambda a: (a.date, a.start_time))
            appt = cand[0]

    if not appt and not old_title:
        todays = get_appointments_by_date(db, _date.today())
        if len(todays) == 1:
            appt = todays[0]

    if not appt:
        return jsonify({
            'error': 'No matching appointment found to rename.',
            'hint': 'Try: "Rename the appointment with the title gym to walk".',
        }), 404

    updated = update_appointment_title(db, appt.id, new_title)
    return jsonify({'updated': _serialize_appt(updated) if updated else None})


# ---------------------------------------------------------------------------
# 9) NL delete by title
# ---------------------------------------------------------------------------
def handle_nl_delete_by_title(db, query, q_lower, data):
    if not (re.search(r'\b(delete|cancel|remove)\b', q_lower) and ('appointment' in q_lower or 'meeting' in q_lower)):
        return None

    # Try to capture a title from common wordings and allow smart/straight quotes
    m = re.search(
        r'(?:with\s+the\s+title|with\s+title|titled|called|named)\s*["\u201c\u201d\'\u2018\u2019]?(.+?)["\u201c\u201d\'\u2018\u2019]?(?:\s*[?.!,]\s*|$)',
        query,
        flags=re.IGNORECASE
    )
    if not m:
        m = re.search(
            r'(?:delete|cancel|remove)\s+(?:the\s+)?(?:appointment|meeting)\s*["\'\u201c\u201d\u2018\u2019]([^"\'\u201c\u201d\u2018\u2019]+)["\'\u201c\u201d\u2018\u2019]',
            query,
            flags=re.IGNORECASE
        )
    title = (m.group(1).strip() if m else '').strip("'\"\u201c\u201d\u2018\u2019")

    # Optional explicit ISO date in the sentence
    sel_date = None
    mdate = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', q_lower)
    if mdate:
        sel_date = _to_date(mdate.group(1))

    appt = None
    if sel_date:
        try:
            matches = find_appointments(
                db,
                target_date=sel_date,
                term=title or None,
                case_insensitive=True,
                min_ratio=0.60,
            )
        except Exception:
            matches = []
        appt = matches[0] if matches else None

    if not appt and title:
        today_local = _date.today()
        todays = get_appointments_by_date(db, today_local)
        cand = [a for a in todays if _fuzzy_match(a.description or '', title, case_insensitive=True, min_ratio=0.60)]
        if len(cand) == 1:
            appt = cand[0]
        elif len(cand) == 0:
            win = get_appointments_for_week(db, today_local - timedelta(days=1), today_local + timedelta(days=14))
            cand = [a for a in win if _fuzzy_match(a.description or '', title, case_insensitive=True, min_ratio=0.60)]
            if len(cand) == 1:
                appt = cand[0]
            elif len(cand) > 1:
                cand.sort(key=lambda a: (a.date, a.start_time))
                out = [_serialize_appt(a) for a in cand[:10]]
                return jsonify({
                    'error': 'Ambiguous delete — multiple matches for that title.',
                    'candidates': out,
                    'hint': 'Specify the date/time or the appointment id to delete exactly one.'
                }), 409

    if appt:
        ok = delete_appointment_by_id(db, appt.id)
        return jsonify({'deleted': bool(ok), 'id': appt.id})

    return None  # fall through


# ---------------------------------------------------------------------------
# 10) NL create fallback
# ---------------------------------------------------------------------------
def handle_nl_create_fallback(db, query, q_lower, data):
    recurring_like = ('every' in q_lower) or bool(_parse_weekday_list(query))
    if not (re.search(r'\b(schedule|make|create|book)\b.*\b(appointment|meeting)\b', q_lower) and not recurring_like):
        return None

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
    title = _extract_title_from_text(query) or None

    if not title:
        m_title = re.search(
            r'(?:titled|with\s+title|called|named)\s*["\u201c\u201d\'\u2018\u2019]?(.+?)["\u201c\u201d\'\u2018\u2019]?(?:[.!?,]\s*|$)',
            query,
            flags=re.IGNORECASE
        )
        if m_title:
            title = m_title.group(1).strip()

    if not title:
        m_title2 = re.search(
            r'\btitle\s+([^\n]+?)(?:[.!?,]\s*|$)',
            query,
            flags=re.IGNORECASE
        )
        if m_title2:
            title = m_title2.group(1).strip()

    if title:
        title = title.strip().strip("'\"\u201c\u201d\u2018\u2019").strip()

    if not title:
        title = 'New appointment'

    try:
        print("CREATE_FALLBACK_PARSE_DEBUG:", {
            'query': query,
            'target_date_hint': ('tomorrow' if 'tomorrow' in q_lower else ('today' if 'today' in q_lower else None)),
            'time_match': m_time.group(1) if 'm_time' in locals() and m_time else None,
            'duration': duration,
            'title': title
        })
    except Exception:
        pass

    if not target or not start_t:
        return jsonify({
            'error': 'Missing date/time for create',
            'hint': 'Try: "Schedule an appointment today at 5:40 pm called Demo"'
        })

    end_t = _add_minutes(start_t, int(duration))
    created, conflicts = create_appointment_if_free(db, target, start_t, end_t, title)
    if created:
        return jsonify({'created': _serialize_appt(created)})

    day_appts = get_appointments_by_date(db, target)
    props = _find_all_free_slots(day_appts, int(duration), _time(0, 0, 0), _time(23, 59, 59), limit=5)
    return jsonify({
        'error': 'Time slot conflicts with existing appointments',
        'proposals': [
            {'date': target.isoformat(), 'start_time': s.isoformat(), 'end_time': e.isoformat(), 'title': title or 'Proposed slot'}
            for (s, e) in props
        ]
    })


# ---------------------------------------------------------------------------
# 11) NL recurring creation/preview (schedule every Thursday...)
# ---------------------------------------------------------------------------
def handle_nl_recurring(db, query, q_lower, data):
    if not (('every' in q_lower or bool(_parse_weekday_list(query))) and re.search(r'\b(schedule|make|create|book|preview)\b', q_lower)):
        return None

    try:
        preview_only = 'preview' in q_lower

        # title
        title = _extract_title_from_text(query) or 'New event'

        # time + duration
        m_time = re.search(r'\bat\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\b', q_lower)
        base_time = _to_time(m_time.group(1)) if m_time else _to_time('09:00')
        duration = _parse_duration_minutes_from_text(q_lower) or int(data.get('duration_minutes') or 60)
        if not base_time or duration <= 0:
            return jsonify({'error': 'Missing/invalid time or duration for recurring request'}), 400

        # weekday(s)
        by_weekdays = _parse_weekday_list(query)
        pattern = 'WEEKLY' if by_weekdays else 'DAILY'

        # bounds: date range, until, weeks, count
        start_date = _date.today()
        end_date = None
        count = 0
        weeks = 0

        # "between Oct 1 and Oct 31" OR "from Oct 1 till Oct 31"
        dr = _parse_month_day_range_text(query)
        if dr:
            start_date, end_date = dr

        # standalone "until Oct 15"
        if end_date is None:
            m_until = re.search(r'\b(?:until|till|through|thru)\s+([a-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?)', q_lower)
            if m_until:
                maybe_end = _parse_human_date(m_until.group(1))
                if maybe_end:
                    end_date = maybe_end

        # explicit "from Oct 11" without end
        if dr is None:
            m_from = re.search(r'\bfrom\s+([a-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?)', q_lower)
            if m_from:
                maybe_start = _parse_human_date(m_from.group(1))
                if maybe_start:
                    start_date = maybe_start

        # "for 3 weeks"
        m_weeks = re.search(r'\bfor\s+(\d{1,3})\s+weeks?\b', q_lower)
        if m_weeks:
            try:
                weeks = max(1, min(520, int(m_weeks.group(1))))
            except Exception:
                weeks = 0

        # "for 4 occurrences"
        m_occ = re.search(r'\bfor\s+(\d{1,3})\s+(?:occurrence|occurrences)\b', q_lower)
        if m_occ:
            try:
                count = max(1, min(100, int(m_occ.group(1))))
            except Exception:
                count = 0

        # interval like "every 2 weeks" / "every 2 days"
        interval = 1
        m_int = re.search(r'\bevery\s+(\d{1,3})\s+(weeks?|days?)\b', q_lower)
        if m_int:
            try:
                interval = max(1, min(365, int(m_int.group(1))))
            except Exception:
                interval = 1
            if 'week' in m_int.group(2) and not by_weekdays:
                pattern = 'WEEKLY'

        # If weeks present and no end_date, derive from start_date
        if end_date is None and weeks > 0:
            end_date = start_date + timedelta(days=7 * weeks)

        # Build preview occurrences first (shared logic)
        def _build_preview_list():
            items = []
            if end_date is None and count > 0:
                cur = start_date
                made = 0
                while made < count and len(items) < 200:
                    emit = False
                    if pattern == 'DAILY':
                        emit = True
                    elif pattern == 'WEEKDAYS':
                        emit = (cur.weekday() < 5)
                    elif pattern == 'WEEKLY':
                        wants = set(by_weekdays or [cur.weekday()])
                        emit = (cur.weekday() in wants)
                    else:
                        emit = True
                    if emit:
                        st = base_time
                        et = _add_minutes(base_time, duration)
                        items.append({'date': cur.isoformat(), 'start_time': st.isoformat(), 'end_time': et.isoformat(), 'title': title})
                        made += 1
                    cur += timedelta(days=1)
                return items
            rng_end = end_date or (start_date + timedelta(days=28))
            for d in _iter_dates_range(start_date, rng_end, pattern=pattern, weekday=None, by_weekdays=by_weekdays, interval=interval):
                st = base_time
                et = _add_minutes(base_time, duration)
                items.append({'date': d.isoformat(), 'start_time': st.isoformat(), 'end_time': et.isoformat(), 'title': title})
                if count and len(items) >= count:
                    break
            return items

        if preview_only:
            preview = _build_preview_list()
            return jsonify({'preview': preview})

        # Otherwise create leniently and surface skipped_conflicts
        preview_entries = _build_preview_list()
        entries = []
        for p in preview_entries:
            d = _to_date(p['date']); st = _to_time(p['start_time']); et = _to_time(p['end_time'])
            if d and st and et:
                entries.append({'date': d, 'start_time': st, 'end_time': et, 'description': title})

        created_rows = []
        skipped = []
        if entries:
            try:
                created_rows, skipped = bulk_create_appointments_lenient(db, entries)
            except TypeError:
                created_rows = bulk_create_appointments(db, entries, allow_overlap=False)
                existing_keys = {(a.date, a.start_time, a.end_time) for a in created_rows}
                for e in entries:
                    key = (e['date'], e['start_time'], e['end_time'])
                    if key in existing_keys:
                        continue
                    if find_conflicts_for_slot(db, e['date'], e['start_time'], e['end_time']):
                        skipped.append({'date': e['date'], 'start_time': e['start_time'], 'end_time': e['end_time'], 'title': title})

        payload = {
            'created_many': [_serialize_appt(a) for a in created_rows],
            'requested': (len(preview_entries) if preview_entries else (count or 0))
        }
        if skipped:
            payload['skipped_conflicts'] = [
                {
                    'date': (s['date'].isoformat() if hasattr(s.get('date'), 'isoformat') else str(s.get('date'))),
                    'start_time': (s['start_time'].isoformat() if hasattr(s.get('start_time'), 'isoformat') else str(s.get('start_time'))),
                    'end_time': (s['end_time'].isoformat() if hasattr(s.get('end_time'), 'isoformat') else str(s.get('end_time'))),
                    'title': s.get('title') or title
                } if isinstance(s, dict) else s
                for s in skipped]
        return jsonify(payload)
    except Exception as e:
        return jsonify({'error': 'Failed to handle recurring request', 'details': str(e)}), 400


# ---------------------------------------------------------------------------
# 12) Human spoken date like "29th August" / "Aug 29"
# ---------------------------------------------------------------------------
def handle_human_date(db, query, q_lower, data):
    human_d = _parse_human_date(query)
    if not human_d:
        return None
    if not any(k in q_lower for k in ['appointment', 'appointments', 'meeting', 'meetings', 'what', 'show']):
        return None
    appts = get_appointments_by_date(db, human_d)
    return jsonify({'appointments': [_serialize_appt(a) for a in appts]})


# ---------------------------------------------------------------------------
# 13) Show appointments on ISO date
# ---------------------------------------------------------------------------
def handle_show_on_date(db, query, q_lower, data):
    m_on = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', q_lower)
    if not m_on:
        return None
    if not ('show' in q_lower or 'appointments' in q_lower or 'meeting' in q_lower):
        return None
    target = _to_date(m_on.group(1))
    if not target:
        return None
    appts = get_appointments_by_date(db, target)
    return jsonify({'appointments': [_serialize_appt(a) for a in appts]})


# ---------------------------------------------------------------------------
# 14) Early recurring weekly fast-path (every/each without schedule/create verbs)
# ---------------------------------------------------------------------------
def _expand_weekly_dates(s_date, e_date, wdays):
    """Returns sorted unique dates in [s_date, e_date] on given weekdays."""
    dates = []
    try:
        if HAVE_RECURRENCE_HELPERS and expand_range_by_weekdays:
            dates = list(expand_range_by_weekdays(s_date, e_date, wdays))
    except Exception:
        dates = []
    if not dates:
        for d in _iter_dates_range(s_date, e_date, pattern='WEEKLY', by_weekdays=wdays):
            dates.append(d)
    return sorted({d for d in dates})


def _md_fallback(txt: str):
    """Ultra-tolerant month/day parser fallback."""
    m1 = re.search(r'([A-Za-z]{3,9})\s+(\d{1,2})', txt, flags=re.IGNORECASE)
    m2 = re.search(r'(\d{1,2})\s+([A-Za-z]{3,9})', txt, flags=re.IGNORECASE)
    if not (m1 or m2):
        return None
    if m2 and not m1:
        month_s, day_s = m2.group(2), m2.group(1)
    else:
        month_s, day_s = m1.group(1), m1.group(2)
    month_s = month_s.strip()[:3].lower()
    mm_map = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
              'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
    mm = mm_map.get(month_s)
    if not mm:
        return None
    try:
        dd = int(re.sub(r'(st|nd|rd|th)$', '', str(day_s), flags=re.IGNORECASE))
    except Exception:
        return None
    yy = _date.today().year
    try:
        return _date(yy, mm, dd)
    except Exception:
        return None


def _strip_ordinal_suffix(s: str) -> str:
    return re.sub(r'(\d{1,2})(?:st|nd|rd|th)', r'\1', s, flags=re.IGNORECASE)


def _parse_month_day_range_flexible(text: str):
    """
    Accepts (any order, optional year):
      - 'between Oct 1 and Oct 31'
      - 'from October 11th to October 25th'
      - 'between September 28, 2025 and Oct 15, 2025'
      - 'from 11th October to 25th October'
      - 'between 5 Nov and 19 Nov 2025'
    Returns (start_date, end_date) or None.
    """
    pat = r"\b(?:between|from)\s+((?:[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9})(?:,\s*\d{4})?)\s+(?:and|to)\s+((?:[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9})(?:,\s*\d{4})?)"
    m = re.search(pat, text, flags=re.IGNORECASE)
    if not m:
        return None
    a = re.sub(r'(\d{1,2})(st|nd|rd|th)', r'\1', m.group(1), flags=re.IGNORECASE)
    b = re.sub(r'(\d{1,2})(st|nd|rd|th)', r'\1', m.group(2), flags=re.IGNORECASE)
    sd = _parse_human_date(a) or _md_fallback(a)
    ed = _parse_human_date(b) or _md_fallback(b)
    if not (sd and ed):
        return None
    return (sd, ed)


def _parse_weekday_list_loose(text: str):
    txt = text.lower()
    m = {
        'monday': 0, 'mon': 0,
        'tuesday': 1, 'tue': 1, 'tues': 1,
        'wednesday': 2, 'wed': 2,
        'thursday': 3, 'thu': 3, 'thur': 3, 'thurs': 3,
        'friday': 4, 'fri': 4,
        'saturday': 5, 'sat': 5,
        'sunday': 6, 'sun': 6,
    }
    out = []
    for k, v in m.items():
        if re.search(r'\b' + re.escape(k) + r'\b', txt):
            out.append(v)
    return sorted(set(out))


def handle_recurring_weekly_fastpath(db, query, q_lower, data):
    if not (('every' in q_lower) or ('each' in q_lower)):
        return None

    print("RECURRING_FASTPATH_HIT")

    time_rng = _parse_time_range_text(query)
    dr_m = _parse_month_day_range_text(query) or _parse_month_day_range_flexible(query)
    title_m = re.search(r"(?:titled|with\s+title|title|called|named)\s*[^\"\u201c\u201d']?([^\"\u201c\u201d']+)[^\"\u201c\u201d']?", query, flags=re.IGNORECASE)

    # Also accept "8 pm" or "at 8 pm" + optional duration ("for 30 minutes")
    at_m = re.search(r"\b(?:at\s*|@)?\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm))\b", q_lower) or \
           re.search(r"\b([0-9]{1,2})(?::([0-9]{2}))?(am|pm)\b", q_lower)

    # Parse "for 4 weeks" / "up to 3 weeks" / "next 5 weeks"
    weeks_m = re.search(r"\b(?:for|up\s*to|upto|next)\s+(\d+)\s+weeks?\b", q_lower)
    weeks_count = int(weeks_m.group(1)) if weeks_m else 0
    if weeks_count < 0:
        weeks_count = 0

    # Parse "for 6 occurrences" / "for 6 times"
    occur_m = re.search(r"\bfor\s+(\d+)\s+(?:occurrence|occurrences|times)\b", q_lower)
    occur_count = int(occur_m.group(1)) if occur_m else 0
    if occur_count < 0:
        occur_count = 0

    # Support "until <date>"
    until_d = None
    m_until_iso = re.search(r'\buntil\s+(20\d{2}-\d{2}-\d{2})\b', q_lower)
    if m_until_iso:
        until_d = _to_date(m_until_iso.group(1))
    else:
        m_until_h = re.search(r'\buntil\s+([A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?)', query, flags=re.IGNORECASE)
        if m_until_h:
            try:
                until_d = _parse_human_date(_strip_ordinal_suffix(m_until_h.group(1)))
            except Exception:
                until_d = None

    title = (title_m.group(1).strip() if title_m else 'Untitled')
    title = title.strip().strip("'\"\u201c\u201d\u2018\u2019")

    # Start/end time
    st = et = None
    cross_midnight = False
    if time_rng:
        st, et = time_rng
        if st and et and et <= st:
            cross_midnight = True
            et = _time(23, 59, 59)
    else:
        if at_m:
            st_candidate = _to_time(at_m.group(1))
            dur = _parse_duration_minutes_from_text(q_lower) or 60
            if st_candidate:
                st = st_candidate
                et = _add_minutes(st_candidate, int(dur))
                if et <= st:
                    cross_midnight = True
                    et = _time(23, 59, 59)

    try:
        print("RECURRING_FASTPATH_PARSED:", {
            'weeks_count': weeks_count,
            'occur_count': occur_count,
            'until': (until_d.isoformat() if until_d else None),
            'range': ((dr_m[0].isoformat(), dr_m[1].isoformat()) if dr_m else None),
            'title': title
        })
    except Exception:
        pass

    if not (st and et):
        return None  # fall through to LLM

    wdays = _parse_weekday_list(query) or _parse_weekday_list_loose(query)
    if not wdays:
        return None  # need weekdays to proceed

    # Decide the date window to generate
    if dr_m:
        s_date, e_date = dr_m
    else:
        anchor = _date.today()

        def _next_match(from_date: _date) -> _date:
            d = from_date
            wanted = set(wdays)
            while d.weekday() not in wanted:
                d = d + timedelta(days=1)
            return d

        first = _next_match(anchor)

        if until_d:
            s_date = first
            e_date = until_d
        elif occur_count > 0:
            s_date = first
            e_date = first + timedelta(days=max(1, occur_count) * 7 + 6)
        elif weeks_count > 0:
            s_date = first
            e_date = first + timedelta(days=weeks_count * 7 - 1)
        else:
            s_date = first
            e_date = first + timedelta(days=28 - 1)

    # Protect against inverted ranges
    if e_date < s_date:
        s_date, e_date = e_date, s_date

    def _expand_weeklies(sd: _date, ed: _date, wd: list):
        try:
            if HAVE_RECURRENCE_HELPERS and expand_range_by_weekdays:
                return list(expand_range_by_weekdays(sd, ed, wd))
        except Exception:
            pass
        out = []
        for d in _iter_dates_range(sd, ed, pattern='WEEKLY', by_weekdays=wd):
            out.append(d)
        return sorted({d for d in out})

    entries = []
    skipped = []

    # Build candidate dates
    dates = []
    if occur_count > 0 and not dr_m:
        d = s_date
        taken = 0
        wanted = set(wdays)
        while d <= e_date and taken < occur_count:
            if d.weekday() in wanted:
                dates.append(d)
                taken += 1
            d = d + timedelta(days=1)
    else:
        dates = _expand_weeklies(s_date, e_date, wdays)

    # Check conflicts and build entries
    for d in dates:
        if find_conflicts_for_slot(db, d, st, et):
            skipped.append({
                'date': d.isoformat(),
                'start_time': st.isoformat(),
                'end_time': et.isoformat(),
                'title': title,
            })
            continue
        entries.append({'date': d, 'start_time': st, 'end_time': et, 'description': title})

    # Always compute a preview/proposals payload
    preview = [{
        'date': d.isoformat(),
        'start_time': st.isoformat(),
        'end_time': et.isoformat(),
        'title': title
    } for d in dates]

    if not entries:
        return jsonify({
            'preview': preview,
            'proposals': preview,
            'requested': len(preview),
            'mode': 'preview_recurring',
            'title': title,
            'skipped_conflicts': skipped,
            'message': f'Previewing {len(preview)} occurrence(s) for "{title}".'
        })

    if 'preview' in q_lower or data.get('preview') or not entries:
        return jsonify({
            'preview': preview,
            'proposals': preview,
            'requested': len(preview),
            'mode': 'preview_recurring',
            'title': title,
            'skipped_conflicts': skipped,
            'message': f'Previewing {len(preview)} occurrence(s) for "{title}".' + (' (End clamped to 23:59 for cross-midnight.)' if cross_midnight else '')
        })

    created = bulk_create_appointments(db, entries, allow_overlap=False) if entries else []
    payload_created = [_serialize_appt(a) for a in created]
    return jsonify({
        'created_many': payload_created,
        'requested': len(preview),
        'mode': 'fallback_recurring_early',
        'skipped_conflicts': skipped,
        'message': f'Created {len(payload_created)} of {len(preview)} requested occurrence(s) for "{title}".' + (' (End clamped to 23:59 for cross-midnight.)' if cross_midnight else ''),
        'proposals': [p for p in preview if p not in [{'date': a["date"], 'start_time': a["start_time"], 'end_time': a["end_time"], 'title': a["description"]} for a in payload_created]]
    })
