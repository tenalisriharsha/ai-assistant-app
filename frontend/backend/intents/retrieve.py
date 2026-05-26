from datetime import date as _date, time as _time, datetime as _dt, timedelta
from typing import Any, Dict

from crud import (
    get_appointments_by_date, get_appointments_for_week,
    get_next_appointment, search_appointments_by_description,
    get_appointments_on_weekends, get_appointments_after_time,
    count_appointments_in_range, get_conflicting_appointments,
    get_appointments_between as crud_get_appointments_between,
)
from utils.parsing import _to_date, _to_time
from utils.dates import _parse_date_range_param
from utils.dates import _month_bounds, _dt_combine
from utils.slots import _compute_free_slots, _find_all_free_slots
from utils.serializers import _serialize_appt


def _J(db, appts_list):
    """Helper to serialize and return appointments."""
    return {'appointments': [_serialize_appt(a) for a in appts_list]}


def handle_retrieve_action(db, action: str, data: Dict[str, Any]) -> tuple:
    today = _date.today()

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
            return ({'proposals': proposals}, 200)
        return ({'free': _compute_free_slots(appts)}, 200)

    if action == 'today':
        appts = get_appointments_by_date(db, today)

    elif action == 'this_week':
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        appts = get_appointments_for_week(db, start, end)

    elif action == 'next_upcoming':
        appt = get_next_appointment(db, today)
        return ({'appointment': _serialize_appt(appt) if appt else None}, 200)

    elif action == 'search_description':
        term = (data.get('term') or '').strip()
        if not term:
            return ({'error': 'Missing search term'}, 400)
        appts = search_appointments_by_description(db, term)
        return ({'appointments': [_serialize_appt(a) for a in appts]}, 200)

    elif action == 'list_by_date':
        target = _to_date(data.get('date'))
        if not target:
            return ({'error': 'Missing or invalid date parameter'}, 400)
        appts = get_appointments_by_date(db, target)
        return ({'appointments': [_serialize_appt(a) for a in appts]}, 200)

    elif action == 'between_tomorrow':
        start_t = _to_time(data.get('start_time'))
        end_t = _to_time(data.get('end_time'))
        if not start_t or not end_t:
            return ({'error': 'Missing or invalid start_time/end_time'}, 400)
        tomorrow = today + timedelta(days=1)
        appts = crud_get_appointments_between(db, tomorrow, start_t, end_t)
        return ({'appointments': [_serialize_appt(a) for a in appts]}, 200)

    elif action == 'weekend_month':
        year = int(data.get('year', today.year))
        month = int(data.get('month', today.month))
        appts = get_appointments_on_weekends(db, year, month)
        return ({'appointments': [_serialize_appt(a) for a in appts]}, 200)

    elif action == 'after_time':
        threshold = _to_time(data.get('time') or '18:00:00')
        if not threshold:
            return ({'error': 'Invalid time format'}, 400)
        appts = get_appointments_after_time(db, today, threshold)
        return ({'appointments': [_serialize_appt(a) for a in appts]}, 200)

    elif action == 'count_this_month':
        start_month = today.replace(day=1)
        next_month = (start_month.replace(year=start_month.year+1, month=1, day=1)
                      if start_month.month == 12 else
                      start_month.replace(month=start_month.month+1, day=1))
        end_month = next_month - timedelta(days=1)
        cnt = count_appointments_in_range(db, start_month, end_month)
        return ({'count': cnt}, 200)

    elif action == 'conflicts':
        target = _to_date(data.get('date')) or today
        conflicts = get_conflicting_appointments(db, target)
        return ({'conflicts': [[_serialize_appt(a) for a in pair] for pair in conflicts]}, 200)

    else:
        return ({'error': f'Unknown retrieve action "{action}"'}, 400)

    serialized = [_serialize_appt(a) for a in appts]
    return ({'appointments': serialized}, 200)
