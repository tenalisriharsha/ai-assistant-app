from typing import Any, Dict, Optional

from schemas import Appointment as AppointmentSchema
from pydantic import ValidationError

from .dates import _duration_minutes


def _serialize_appt(a) -> Dict[str, Any]:
    try:
        return AppointmentSchema.model_validate(a).model_dump(mode="json")
    except Exception as e:
        print("SERIALIZE_WARNING:", getattr(a, "id", None), e)
        return {
            "id": getattr(a, "id", None),
            "date": a.date.isoformat() if getattr(a, "date", None) else None,
            "start_time": a.start_time.isoformat() if getattr(a, "start_time", None) else None,
            "end_time": a.end_time.isoformat() if getattr(a, "end_time", None) else None,
            "description": getattr(a, "description", None),
            "title": getattr(a, "title", getattr(a, "description", None)),
            "invalid": "end_time must be after start_time",
        }


def _serialize_reminder(r, db=None, *, include_appt: bool = True, appt=None) -> Dict[str, Any]:
    try:
        d: Dict[str, Any] = {
            'id': getattr(r, 'id', None),
            'date': r.date.isoformat() if getattr(r, 'date', None) else None,
            'time': r.time.isoformat() if getattr(r, 'time', None) else None,
            'title': getattr(r, 'title', None),
            'lead_minutes': int(getattr(r, 'lead_minutes', 0) or 0),
            'channel': getattr(r, 'channel', None),
            'active': bool(getattr(r, 'active', True)),
            'delivered': bool(getattr(r, 'delivered', False)),
            'appointment_id': getattr(r, 'appointment_id', None),
        }
        if include_appt and (appt is not None or (db is not None and getattr(r, 'appointment_id', None))):
            try:
                from crud import get_appointment_by_id
                _a = appt or get_appointment_by_id(db, int(r.appointment_id))
                if _a:
                    d['appt_title'] = (_a.description or getattr(_a, 'title', '') or '')[:255]
                    d['appt_duration_minutes'] = _duration_minutes(_a.start_time, _a.end_time)
                    d['appt_start'] = _a.start_time.isoformat() if getattr(_a, 'start_time', None) else None
                    d['appt_end'] = _a.end_time.isoformat() if getattr(_a, 'end_time', None) else None
            except Exception:
                pass
        return d
    except Exception as e:
        return {
            'id': getattr(r, 'id', None),
            'date': getattr(r, 'date', None).isoformat() if getattr(r, 'date', None) else None,
            'time': getattr(r, 'time', None).isoformat() if getattr(r, 'time', None) else None,
            'title': getattr(r, 'title', None),
            'lead_minutes': int(getattr(r, 'lead_minutes', 0) or 0),
            'channel': getattr(r, 'channel', None),
            'active': bool(getattr(r, 'active', True)),
            'delivered': bool(getattr(r, 'delivered', False)),
            'appointment_id': getattr(r, 'appointment_id', None),
        }
