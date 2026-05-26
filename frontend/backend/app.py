# routes.py  — Scheduler API (refactored)
from flask import Flask, request, jsonify
from flask_cors import CORS
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import date as _date, time as _time, timedelta, datetime as _dt, timezone as _tz
from functools import wraps

from utils import (
    _to_date, _to_time, _as_delta, _add_minutes, _duration_minutes,
    _fuzzy_match, _match_opts,
    _iter_dates_range, _parse_date_range_param,
    _parse_month_name_token, _strip_ordinals, _parse_human_date,
    _extract_title_from_text, _parse_month_day_range_text,
    _parse_weekday_list, _parse_time_range_text,
    _parse_duration_minutes_from_text, _parse_lead_from_text,
    _month_bounds, _dt_combine, _local_tz, _normalize_tz, _tz_to_local_date_time,
    _compute_free_slots, _find_first_free_slot, _find_all_free_slots,
    _serialize_appt, _serialize_reminder, _resolve_reschedule_times,
    get_db,
)
from database import SessionLocal
from models import Appointment
from openai_handler import parse_query
from flows.create_appointment_flow import handle_create_appointment_flow
from crud import (
    get_appointment_by_id, get_appointments_by_date, get_appointments_for_week,
    get_appointments_between as crud_get_appointments_between,
    get_next_appointment, search_appointments_by_description,
    get_appointments_on_weekends, get_appointments_after_time,
    count_appointments_in_range, get_conflicting_appointments,
    create_appointment, create_appointment_if_free,
    bulk_create_appointments, bulk_create_appointments_lenient,
    create_appointment_lenient, find_conflicts_for_slot,
    find_appointments, update_appointment_time, update_appointment_title,
    reschedule_appointment, delete_appointment_by_id,
    delete_on_date, delete_by_search, delete_by_label,
    move_day_appointments,
    create_reminder, create_reminder_for_appointment, list_reminders,
    get_reminder_by_id, update_reminder, delete_reminder, toggle_reminder,
    get_due_reminders, snooze_reminder, mark_reminder_delivered,
)
from intents import handle_reminder_action, handle_retrieve_action, dispatch_nl, handle_llm_intent

# Optional recurrence helpers
try:
    from scheduler.recurrence import (
        expand_daily_until, expand_weekly_until,
        expand_range_by_weekdays, expand_monthly_byday_until,
    )
    HAVE_RECURRENCE_HELPERS = True
except Exception:
    HAVE_RECURRENCE_HELPERS = False

# Optional templates module
try:
    from scheduler.templates import generate_template_blocks
except Exception:
    generate_template_blocks = None

from schemas import Appointment as AppointmentSchema
from pydantic import ValidationError

app = Flask(__name__)
CORS(app)

# Global in-memory session states to support multi-step creation
CREATE_APPT_SESSIONS: Dict[str, dict] = {}

# ---------- decorators ----------
def with_db(f):
    """Decorator that injects a managed DB session as the first argument."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        with get_db() as db:
            return f(db, *args, **kwargs)
    return wrapper

@app.get('/health')
def health():
    return jsonify({'ok': True, 'service': 'scheduler', 'time': _dt.now().isoformat()})

# Tiny root route for manual pings
@app.get('/')
@app.get('/')
def root():
    return jsonify({'status': 'running'})

# JSON/error handler for bad JSON bodies
@app.errorhandler(400)
@app.errorhandler(400)
def handle_400(err):
    try:
        # Flask may raise BadRequest on invalid JSON; keep response consistent
        return jsonify({'error': 'Bad Request', 'details': str(err)}), 400
    except Exception:
        return jsonify({'error': 'Bad Request'}), 400


# ---------- export / import ----------
@app.get('/export')
@with_db
def export_all(db):
    """Export all appointments as JSON."""
    from crud import get_appointments_between
    from datetime import date
    appts = db.query(Appointment).order_by(Appointment.date, Appointment.start_time).all()
    return jsonify({
        'appointments': [_serialize_appt(a) for a in appts],
        'exported_at': _dt.now().isoformat(),
    })


@app.post('/import')
@with_db
def import_all(db):
    """Bulk import appointments from JSON."""
    from crud import create_appointment_if_free
    data = request.get_json() or {}
    appointments = data.get('appointments') or []
    created = 0
    errors = []
    for item in appointments:
        try:
            date_ = _to_date(item.get('date'))
            start = _to_time(item.get('start_time'))
            end = _to_time(item.get('end_time'))
            if not date_ or not start or not end:
                errors.append({'item': item, 'error': 'Missing date or time'})
                continue
            create_appointment_if_free(
                db, date_, start, end,
                description=item.get('description') or item.get('title'),
                title=item.get('title'),
                location=item.get('location'),
                notes=item.get('notes'),
                recurrence_rule=item.get('recurrence_rule'),
            )
            created += 1
        except Exception as e:
            errors.append({'item': item, 'error': str(e)})
    return jsonify({'created': created, 'errors': errors})


@app.post('/import_ics')
@with_db
def import_ics(db):
    """Import appointments from an uploaded .ics file."""
    from icalendar import Calendar
    from crud import create_appointment_if_free
    from datetime import date as dt_date, time as dt_time

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    if not file.filename or not file.filename.endswith('.ics'):
        return jsonify({'error': 'File must be .ics'}), 400

    try:
        cal = Calendar.from_ical(file.read())
    except Exception as e:
        return jsonify({'error': f'Invalid ICS file: {e}'}), 400

    created = 0
    errors = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        try:
            dtstart = component.get('dtstart').dt
            dtend = component.get('dtend').dt
            summary = str(component.get('summary', ''))
            location = str(component.get('location', ''))
            description = str(component.get('description', ''))

            # Handle datetime vs date
            if hasattr(dtstart, 'date'):
                event_date = dtstart.date()
                start_time = dtstart.time()
            else:
                event_date = dtstart
                start_time = dt_time(0, 0)

            if hasattr(dtend, 'date'):
                end_time = dtend.time()
            else:
                end_time = dt_time(23, 59)

            create_appointment_if_free(
                db, event_date, start_time, end_time,
                description=description or summary,
                title=summary,
                location=location,
            )
            created += 1
        except Exception as e:
            errors.append({'summary': str(component.get('summary', '')), 'error': str(e)})

    return jsonify({'created': created, 'errors': errors})

# ---------- route ----------
@app.route('/query', methods=['POST', 'OPTIONS'])
@with_db
def query_appointments(db):
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.json or {}
    raw_action = data.get('action') or data.get('op') or data.get('type')
    action = (raw_action.strip().lower() if isinstance(raw_action, str) else None)
    # FIX: Ignore "text" — this is NOT a structured action
    if action == "text":
        action = None
    # Debug: surface the incoming action and payload in logs
    if action:
        print("ACTION_DEBUG:", {"raw": raw_action, "normalized": action, "keys": list(data.keys())})

    # 1) Structured actions (backward compatible)
    if action:
        today = _date.today()

        # ---- Deleting (structured) ----
        if action in {"delete", "cancel", "remove", "delete_single"}:
            # NOTE: This version works with your original CRUD (no soft-delete dependency).
            # It prefers explicit IDs; otherwise resolves a single match by (date, time window, optional title).
            # If multiple candidates match, it returns 409 with a short candidate list (no accidental deletes).

            selector = data.get("selector") or {}
            ci_opt, mr_opt = _match_opts(selector, data)

            # 1) Explicit id at top level or nested in selector
            appt_id = (
                data.get("id")
                or data.get("appt_id")
                or data.get("appointment_id")
                or data.get("appointmentId")
                or (selector.get("id") if isinstance(selector, dict) else None)
                or (selector.get("appt_id") if isinstance(selector, dict) else None)
                or (selector.get("appointment_id") if isinstance(selector, dict) else None)
                or (selector.get("appointmentId") if isinstance(selector, dict) else None)
            )

            appt = None
            if appt_id is not None:
                try:
                    appt_id = int(appt_id)
                except Exception:
                    return jsonify({"error": "Invalid id"}), 400

                appt = get_appointment_by_id(db, appt_id)
                if not appt:
                    return jsonify({"error": "Not found", "id": appt_id}), 404
            else:
                # 2) Resolve by (date, optional start/end, optional title/description)
                sel_date = _to_date(data.get("date") or (selector.get("date") if isinstance(selector, dict) else None))
                sel_start = _to_time(data.get("start_time") or (selector.get("start_time") if isinstance(selector, dict) else None))
                sel_end   = _to_time(data.get("end_time") or (selector.get("end_time") if isinstance(selector, dict) else None))
                sel_title = (
                    data.get("title") or data.get("description") or
                    (selector.get("title") if isinstance(selector, dict) else None) or
                    (selector.get("description") if isinstance(selector, dict) else None)
                )
                sel_title = (sel_title or "").strip() or None

                matches = []
                if sel_date:
                    try:
                        matches = find_appointments(
                            db,
                            target_date=sel_date,
                            term=sel_title,
                            start_time_=sel_start,
                            end_time_=sel_end,
                            case_insensitive=True if ci_opt is None else bool(ci_opt),
                            min_ratio=mr_opt if mr_opt is not None else 0.60,
                        ) or []
                    except Exception:
                        matches = []
                else:
                    # No date given: if we have a title, search today, then widen to the next 7 days
                    if sel_title:
                        today_local = _date.today()
                        todays = get_appointments_by_date(db, today_local)
                        cand = [a for a in todays if _fuzzy_match(
                            a.description or "",
                            sel_title,
                            case_insensitive=True if ci_opt is None else bool(ci_opt),
                            min_ratio=mr_opt if mr_opt is not None else 0.60,
                        )]
                        if len(cand) == 1:
                            matches = cand
                        elif len(cand) == 0:
                            win = get_appointments_for_week(db, today_local, today_local + timedelta(days=7))
                            cand2 = [a for a in win if _fuzzy_match(
                                a.description or "",
                                sel_title,
                                case_insensitive=True if ci_opt is None else bool(ci_opt),
                                min_ratio=mr_opt if mr_opt is not None else 0.60,
                            )]
                            # Accept a unique match; otherwise return all to let UI disambiguate
                            matches = cand2

                if len(matches) == 0:
                    return jsonify({
                        "error": "No matching appointment found to delete.",
                        "hint": "Provide an id, or include date with start/end time (and optional title)."
                    }), 404

                if len(matches) > 1:
                    # Don't guess; surface candidates for the client to pick one by id
                    out = [
                        {
                            "id": a.id,
                            "date": a.date.isoformat(),
                            "start_time": a.start_time.isoformat(),
                            "end_time": a.end_time.isoformat(),
                            "title": (a.description or getattr(a, "title", "") or "")[:255],
                        }
                        for a in sorted(matches, key=lambda x: (x.date, x.start_time, x.id or 0))
                    ]
                    return jsonify({"error": "Ambiguous selector matched multiple appointments.", "candidates": out}), 409

                appt = matches[0]
                appt_id = int(appt.id)

            # 3) Perform the delete via your original CRUD
            try:
                ok = delete_appointment_by_id(db, appt_id)
            except Exception as e:
                return jsonify({"error": "Delete failed", "details": str(e)}), 500

            if ok:
                return jsonify({"deleted": True, "id": appt_id})
            return jsonify({"error": "Not found"}), 404

        # ---- Updating / Rescheduling (structured) ----
        if action in {'update', 'reschedule', 'move'}:
            selector = data.get('selector') or {}
            # Support UI payloads that send updates inside a 'fields' object
            fields = data.get('fields') or {}
            ci_opt, mr_opt = _match_opts(selector, data)
            appt = None

            # 1) Try id first (either top-level or inside selector)
            sel_id = selector.get('id') or data.get('id')
            if sel_id:
                try:
                    appt = get_appointment_by_id(db, int(sel_id))
                except Exception:
                    appt = None

            # 2) Otherwise, try to resolve by (date, time window, optional title)
            if not appt:
                sel_date = _to_date(selector.get('date') or data.get('date'))
                sel_start = _to_time(selector.get('start_time') or data.get('start_time'))
                sel_end = _to_time(selector.get('end_time') or data.get('end_time'))
                sel_title = (selector.get('title') or data.get('title') or data.get('description') or '').strip() or None
                # If UI sent the title inside fields, fold it in as a selector hint
                if not sel_title:
                    sel_title = (fields.get('title') or fields.get('description') or '').strip() or None

                matches = find_appointments(
                    db,
                    target_date=sel_date,
                    term=sel_title,
                    start_time_=sel_start,
                    end_time_=sel_end,
                    case_insensitive=True if ci_opt is None else bool(ci_opt),
                    min_ratio=mr_opt if mr_opt is not None else 0.60,
                ) if sel_date else []
                appt = matches[0] if matches else None

                # Fallback: exact-window scan on that date if provided
                if not appt and sel_date:
                    day_list = get_appointments_by_date(db, sel_date)
                    for a in day_list:
                        same_start = (sel_start is None) or (a.start_time == sel_start)
                        same_end = (sel_end is None) or (a.end_time == sel_end)
                        title_ok = (not sel_title) or _fuzzy_match(
                            (a.description or ''),
                            sel_title,
                            case_insensitive=True if ci_opt is None else bool(ci_opt),
                            min_ratio=mr_opt if mr_opt is not None else 0.60,
                        )
                        if same_start and same_end and title_ok:
                            appt = a
                            break

            # 3) If still not found and only a title is provided, search today then the next 7 days
            if not appt:
                sel_title2 = (selector.get('title') or data.get('title') or data.get('description') or '').strip() or None
                if not sel_title2:
                    sel_title2 = (fields.get('title') or fields.get('description') or '').strip() or None
                if sel_title2:
                    today_local = _date.today()
                    todays = get_appointments_by_date(db, today_local)
                    cand = [a for a in todays if sel_title2.lower() in (a.description or '').lower()]
                    if len(cand) == 1:
                        appt = cand[0]
                    elif len(cand) == 0:
                        win = get_appointments_for_week(db, today_local, today_local + timedelta(days=7))
                        cand2 = [a for a in win if sel_title2.lower() in (a.description or '').lower()]
                        if cand2:
                            cand2.sort(key=lambda a: (a.date, a.start_time))
                            appt = cand2[0]

            if not appt:
                return jsonify({'error': 'No matching appointment found to reschedule.'}), 404

            # If caller is only changing the title/description (no date/time provided), treat as rename
            new_title = (fields.get('title') or fields.get('description') or '').strip()
            provided_time_change = any([
                data.get('new_date'), data.get('date'), fields.get('date'),
                data.get('new_start_time'), data.get('new_start'), data.get('time'),
                fields.get('start_time'), fields.get('start'),
                data.get('new_end_time'), data.get('new_end'),
                fields.get('end_time'), fields.get('end')
            ])
            if new_title and not provided_time_change:
                updated = update_appointment_title(db, appt.id, new_title)
                return jsonify({'updated': _serialize_appt(updated) if updated else None})

            # Compute target window using unified helper (preserve duration safely)
            req_new_date  = _to_date(data.get('new_date') or data.get('date') or fields.get('date'))
            req_new_start = _to_time(
                data.get('new_start_time') or data.get('new_start') or data.get('time') or
                fields.get('start_time')   or fields.get('start')
            )
            req_new_end   = _to_time(
                data.get('new_end_time') or data.get('new_end') or
                fields.get('end_time')   or fields.get('end')
            )
            target_date, target_start, target_end = _resolve_reschedule_times(appt, req_new_date, req_new_start, req_new_end)

            try:
                updated = update_appointment_time(
                    db,
                    appt_id=appt.id,
                    date_=target_date,
                    start_time_=target_start,
                    end_time_=target_end,
                    allow_overlap=False,
                )
                if not updated:
                    return jsonify({'error': 'Update failed'}), 400
                return jsonify({'updated': _serialize_appt(updated)})
            except ValueError as e:
                # Conflict: return proposals so UI can surface options
                base_dur = _duration_minutes(appt.start_time, appt.end_time)
                dur_min = _duration_minutes(target_start, target_end) if (target_start and target_end) else (base_dur if base_dur > 0 else 60)
                day_appts = get_appointments_by_date(db, target_date)
                props = _find_all_free_slots(day_appts, dur_min, _time(0,0,0), _time(23,59,59), limit=5)
                return jsonify({
                    'error': 'Updated time slot conflicts with existing appointments',
                    'details': str(e),
                    'proposals': [
                        {'date': target_date.isoformat(), 'start_time': s.isoformat(), 'end_time': e.isoformat()}
                        for (s, e) in props
                    ]
                }), 409
            except Exception as e:
                return jsonify({'error': 'Update failed', 'details': str(e)}), 500

        # ---- Scheduling / Creating (structured) ----
        if action == 'create':
            target = _to_date(data.get('date'))
            start_t = _to_time(data.get('start_time') or data.get('time'))
            end_t = _to_time(data.get('end_time'))
            duration = data.get('duration_minutes') or data.get('duration')
            title = (data.get('title') or data.get('description') or "").strip()

            if not target or not start_t or (not end_t and not duration):
                return jsonify({'error': 'Missing date/start_time and end_time or duration_minutes'}), 400
            if not end_t and duration:
                try:
                    end_t = _add_minutes(start_t, int(duration))
                except Exception:
                    pass

            dur_min = int(duration) if duration else _duration_minutes(start_t, end_t)
            if not end_t or dur_min <= 0:
                return jsonify({'error': 'Invalid time window: ensure end_time is after start_time or provide a positive duration_minutes'}), 400

            created, conflicts = create_appointment_if_free(db, target, start_t, end_t, title)
            if created:
                return jsonify({'created': _serialize_appt(created)})

            day_appts = get_appointments_by_date(db, target)
            slot = _find_first_free_slot(day_appts, dur_min, _time(0,0), _time(23,59,59))
            props = _find_all_free_slots(day_appts, dur_min, _time(0,0), _time(23,59,59), limit=5)
            return jsonify({
                'error': 'Time slot conflicts with existing appointments',
                'conflicts': [_serialize_appt(c) for c in conflicts],
                'suggested_slot': {'start': slot[0].isoformat(), 'end': slot[1].isoformat()} if slot else None,
                'proposals': [
                    {'date': target.isoformat(),
                     'start_time': s.isoformat(),
                     'end_time': e.isoformat(),
                     'title': title or 'Proposed slot'}
                    for (s, e) in props
                ]
            }), 409

        if action == 'create_constraint':
            target = _to_date(data.get('date')) or today
            duration = int(data.get('duration_minutes') or 0)
            w_start = _to_time(data.get('window_start') or '00:00:00') or _time(0,0,0)
            w_end = _to_time(data.get('window_end') or '23:59:59') or _time(23,59,59)
            if _as_delta(w_start, w_end).total_seconds() <= 0:
                return jsonify({'error': 'window_start must be before window_end'}), 400
            title = (data.get('title') or data.get('description') or '').strip()

            if duration <= 0:
                return jsonify({'error': 'duration_minutes must be > 0'}), 400

            day_appts = get_appointments_by_date(db, target)
            slot = _find_first_free_slot(day_appts, duration, w_start, w_end)
            if not slot:
                return jsonify({'error': 'No free slot found in the requested window'}), 409

            start_t, end_t = slot
            created = create_appointment(db, target, start_t, end_t, title, allow_overlap=False)
            return jsonify({'created': _serialize_appt(created)})

        if action == 'create_recurring_simple':
            title = (data.get('title') or data.get('description') or '').strip()
            start_date = _to_date(data.get('start_date')) or today
            end_date = _to_date(data.get('end_date')) if data.get('end_date') else None
            count = int(data.get('count') or 0)
            count = max(1, min(count, 100))
            pattern = (data.get('pattern') or 'DAILY').upper()
            base_time = _to_time(data.get('time') or '09:00')
            duration = int(data.get('duration_minutes') or 30)
            interval = int(data.get('interval') or 1)
            by_weekdays = data.get('by_weekdays')
            wday = data.get('weekday')
            if duration <= 0:
                return jsonify({'error': 'duration_minutes must be > 0'}), 400

            if not title or not base_time:
                return jsonify({'error': 'Missing title/time or invalid duration'}), 400

            entries: List[dict] = []
            if end_date:
                for d in _iter_dates_range(
                    start_date, end_date,
                    pattern=pattern,
                    weekday=wday,
                    by_weekdays=by_weekdays,
                    interval=interval,
                ):
                    start_t = base_time
                    end_t = _add_minutes(base_time, duration)
                    if not find_conflicts_for_slot(db, d, start_t, end_t):
                        entries.append({
                            'date': d,
                            'start_time': start_t,
                            'end_time': end_t,
                            'description': title,
                        })
            else:
                cur = start_date
                made = 0
                while made < count:
                    if pattern == 'DAILY':
                        pass
                    elif pattern == 'WEEKDAYS':
                        if cur.weekday() >= 5:
                            cur += timedelta(days=1)
                            continue
                    elif pattern == 'WEEKLY':
                        want = wday
                        if want is not None and int(want) != cur.weekday():
                            cur += timedelta(days=1)
                            continue
                    else:
                        break

                    start_t = base_time
                    end_t = _add_minutes(base_time, duration)
                    if not find_conflicts_for_slot(db, cur, start_t, end_t):
                        entries.append({
                            'date': cur,
                            'start_time': start_t,
                            'end_time': end_t,
                            'description': title,
                        })
                        made += 1
                    cur += timedelta(days=1)

            created = []
            skipped = []
            if entries:
                try:
                    # Preferred path: use lenient helper which returns (created, skipped_conflicts)
                    created, skipped = bulk_create_appointments_lenient(db, entries)
                except TypeError:
                    # Backward-compat path: older helper may return only the created list
                    created = bulk_create_appointments(db, entries, allow_overlap=False)
                    # Synthesize "skipped_conflicts" by checking which requested entries still collide
                    existing_keys = {(a.date, a.start_time, a.end_time) for a in created}
                    for e in entries:
                        key = (e['date'], e['start_time'], e['end_time'])
                        if key in existing_keys:
                            continue
                        if find_conflicts_for_slot(db, e['date'], e['start_time'], e['end_time']):
                            skipped.append({
                                'date': e['date'],
                                'start_time': e['start_time'],
                                'end_time': e['end_time'],
                                'title': e.get('description') or e.get('title') or 'Conflict'
                            })
                except Exception as _e:
                    # Absolute fallback: try to create what we can, ignore failures
                    for e in entries:
                        try:
                            a = create_appointment(db, e['date'], e['start_time'], e['end_time'], e.get('description') or e.get('title') or '')
                            created.append(a)
                        except Exception:
                            skipped.append({
                                'date': e['date'],
                                'start_time': e['start_time'],
                                'end_time': e['end_time'],
                                'title': e.get('description') or e.get('title') or 'Conflict'
                            })
            payload = {
                'created_many': [_serialize_appt(a) for a in created],
                'requested': count
            }
            if skipped:
                # Normalize skipped entries to plain JSON-friendly dicts
                payload['skipped_conflicts'] = [
                    {
                        'date': (s['date'].isoformat() if hasattr(s.get('date'), 'isoformat') else str(s.get('date'))),
                        'start_time': (s['start_time'].isoformat() if hasattr(s.get('start_time'), 'isoformat') else str(s.get('start_time'))),
                        'end_time': (s['end_time'].isoformat() if hasattr(s.get('end_time'), 'isoformat') else str(s.get('end_time'))),
                        'title': s.get('title') or 'Conflict'
                    } if isinstance(s, dict) else s
                    for s in skipped
                ]
            return jsonify(payload)

        if action == 'create_recurring_preview':
            """
            Build a preview list of recurring occurrences without writing to the DB.

            Accepted fields (same as create_recurring_simple):
              - title / description
              - start_date (YYYY-MM-DD), end_date (YYYY-MM-DD) or weeks / count / until
              - pattern: DAILY | WEEKLY | WEEKDAYS  (default WEEKLY if by_weekdays/weekday provided)
              - by_weekdays: list[int]  (0=Mon..6=Sun)
              - weekday: int (0=Mon..6=Sun)  (shorthand)
              - time: "7 PM" / "19:00"
              - duration_minutes: int
              - interval: int (default 1)
            """
            today = _date.today()
            title = (data.get('title') or data.get('description') or '').strip() or 'Untitled'
            start_date = _to_date(data.get('start_date')) or today
            end_date = _to_date(data.get('end_date'))
            pattern = (data.get('pattern') or '').upper().strip()
            by_weekdays = data.get('by_weekdays')
            weekday_opt = data.get('weekday')
            interval = int(data.get('interval') or 1)

            # Allow alternative bounding controls
            weeks = int(data.get('weeks') or 0)
            count = int(data.get('count') or 0)
            until = _to_date(data.get('until')) if data.get('until') else None

            base_time = _to_time(data.get('time') or '09:00')
            duration = int(data.get('duration_minutes') or 60)
            if not base_time or duration <= 0:
                return jsonify({'error': 'Missing/invalid time or duration_minutes'}), 400

            # Derive end_date if not provided
            if not end_date:
                if until:
                    end_date = until
                elif weeks > 0:
                    end_date = start_date + timedelta(days=7 * weeks)
                elif count > 0:
                    # will generate by count below without end_date
                    pass
                else:
                    # sensible default preview horizon = 4 weeks
                    end_date = start_date + timedelta(days=28)

            # Determine pattern default
            if not pattern:
                pattern = 'WEEKLY' if (by_weekdays or (weekday_opt is not None)) else 'DAILY'

            # Build preview occurrences (no DB writes)
            preview = []
            if end_date:
                for d in _iter_dates_range(
                    start_date, end_date,
                    pattern=pattern,
                    weekday=weekday_opt,
                    by_weekdays=by_weekdays,
                    interval=interval
                ):
                    st = base_time
                    et = _add_minutes(base_time, duration)
                    preview.append({
                        'date': d.isoformat(),
                        'start_time': st.isoformat(),
                        'end_time': et.isoformat(),
                        'title': title
                    })
            else:
                # Count-limited preview
                cur = start_date
                made = 0
                while made < max(1, min(count, 100)):
                    emit = False
                    if pattern == 'DAILY':
                        emit = True
                    elif pattern == 'WEEKDAYS':
                        emit = (cur.weekday() < 5)
                    elif pattern == 'WEEKLY':
                        want = set(by_weekdays or ([] if weekday_opt is None else [int(weekday_opt)]))
                        if not want:
                            want = {cur.weekday()}
                        emit = (cur.weekday() in want)
                    else:
                        emit = True

                    if emit:
                        st = base_time
                        et = _add_minutes(base_time, duration)
                        preview.append({
                            'date': cur.isoformat(),
                            'start_time': st.isoformat(),
                            'end_time': et.isoformat(),
                            'title': title
                        })
                        made += 1
                    cur += timedelta(days=1)

            return jsonify({'preview': preview})

        if action == 'create_from_template':
            if generate_template_blocks is None:
                return jsonify({'error': 'templates module not available'}), 400

            template_key = (data.get('template') or '').upper()
            anchor = _to_date(data.get('anchor_date')) or today
            options = data.get('options') or {}

            blocks = generate_template_blocks(template_key, anchor, options)
            if not blocks:
                return jsonify({'error': 'unknown or empty template'}), 400

            entries = []
            skipped = []
            for b in blocks:
                d = _to_date(b.get('date')) or anchor
                st = _to_time(b.get('start_time'))
                et = _to_time(b.get('end_time'))
                title = (b.get('title') or b.get('description') or '').strip()
                if not d or not st or not et:
                    continue
                if find_conflicts_for_slot(db, d, st, et):
                    skipped.append(b)
                    continue
                entries.append({'date': d, 'start_time': st, 'end_time': et, 'description': title})

            created = bulk_create_appointments(db, entries, allow_overlap=False) if entries else []
            return jsonify({
                'created_many': [_serialize_appt(a) for a in created],
                'skipped_conflicts': skipped
            })

        # ---- Reminders (structured) ----
        if action in {'reminder_create', 'create_reminder'}:
            date_ = _to_date(data.get('date')) or today
            time_ = _to_time(data.get('time') or data.get('at') or '09:00')
            title = (data.get('title') or data.get('description') or 'Reminder').strip()
            lead = int(data.get('lead_minutes') or data.get('lead') or 0)
            channel = (data.get('channel') or 'inapp').strip()
            if not time_:
                return jsonify({'error': 'Missing/invalid time'}), 400
            r = create_reminder(
                db,
                date_=date_,
                time_=time_,
                title=title,
                description=title,
                lead_minutes=lead,
                channel=channel
            )
            payload = _serialize_reminder(r, db)
            return jsonify({'reminder': payload})

        if action in {'reminder_for_appointment', 'create_reminder_for_appt'}:
            appt_id = data.get('appointment_id') or data.get('id')
            lead = int(data.get('lead_minutes') or data.get('lead') or 15)
            channel = (data.get('channel') or 'inapp').strip()
            if not appt_id:
                return jsonify({'error': 'Missing appointment id'}), 400
            appt = get_appointment_by_id(db, int(appt_id))
            if not appt:
                return jsonify({'error': 'Appointment not found'}), 404
            r = create_reminder_for_appointment(
                db,
                appt,
                lead_minutes=lead,
                title=appt.description or 'Upcoming appointment',
                channel=channel
            )
            payload = _serialize_reminder(r, db, appt=appt)
            return jsonify({'reminder': payload})

        if action in {'reminder_list', 'list_reminders'}:
            dr = _parse_date_range_param(data.get('date_range'))
            start = _to_date(data.get('start_date')) if not dr else dr[0]
            end   = _to_date(data.get('end_date'))   if not dr else dr[1]
            active = data.get('active')
            if isinstance(active, str):
                active = active.lower() in ('1', 'true', 'yes', 'y', 'on')
            search = (data.get('search') or data.get('term') or '').strip() or None
            rs = list_reminders(db, start_date=start, end_date=end, active=active, search=search)
            payload = [_serialize_reminder(r, db) for r in rs]
            return jsonify({'reminders': payload})

        if action in {'reminder_update'}:
            rid = data.get('id') or data.get('reminder_id')
            if not rid:
                return jsonify({'error': 'Missing reminder id'}), 400
            r = update_reminder(
                db,
                int(rid),
                date_=_to_date(data.get('date')),
                time_=_to_time(data.get('time')),
                title=(data.get('title') or '').strip() or None,
                description=(data.get('description') or '').strip() or None,
                lead_minutes=(data.get('lead_minutes') or data.get('lead')),
                channel=(data.get('channel') or None),
                active=(data.get('active') if data.get('active') is not None else None),
            )
            if not r:
                return jsonify({'error': 'Not found'}), 404
            payload = _serialize_reminder(r, db)
            return jsonify({'reminder': payload})

        if action in {'reminder_toggle'}:
            rid = data.get('id') or data.get('reminder_id')
            if not rid:
                return jsonify({'error': 'Missing reminder id'}), 400
            r = toggle_reminder(db, int(rid), active=data.get('active'))
            if not r:
                return jsonify({'error': 'Not found'}), 404
            return jsonify({'reminder': {'id': r.id, 'active': r.active}})

        if action in {'reminder_delete'}:
            rid = data.get('id') or data.get('reminder_id')
            if not rid:
                return jsonify({'error': 'Missing reminder id'}), 400
            ok = delete_reminder(db, int(rid))
            if ok:
                return jsonify({'deleted': True, 'id': int(rid)})
            return jsonify({'error': 'Not found'}), 404

        if action in {'reminders_due'}:
            # UI can poll this every ~60s to show in-app toasts
            due = get_due_reminders(db, now=_dt.now(_tz.utc))
            payload = [_serialize_reminder(r, db) for r in due]
            return jsonify({'due_reminders': payload})

        if action in {'reminder_mark_delivered'}:
            rid = data.get('id') or data.get('reminder_id')
            if not rid:
                return jsonify({'error': 'Missing reminder id'}), 400
            r = mark_reminder_delivered(db, int(rid))
            if not r:
                return jsonify({'error': 'Not found'}), 404
            return jsonify({'reminder': {'id': r.id, 'delivered': True}})

        if action in {'reminder_snooze'}:
            rid = data.get('id') or data.get('reminder_id')
            mins = int(data.get('minutes') or 10)
            if not rid:
                return jsonify({'error': 'Missing reminder id'}), 400
            r = snooze_reminder(db, int(rid), minutes=mins)
            if not r:
                return jsonify({'error': 'Not found'}), 404
            payload = _serialize_reminder(r, db)
            return jsonify({'reminder': payload})

        # ---- Retrieval/analytics actions ----
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
                return jsonify({'proposals': proposals})
            return jsonify({'free': _compute_free_slots(appts)})

        if action == 'today':
            appts = get_appointments_by_date(db, today)

        elif action == 'this_week':
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            appts = get_appointments_for_week(db, start, end)

        elif action == 'next_upcoming':
            appt = get_next_appointment(db, today)
            return jsonify({'appointment': _serialize_appt(appt) if appt else None})

        elif action == 'search_description':
            term = (data.get('term') or '').strip()
            if not term:
                return jsonify({'error': 'Missing search term'}), 400
            appts = search_appointments_by_description(db, term)
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'list_by_date':
            target = _to_date(data.get('date'))
            if not target:
                return jsonify({'error': 'Missing or invalid date parameter'}), 400
            appts = get_appointments_by_date(db, target)
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'between_tomorrow':
            start_t = _to_time(data.get('start_time'))
            end_t = _to_time(data.get('end_time'))
            if not start_t or not end_t:
                return jsonify({'error': 'Missing or invalid start_time/end_time'}), 400
            tomorrow = today + timedelta(days=1)
            appts = crud_get_appointments_between(db, tomorrow, start_t, end_t)
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'weekend_month':
            year = int(data.get('year', today.year))
            month = int(data.get('month', today.month))
            appts = get_appointments_on_weekends(db, year, month)
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'after_time':
            threshold = _to_time(data.get('time') or '18:00:00')
            if not threshold:
                return jsonify({'error': 'Invalid time format'}), 400
            appts = get_appointments_after_time(db, today, threshold)
            return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

        elif action == 'count_this_month':
            start_month = today.replace(day=1)
            next_month = (start_month.replace(year=start_month.year+1, month=1, day=1)
                          if start_month.month == 12 else
                          start_month.replace(month=start_month.month+1, day=1))
            end_month = next_month - timedelta(days=1)
            cnt = count_appointments_in_range(db, start_month, end_month)
            return jsonify({'count': cnt})

        elif action == 'conflicts':
            target = _to_date(data.get('date')) or today
            conflicts = get_conflicting_appointments(db, target)
            return jsonify({'conflicts': [
                [_serialize_appt(a) for a in pair] for pair in conflicts
            ]})

        else:
            return jsonify({'error': f'Unknown action "{action}"'}), 400

        serialized = [_serialize_appt(a) for a in appts]
        return jsonify({'appointments': serialized})

    # 2) Natural language + LLM router
    data = request.get_json() or {}
    nl_query = (data.get("query") or "").strip()
    try:
        # ---------------------------------------------------------
        # 0. Conversational CREATE-APPOINTMENT FLOW (early intercept)
        # ---------------------------------------------------------
        session_key = request.remote_addr or "default"

        create_result = handle_create_appointment_flow(
            db=db,
            raw_query=nl_query,
            state_bucket=CREATE_APPT_SESSIONS,
            session_key=session_key,
        )

        if create_result is not None:
            return jsonify({
                "status": create_result.get("status"),
                "message": create_result.get("message"),
                "appointment": create_result.get("appointment"),
                "flow": "create_appointment"
            }), 200
    except Exception:
        pass

    query = nl_query
    try:
        print("NL_QUERY:", query)
    except Exception:
        pass
    if not query:
        return jsonify({'error': 'No query provided'}), 400

    q_lower = query.lower()

    # --- NL fast-path handlers (LLM-independent) ---
    nl_resp = dispatch_nl(db, query, q_lower, data)
    if nl_resp is not None:
        return nl_resp

    # --- LLM router ---
    try:
        llm = parse_query(query)
    except Exception as e:
        print("PARSE_ERROR:", e)
        llm = None

    llm_resp = handle_llm_intent(db, query, q_lower, data, llm)
    if llm_resp is not None:
        return llm_resp

    # --- legacy tuple path ---
    date_obj, start_time, end_time = llm if isinstance(llm, tuple) and len(llm) == 3 else (None, None, None)
    if date_obj:
        if start_time and end_time:
            appts = crud_get_appointments_between(db, date_obj, start_time, end_time)
        else:
            appts = get_appointments_by_date(db, date_obj)
        return jsonify({'appointments': [_serialize_appt(a) for a in appts]})

    # Final fallback — no hard error code; include hint for the UI
    return jsonify({
        'error': 'Unable to parse query',
        'hint': 'Examples: "What appointments do I have on 28 Aug", "Schedule an appointment today at 5:40 pm called Demo".',
        'raw_query': query
    }), 400



if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', '5001'))
    app.run(debug=True, port=port)
