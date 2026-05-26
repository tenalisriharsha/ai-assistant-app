from datetime import date as _date, time as _time, datetime as _dt, timezone as _tz
from typing import Any, Dict, Optional

from crud import (
    create_reminder, create_reminder_for_appointment, list_reminders,
    update_reminder, delete_reminder, toggle_reminder,
    get_due_reminders, snooze_reminder, mark_reminder_delivered,
    get_appointment_by_id,
)
from utils.parsing import _to_date, _to_time
from utils.dates import _parse_date_range_param
from utils.serializers import _serialize_reminder


def handle_reminder_action(db, action: str, data: Dict[str, Any]) -> tuple:
    today = _date.today()

    if action in {'reminder_create', 'create_reminder'}:
        date_ = _to_date(data.get('date')) or today
        time_ = _to_time(data.get('time') or data.get('at') or '09:00')
        title = (data.get('title') or data.get('description') or 'Reminder').strip()
        lead = int(data.get('lead_minutes') or data.get('lead') or 0)
        channel = (data.get('channel') or 'inapp').strip()
        if not time_:
            return ({'error': 'Missing/invalid time'}, 400)
        r = create_reminder(
            db, date_=date_, time_=time_, title=title,
            description=title, lead_minutes=lead, channel=channel
        )
        return ({'reminder': _serialize_reminder(r, db)}, 200)

    if action in {'reminder_for_appointment', 'create_reminder_for_appt'}:
        appt_id = data.get('appointment_id') or data.get('id')
        lead = int(data.get('lead_minutes') or data.get('lead') or 15)
        channel = (data.get('channel') or 'inapp').strip()
        if not appt_id:
            return ({'error': 'Missing appointment id'}, 400)
        appt = get_appointment_by_id(db, int(appt_id))
        if not appt:
            return ({'error': 'Appointment not found'}, 404)
        r = create_reminder_for_appointment(
            db, appt, lead_minutes=lead,
            title=appt.description or 'Upcoming appointment', channel=channel
        )
        return ({'reminder': _serialize_reminder(r, db, appt=appt)}, 200)

    if action in {'reminder_list', 'list_reminders'}:
        dr = _parse_date_range_param(data.get('date_range'))
        start = _to_date(data.get('start_date')) if not dr else dr[0]
        end = _to_date(data.get('end_date')) if not dr else dr[1]
        active = data.get('active')
        if isinstance(active, str):
            active = active.lower() in ('1', 'true', 'yes', 'y', 'on')
        search = (data.get('search') or data.get('term') or '').strip() or None
        rs = list_reminders(db, start_date=start, end_date=end, active=active, search=search)
        return ({'reminders': [_serialize_reminder(r, db) for r in rs]}, 200)

    if action in {'reminder_update'}:
        rid = data.get('id') or data.get('reminder_id')
        if not rid:
            return ({'error': 'Missing reminder id'}, 400)
        r = update_reminder(
            db, int(rid),
            date_=_to_date(data.get('date')),
            time_=_to_time(data.get('time')),
            title=(data.get('title') or '').strip() or None,
            description=(data.get('description') or '').strip() or None,
            lead_minutes=(data.get('lead_minutes') or data.get('lead')),
            channel=(data.get('channel') or None),
            active=(data.get('active') if data.get('active') is not None else None),
        )
        if not r:
            return ({'error': 'Not found'}, 404)
        return ({'reminder': _serialize_reminder(r, db)}, 200)

    if action in {'reminder_toggle'}:
        rid = data.get('id') or data.get('reminder_id')
        if not rid:
            return ({'error': 'Missing reminder id'}, 400)
        r = toggle_reminder(db, int(rid), active=data.get('active'))
        if not r:
            return ({'error': 'Not found'}, 404)
        return ({'reminder': {'id': r.id, 'active': r.active}}, 200)

    if action in {'reminder_delete'}:
        rid = data.get('id') or data.get('reminder_id')
        if not rid:
            return ({'error': 'Missing reminder id'}, 400)
        ok = delete_reminder(db, int(rid))
        if ok:
            return ({'deleted': True, 'id': int(rid)}, 200)
        return ({'error': 'Not found'}, 404)

    if action in {'reminders_due'}:
        due = get_due_reminders(db, now=_dt.now(_tz.utc))
        return ({'due_reminders': [_serialize_reminder(r, db) for r in due]}, 200)

    if action in {'reminder_mark_delivered'}:
        rid = data.get('id') or data.get('reminder_id')
        if not rid:
            return ({'error': 'Missing reminder id'}, 400)
        r = mark_reminder_delivered(db, int(rid))
        if not r:
            return ({'error': 'Not found'}, 404)
        return ({'reminder': {'id': r.id, 'delivered': True}}, 200)

    if action in {'reminder_snooze'}:
        rid = data.get('id') or data.get('reminder_id')
        mins = int(data.get('minutes') or 10)
        if not rid:
            return ({'error': 'Missing reminder id'}, 400)
        r = snooze_reminder(db, int(rid), minutes=mins)
        if not r:
            return ({'error': 'Not found'}, 404)
        return ({'reminder': _serialize_reminder(r, db)}, 200)

    return ({'error': f'Unknown reminder action "{action}"'}, 400)
