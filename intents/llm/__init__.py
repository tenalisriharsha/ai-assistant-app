"""LLM intent dispatcher — handles all structured intents from parse_query()."""

from typing import Any, Dict, List, Optional
from datetime import date as _date, time as _time, timedelta, datetime as _dt
from flask import jsonify, Response

from utils import (
    _to_date, _to_time, _add_minutes, _duration_minutes,
    _month_bounds, _dt_combine, _normalize_tz, _tz_to_local_date_time,
    _parse_date_range_param, _parse_duration_minutes_from_text,
    _parse_time_range_text,
    _serialize_appt,
    _fuzzy_match, _match_opts, _resolve_reschedule_times,
    _find_all_free_slots, _compute_free_slots,
)
from crud import (
    get_appointment_by_id, get_appointments_by_date, get_appointments_for_week,
    get_appointments_between as crud_get_appointments_between,
    get_next_appointment, search_appointments_by_description,
    get_appointments_on_weekends, get_appointments_after_time,
    count_appointments_in_range, get_conflicting_appointments,
    create_appointment_if_free, bulk_create_appointments,
    find_appointments, find_conflicts_for_slot,
    update_appointment_time, update_appointment_title,
    delete_appointment_by_id,
    delete_on_date, delete_by_search, delete_by_label,
    move_day_appointments,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _J(appts_list):
    return jsonify({'appointments': [_serialize_appt(a) for a in appts_list]})


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------
def handle_llm_intent(db, query: str, q_lower: str, data: dict, llm_result) -> Optional[Response]:
    """Dispatch an LLM-parsed intent. Returns Response if handled, None otherwise."""
    if not (isinstance(llm_result, dict) and 'intent' in llm_result):
        return None

    intent = (llm_result.get('intent') or '').upper()
    params: Dict[str, Any] = llm_result.get('params') or {}

    try:
        print("LLM_DEBUG:", {'intent': intent, 'params': params})
    except Exception:
        pass

    # Heuristic: answer free-time requests directly (with proposals if asked)
    if (
        'free' in q_lower or 'free time' in q_lower or 'availability' in q_lower or 'available' in q_lower or
        'open slot' in q_lower or 'open slots' in q_lower or 'free slot' in q_lower or 'free slots' in q_lower or 'avail' in q_lower
    ):
        if intent in {'RETRIEVE_TODAY', 'TODAY'}:
            target = _date.today()
        elif intent in {'RETRIEVE_TOMORROW', 'TOMORROW'}:
            target = _date.today() + timedelta(days=1)
        elif intent in {'RETRIEVE_DATE', 'ON_DATE'}:
            target = _to_date(params.get('date')) or _date.today()
        else:
            target = _to_date(params.get('date')) or _date.today()
        appts = get_appointments_by_date(db, target)
        want_proposals = ('propos' in q_lower) or ('option' in q_lower) or ('slot' in q_lower)
        dur_req = params.get('duration_minutes') or params.get('duration') or _parse_duration_minutes_from_text(q_lower) or 0
        rng = _parse_time_range_text(q_lower)
        w_start = _to_time(params.get('window_start') or params.get('start_time')) or (rng[0] if rng else _time(0, 0, 0))
        w_end = _to_time(params.get('window_end') or params.get('end_time')) or (rng[1] if rng else _time(23, 59, 59))
        if int(dur_req) > 0 and want_proposals:
            props = _find_all_free_slots(appts, int(dur_req), w_start, w_end, limit=5)
            proposals = [
                {
                    'date': target.isoformat(),
                    'start_time': s.isoformat(),
                    'end_time': e.isoformat(),
                    'title': (params.get('title') or params.get('description') or 'Proposed slot')
                }
                for (s, e) in props
            ]
            return jsonify({'proposals': proposals})
        free = _compute_free_slots(appts)
        return jsonify({'free': free})

    # ----- Creating intents -----
    if intent in {'CREATE_SINGLE', 'CREATE', 'BOOK'}:
        target = _to_date(params.get('date'))
        start_t = _to_time(params.get('start_time') or params.get('time'))
        end_t = _to_time(params.get('end_time'))
        duration = params.get('duration_minutes') or params.get('duration')
        title = (params.get('title') or params.get('description') or '').strip()

        # If the user's text sounds like a *move/reschedule*, try to UPDATE instead of creating
        move_like = any(k in q_lower for k in ['move', 'reschedule', 'postpone', 'bring forward', 'shift', 'push back', 'pushback'])
        if move_like and title and target and start_t:
            try:
                end_for_update = end_t
                if not end_for_update:
                    try:
                        dur_for_update = int(duration) if duration else 0
                    except Exception:
                        dur_for_update = 0
                    if dur_for_update <= 0 and start_t:
                        dur_for_update = 60
                    end_for_update = _add_minutes(start_t, int(dur_for_update))

                today_local = _date.today()
                todays = get_appointments_by_date(db, today_local)
                cand = [a for a in todays if title.lower() in (a.description or '').lower()]

                chosen = None
                if len(cand) == 1:
                    chosen = cand[0]
                elif len(cand) == 0:
                    win = get_appointments_for_week(db, today_local, today_local + timedelta(days=7))
                    cand2 = [a for a in win if title.lower() in (a.description or '').lower()]
                    if cand2:
                        cand2.sort(key=lambda a: (a.date, a.start_time))
                        chosen = cand2[0]

                if chosen:
                    updated = update_appointment_time(
                        db,
                        appt_id=chosen.id,
                        date_=target,
                        start_time_=start_t,
                        end_time_=end_for_update,
                        allow_overlap=False,
                    )
                    if updated:
                        return jsonify({'updated': _serialize_appt(updated)})
            except ValueError as e:
                dur_min = int(duration) if duration else (_duration_minutes(start_t, end_t) if (start_t and end_t) else 60)
                day_appts = get_appointments_by_date(db, target)
                props = _find_all_free_slots(day_appts, dur_min, _time(0, 0, 0), _time(23, 59, 59), limit=5)
                return jsonify({
                    'error': 'Updated time slot conflicts with existing appointments',
                    'details': str(e),
                    'proposals': [
                        {'date': target.isoformat(), 'start_time': s.isoformat(), 'end_time': e.isoformat()}
                        for (s, e) in props
                    ]
                }), 409
            except Exception as e:
                print('CREATE->RESCHEDULE bridge failed:', e)

        if move_like:
            today_local = _date.today()
            window = get_appointments_for_week(
                db,
                today_local - timedelta(days=3),
                today_local + timedelta(days=10)
            )
            cand3 = [a for a in window if title and title.lower() in (a.description or '').lower()]
            cand3.sort(key=lambda a: (a.date, a.start_time))
            out = [_serialize_appt(a) for a in cand3[:10]]
            if not cand3:
                return jsonify({
                    'error': 'Could not find an existing appointment to move with that title.',
                    'hint': 'Tell me the original date/time or provide the appointment id.'
                }), 404
            else:
                return jsonify({
                    'error': 'Ambiguous source appointment for move.',
                    'candidates': out,
                    'hint': 'Specify which one (id, or date + time).'
                }), 409

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
        slot = _find_all_free_slots(day_appts, dur_min, _time(0, 0), _time(23, 59, 59), limit=1)
        return jsonify({
            'error': 'Time slot conflicts with existing appointments',
            'conflicts': [_serialize_appt(c) for c in conflicts],
            'suggested_slot': {'start': slot[0][0].isoformat(), 'end': slot[0][1].isoformat()} if slot else None
        }), 409

    # ----- MODIFYING / RESCHEDULING -----
    if intent in {'UPDATE_RESCHEDULE', 'RESCHEDULE', 'MOVE'}:
        selector = params.get('selector') or {}
        print("RESCHEDULE_DEBUG selector=", selector, "params=", params)
        ci_opt, mr_opt = _match_opts(selector, params)
        appt = None

        sel_id = selector.get('id') or params.get('id')
        if sel_id:
            appt = get_appointment_by_id(db, int(sel_id))

        if not appt:
            sel_date = _to_date(selector.get('date') or params.get('date'))
            sel_start = _to_time(selector.get('start_time') or params.get('start_time'))
            sel_end = _to_time(selector.get('end_time') or params.get('end_time'))
            sel_title = (selector.get('title') or params.get('title') or '').strip() or None
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

        if not appt:
            sel_title2 = (selector.get('title') or params.get('title') or '').strip() or None
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

        req_new_date = _to_date(params.get('new_date') or params.get('date'))
        req_new_start = _to_time(params.get('new_start_time') or params.get('new_start') or params.get('time'))
        req_new_end = _to_time(params.get('new_end_time') or params.get('new_end'))
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
            print("RESCHEDULE_DEBUG conflict:", e)
            base_dur = _duration_minutes(appt.start_time, appt.end_time)
            dur_min = _duration_minutes(target_start, target_end) if (target_start and target_end) else (base_dur if base_dur > 0 else 60)
            day_appts = get_appointments_by_date(db, target_date)
            props = _find_all_free_slots(day_appts, dur_min, _time(0, 0, 0), _time(23, 59, 59), limit=5)
            return jsonify({
                'error': 'Updated time slot conflicts with existing appointments',
                'details': str(e),
                'proposals': [
                    {'date': target_date.isoformat(), 'start_time': s.isoformat(), 'end_time': e.isoformat()}
                    for (s, e) in props
                ]
            }), 409
        except Exception as e:
            print("RESCHEDULE_DEBUG failure:", e)
            return jsonify({'error': 'Update failed', 'details': str(e)}), 500

    if intent in {'UPDATE_TITLE', 'UPDATE_RENAME', 'RENAME', 'CHANGE_TITLE'}:
        selector = params.get('selector') or {}
        ci_opt, mr_opt = _match_opts(selector, params)
        new_title = (params.get('new_title') or params.get('title') or '').strip()
        if not new_title:
            return jsonify({'error': 'Missing new title'}), 400

        appt = None
        sel_id = selector.get('id') or params.get('id')
        if sel_id:
            appt = get_appointment_by_id(db, int(sel_id))
        if not appt:
            sel_date = _to_date(selector.get('date') or params.get('date'))
            sel_start = _to_time(selector.get('start_time') or params.get('start_time'))
            sel_end = _to_time(selector.get('end_time') or params.get('end_time'))
            sel_title = (selector.get('title') or params.get('title') or params.get('old_title') or '').strip() or None

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

            if not appt and sel_title:
                today_local = _date.today()
                todays = get_appointments_by_date(db, today_local)
                cand = [a for a in todays if _fuzzy_match(
                    a.description or '',
                    sel_title,
                    case_insensitive=True if ci_opt is None else bool(ci_opt),
                    min_ratio=mr_opt if mr_opt is not None else 0.60,
                )]
                if len(cand) == 1:
                    appt = cand[0]
                if not appt:
                    win = get_appointments_for_week(db, today_local, today_local + timedelta(days=7))
                    cand2 = [a for a in win if _fuzzy_match(
                        a.description or '',
                        sel_title,
                        case_insensitive=True if ci_opt is None else bool(ci_opt),
                        min_ratio=mr_opt if mr_opt is not None else 0.60,
                    )]
                    if cand2:
                        cand2.sort(key=lambda a: (a.date, a.start_time))
                        appt = cand2[0]

        if not appt:
            return jsonify({'error': 'No matching appointment found to rename.'}), 404

        updated = update_appointment_title(db, appt.id, new_title)
        return jsonify({'updated': _serialize_appt(updated) if updated else None})

    if intent in {'MOVE_DAY_ALL', 'MOVE_DAY', 'MOVE_ALL_FROM_DATE'}:
        from_date = _to_date(params.get('from_date') or params.get('date'))
        to_date = _to_date(params.get('to_date') or params.get('new_date'))
        if not from_date or not to_date:
            return jsonify({'error': 'Missing from_date/to_date'}), 400
        updated, skipped = move_day_appointments(db, from_date, to_date, keep_times=True)
        return jsonify({
            'moved': [_serialize_appt(a) for a in updated],
            'skipped_conflicts': [_serialize_appt(a) for a in skipped],
        })

    if intent in {'CONVERT_TO_RECURRING', 'MAKE_RECURRING'}:
        selector = params.get('selector') or {}
        count = int(params.get('count') or 6)
        appt = None
        sel_id = selector.get('id') or params.get('id')
        if sel_id:
            appt = get_appointment_by_id(db, int(sel_id))
        if not appt:
            sel_date = _to_date(selector.get('date') or params.get('date'))
            sel_start = _to_time(selector.get('start_time') or params.get('start_time'))
            sel_end = _to_time(selector.get('end_time') or params.get('end_time'))
            matches = find_appointments(db, target_date=sel_date, start_time_=sel_start, end_time_=sel_end) if sel_date else []
            appt = matches[0] if matches else None
        if not appt:
            return jsonify({'error': 'No matching appointment to convert.'}), 404

        duration = _duration_minutes(appt.start_time, appt.end_time)
        entries = []
        d = appt.date
        made = 0
        while made < max(0, count - 1):
            d = d + timedelta(days=7)
            if not find_conflicts_for_slot(db, d, appt.start_time, appt.end_time):
                entries.append({
                    'date': d,
                    'start_time': appt.start_time,
                    'end_time': _add_minutes(appt.start_time, duration),
                    'description': appt.description,
                })
                made += 1
        created = bulk_create_appointments(db, entries, allow_overlap=False) if entries else []
        return jsonify({'created_many': [_serialize_appt(a) for a in created], 'base': _serialize_appt(appt)})

    # ----- CANCELLING / DELETING -----
    if intent in {'CANCEL_SINGLE', 'DELETE_SINGLE', 'DELETE'}:
        selector = params.get('selector') or {}
        ci_opt, mr_opt = _match_opts(selector, params)
        appt = None
        sel_id = selector.get('id') or params.get('id')
        if sel_id:
            appt = get_appointment_by_id(db, int(sel_id))
        if not appt:
            sel_date = _to_date(selector.get('date') or params.get('date'))
            sel_start = _to_time(selector.get('start_time') or params.get('start_time'))
            sel_end = _to_time(selector.get('end_time') or params.get('end_time'))
            sel_title = (selector.get('title') or params.get('title') or '').strip() or None
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
        if not appt:
            return jsonify({'error': 'No matching appointment found to delete.'}), 404

        ok = delete_appointment_by_id(db, appt.id)
        return jsonify({'deleted': bool(ok), 'id': appt.id})

    if intent in {'DELETE_ON_DATE', 'CANCEL_ON_DATE'}:
        target = _to_date(params.get('date')) or _date.today()
        term = (params.get('term') or params.get('title') or '').strip() or None
        victims = delete_on_date(db, target, term=term)
        return jsonify({'deleted_many': [_serialize_appt(a) for a in victims]})

    if intent in {'DELETE_BY_TERM', 'DELETE_BY_TEXT'}:
        term = (params.get('term') or params.get('title') or '').strip()
        if not term:
            return jsonify({'error': 'Missing term'}), 400
        victims = delete_by_search(db, term)
        return jsonify({'deleted_many': [_serialize_appt(a) for a in victims]})

    if intent in {'DELETE_BY_LABEL'}:
        label = (params.get('label') or '').strip()
        if not label:
            return jsonify({'error': 'Missing label'}), 400
        victims = delete_by_label(db, label)
        return jsonify({'deleted_many': [_serialize_appt(a) for a in victims]})

    # ----- Retrieval intents -----
    if intent in {'RETRIEVE_TODAY', 'TODAY'}:
        return _J(get_appointments_by_date(db, _date.today()))

    if intent in {'RETRIEVE_TOMORROW', 'TOMORROW'}:
        return _J(get_appointments_by_date(db, _date.today() + timedelta(days=1)))

    if intent in {'RETRIEVE_WEEK', 'THIS_WEEK'}:
        today = _date.today()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return _J(get_appointments_for_week(db, start, end))

    if intent in {'RETRIEVE_NEXT_WEEK', 'NEXT_WEEK'}:
        today = _date.today()
        this_mon = today - timedelta(days=today.weekday())
        next_mon = this_mon + timedelta(days=7)
        next_sun = next_mon + timedelta(days=6)
        return _J(get_appointments_for_week(db, next_mon, next_sun))

    if intent in {'RETRIEVE_MONTH', 'THIS_MONTH', 'LIST_MONTH'}:
        today = _date.today()
        year = int(params.get('year', today.year))
        month = int(params.get('month', today.month))
        m_start, m_end = _month_bounds(year, month)
        return _J(get_appointments_for_week(db, m_start, m_end))

    if intent in {'RETRIEVE_MONTH_TZ', 'THIS_MONTH_TZ'}:
        today = _date.today()
        year = int(params.get('year', today.year))
        month = int(params.get('month', today.month))
        tz = _normalize_tz((params.get('timezone') or params.get('tz') or '').strip())
        m_start, m_end = _month_bounds(year, month)
        if not tz:
            return _J(get_appointments_for_week(db, m_start, m_end))
        noon = _time(12, 0, 0)
        local_start, _ = _tz_to_local_date_time(m_start, noon, tz)
        local_end, _ = _tz_to_local_date_time(m_end, noon, tz)
        if local_end < local_start:
            local_start, local_end = local_end, local_start
        return _J(get_appointments_for_week(db, local_start, local_end))

    if intent in {'RETRIEVE_DATE', 'ON_DATE'}:
        target = _to_date(params.get('date')) or _date.today()
        return _J(get_appointments_by_date(db, target))

    if intent in {'RETRIEVE_BETWEEN', 'BETWEEN_TIMES'}:
        target = _to_date(params.get('date')) or _date.today()
        start_t = _to_time(params.get('start_time')) or _time(0, 0)
        end_t = _to_time(params.get('end_time')) or _time(23, 59, 59)

        dr = _parse_date_range_param(params.get('date_range'))
        if dr:
            start_d, end_d = dr
            return _J(get_appointments_for_week(db, start_d, end_d))

        if 'next 24' in q_lower.replace('hours', 'h') or 'next24' in q_lower.replace(' ', ''):
            now_dt = _dt.now().replace(microsecond=0)
            end_dt = now_dt + timedelta(hours=24)
            appts = get_appointments_for_week(db, now_dt.date(), end_dt.date())
            win = []
            for a in appts:
                a_start = _dt_combine(a.date, a.start_time)
                a_end = _dt_combine(a.date, a.end_time)
                if a_end > now_dt and a_start < end_dt:
                    win.append(a)
            return _J(win)

        if end_t <= start_t:
            day_end = _time(23, 59, 59)
            day_start = _time(0, 0, 0)
            part1 = crud_get_appointments_between(db, target, start_t, day_end)
            part2 = crud_get_appointments_between(db, target + timedelta(days=1), day_start, end_t)
            seen = set()
            merged = []
            for a in part1 + part2:
                if a.id not in seen:
                    seen.add(a.id)
                    merged.append(a)
            return _J(merged)

        return _J(crud_get_appointments_between(db, target, start_t, end_t))

    if intent in {'RETRIEVE_NOW', 'NOW', 'CURRENT', 'ONGOING', 'RIGHT_NOW', 'CURRENTLY'}:
        today = _date.today()
        now_t = _dt.now().time().replace(microsecond=0)
        todays = get_appointments_by_date(db, today)
        ongoing = [a for a in todays if a.start_time <= now_t < a.end_time]
        return _J(ongoing)

    if intent in {'RETRIEVE_NEXT_24H', 'NEXT_24H', 'ROLLING_DAY'}:
        now_dt = _dt.now().replace(microsecond=0)
        end_dt = now_dt + timedelta(hours=24)
        appts = get_appointments_for_week(db, now_dt.date(), end_dt.date())
        win = []
        for a in appts:
            a_start = _dt_combine(a.date, a.start_time)
            a_end = _dt_combine(a.date, a.end_time)
            if a_end > now_dt and a_start < end_dt:
                win.append(a)
        return _J(win)

    if intent in {'RETRIEVE_BETWEEN_TZ', 'BETWEEN_TZ', 'RETRIEVE_DATE_TZ', 'ON_DATE_TZ'}:
        tz = _normalize_tz((params.get('timezone') or params.get('tz') or '').strip())
        target = _to_date(params.get('date')) or _date.today()
        dr = _parse_date_range_param(params.get('date_range'))
        if dr:
            s, e = dr
            if tz:
                noon = _time(12, 0, 0)
                s_local, _ = _tz_to_local_date_time(s, noon, tz)
                e_local, _ = _tz_to_local_date_time(e, noon, tz)
                if e_local < s_local:
                    s_local, e_local = e_local, s_local
                return _J(get_appointments_for_week(db, s_local, e_local))
            else:
                return _J(get_appointments_for_week(db, s, e))
        st = _to_time(params.get('start_time')) if params.get('start_time') else None
        et = _to_time(params.get('end_time')) if params.get('end_time') else None
        if not tz:
            if st and et:
                if et <= st:
                    day_end = _time(23, 59, 59)
                    day_start = _time(0, 0, 0)
                    part1 = crud_get_appointments_between(db, target, st, day_end)
                    part2 = crud_get_appointments_between(db, target + timedelta(days=1), day_start, et)
                    seen = set()
                    merged = []
                    for a in part1 + part2:
                        if a.id not in seen:
                            seen.add(a.id)
                            merged.append(a)
                    return _J(merged)
                return _J(crud_get_appointments_between(db, target, st, et))
            else:
                if 'month' in q_lower:
                    today = _date.today()
                    m_start, m_end = _month_bounds(today.year, today.month)
                    return _J(get_appointments_for_week(db, m_start, m_end))
                return _J(get_appointments_by_date(db, target))
        if st and et:
            ld, lt = _tz_to_local_date_time(target, st, tz)
            rd, rt = _tz_to_local_date_time(target, et, tz)
            if ld == rd:
                return _J(crud_get_appointments_between(db, ld, lt, rt))
            else:
                day_end = _time(23, 59, 59)
                day_start = _time(0, 0, 0)
                part1 = crud_get_appointments_between(db, ld, lt, day_end)
                part2 = crud_get_appointments_between(db, rd, day_start, rt)
                seen = set()
                merged = []
                for a in part1 + part2:
                    if a.id not in seen:
                        seen.add(a.id)
                        merged.append(a)
                return _J(merged)
        else:
            noon = _time(12, 0, 0)
            local_date, _ = _tz_to_local_date_time(target, noon, tz)
            return _J(get_appointments_by_date(db, local_date))

    if intent in {'RETRIEVE_RANGE', 'DATE_RANGE', 'RANGE'}:
        start = _to_date(params.get('start_date') or params.get('from'))
        end = _to_date(params.get('end_date') or params.get('to'))
        if not start or not end:
            return jsonify({'error': 'Missing start_date/end_date'}), 400
        if start > end:
            start, end = end, start
        return _J(get_appointments_for_week(db, start, end))

    if intent in {'RETRIEVE_NEXT_72H', 'NEXT_72H', 'NEXT_3_DAYS'}:
        start = _date.today()
        end = start + timedelta(days=2)
        return _J(get_appointments_for_week(db, start, end))

    if intent in {'COUNT_WEEK', 'RETRIEVE_COUNT_WEEK'}:
        today = _date.today()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        cnt = count_appointments_in_range(db, start, end)
        return jsonify({'count': cnt})

    if 'WEEKEND' in intent:
        today = _date.today()
        year = int(params.get('year', today.year))
        month = int(params.get('month', today.month))
        return _J(get_appointments_on_weekends(db, year, month))

    if 'AFTER_TIME' in intent or intent == 'AFTER':
        today = _date.today()
        threshold = _to_time(params.get('time')) or _time(18, 0)
        return _J(get_appointments_after_time(db, today, threshold))

    if 'NEXT_UPCOMING' in intent or intent == 'NEXT':
        appt = get_next_appointment(db, _date.today())
        return jsonify({'appointment': _serialize_appt(appt) if appt else None})

    if 'COUNT_MONTH' in intent or ('COUNT' in intent and 'MONTH' in (params.get('scope', '') or '').upper()):
        today = _date.today()
        start_month = today.replace(day=1)
        next_month = (start_month.replace(year=start_month.year + 1, month=1, day=1)
                      if start_month.month == 12 else
                      start_month.replace(month=start_month.month + 1, day=1))
        end_month = next_month - timedelta(days=1)
        cnt = count_appointments_in_range(db, start_month, end_month)
        return jsonify({'count': cnt})

    if 'SEARCH' in intent or 'DESCRIPTION' in intent:
        term = (params.get('term') or '').strip()
        appts = search_appointments_by_description(db, term) if term else []
        return _J(appts)

    if 'FREE_TIME' in intent or 'FREE' in intent or 'AVAIL' in intent:
        target = _to_date(params.get('date')) or _date.today()
        appts = get_appointments_by_date(db, target)
        free = _compute_free_slots(appts)
        return jsonify({'free': free})

    if 'CONFLICT' in intent or 'OVERLAP' in intent:
        target = _to_date(params.get('date')) or _date.today()
        conflicts = get_conflicting_appointments(db, target)
        return jsonify({'conflicts': [[_serialize_appt(a) for a in pair] for pair in conflicts]})

    # No matching intent
    return None
