# flows/create_appointment_flow.py

from __future__ import annotations

from datetime import date as _date, datetime as _dt, time as _time, timedelta
from typing import Dict, Any, Optional, Tuple
import re

from crud import create_appointment, _parse_time_str_raw  # reuse existing parser


# -------------------------
# Parsing helpers
# -------------------------

def _parse_date_phrase(text: str) -> Optional[_date]:
    """
    Understands:
      - today
      - tomorrow
      - day after tomorrow / day after
      - explicit dd/mm/yyyy or dd-mm-yyyy
    """
    if not text:
        return None

    today = _date.today()
    t = text.strip().lower()

    if "day after tomorrow" in t or "dayafter tomorrow" in t or "day after" in t:
        return today + timedelta(days=2)
    if "tomorrow" in t:
        return today + timedelta(days=1)
    if "today" in t:
        return today

    # explicit date: dd/mm/yyyy or dd-mm-yyyy
    m = re.search(r"\b(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})\b", t)
    if m:
        d = int(m.group(1))
        mth = int(m.group(2))
        y = int(m.group(3))
        try:
            return _date(y, mth, d)
        except ValueError:
            return None

    return None


def _parse_duration_minutes(text: str) -> Optional[int]:
    """
    Parse things like:
      - 60 mins / 60 min / 60 minutes
      - 2 hours / 2 hour / 2 hrs / 2 hr
    Returns total minutes, or None if nothing found.
    """
    if not text:
        return None

    t = text.lower()

    # minutes pattern
    m = re.search(r"(\d+)\s*(mins?|minutes?)", t)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    # hours pattern
    h = re.search(r"(\d+)\s*(hours?|hrs?|hr)", t)
    if h:
        try:
            return int(h.group(1)) * 60
        except ValueError:
            pass

    return None


def _extract_time(text: str) -> Optional[_time]:
    """
    Extract a time from the whole sentence, e.g. 'at 11am', 'at 3:15 pm'.
    Reuses crud._parse_time_str_raw for robustness.
    """
    if not text:
        return None
    t = text.lower()

    # look for "at <time>" first
    m = re.search(r"\bat\s+([0-9]{1,2}(:[0-9]{2})?\s*(am|pm)?)", t)
    if m:
        parsed = _parse_time_str_raw(m.group(1))
        if parsed:
            return parsed

    # fallback: any standalone time-like token
    m2 = re.search(r"\b([0-9]{1,2}(:[0-9]{2})?\s*(am|pm))\b", t)
    if m2:
        parsed = _parse_time_str_raw(m2.group(1))
        if parsed:
            return parsed

    return None


def _extract_title(text: str) -> Optional[str]:
    """
    Try to pull out a short title:
      - after 'title' (e.g., 'with title school')
      - after 'called' (e.g., 'called dentist')
      - otherwise, None (we'll ask the user)
    """
    if not text:
        return None
    t = text.strip()

    # with title XYZ
    m = re.search(r"title\s+(.+)$", t, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # called XYZ
    m2 = re.search(r"(?:called|call it)\s+(.+)$", t, flags=re.IGNORECASE)
    if m2:
        return m2.group(1).strip()

    return None


def _compute_end_time(start: _time, duration_minutes: int) -> _time:
    dt = _dt.combine(_date.today(), start) + timedelta(minutes=int(duration_minutes))
    return dt.time().replace(microsecond=0)


# -------------------------
# Flow state + public API
# -------------------------

# state_bucket[session_key] = {
#   "intent": "create_appointment",
#   "pending": {
#       "date": date | None,
#       "start_time": time | None,
#       "duration_minutes": int | None,
#       "title": str | None,
#   },
#   "awaiting": "date" | "time" | "duration" | "title" | None,
# }

def _is_create_intent(raw: str) -> bool:
    if not raw:
        return False
    t = raw.strip().lower()
    # ---- BLOCK recurring patterns from entering this flow ----
    recurring_keywords = [
        "every day",
        "every week",
        "every month",
        "weekly",
        "daily",
        "monthly",
        "every monday",
        "every tuesday",
        "every wednesday",
        "every thursday",
        "every friday",
        "every saturday",
        "every sunday",
        "every 2 weeks",
        "every two weeks",
        "biweekly",
        "fortnight",
    ]
    for kw in recurring_keywords:
        if kw in t:
            return False  # Let main app handle recurring
    # you can extend this list
    return (
        t.startswith("create an appointment")
        or t.startswith("create appointment")
        or t.startswith("schedule an appointment")
        or t.startswith("schedule appointment")
    )


def _initial_parse(raw: str) -> Dict[str, Any]:
    """Parse date/time/duration/title from the original sentence."""
    return {
        "date": _parse_date_phrase(raw),
        "start_time": _extract_time(raw),
        "duration_minutes": _parse_duration_minutes(raw),
        "title": _extract_title(raw),
    }


def _next_missing(pending: Dict[str, Any]) -> Optional[str]:
    if pending.get("date") is None:
        return "date"
    if pending.get("start_time") is None:
        return "time"
    if pending.get("duration_minutes") is None:
        return "duration"
    if not pending.get("title"):
        return "title"
    return None


def _prompt_for(missing: str) -> str:
    if missing == "date":
        return (
            "Should I create it for **today**, **tomorrow**, **day after**, "
            "or type a date in the format **dd/mm/yyyy**?"
        )
    if missing == "time":
        return (
            "What time should I schedule it? For example: **11am**, **12 pm**, "
            "or **11:23 am**."
        )
    if missing == "duration":
        return (
            "For how long should I make this appointment? For example: "
            "**20 mins**, **45 minutes**, or **2 hours**."
        )
    if missing == "title":
        return (
            "What should I call this appointment? For example: "
            "**walking**, **school**, or **dentist**."
        )
    return "I need a bit more information to create this appointment."


def _apply_answer_to_state(answer: str, state: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Apply user answer to whatever field we were waiting for."""
    pending = state.setdefault("pending", {})
    awaiting = state.get("awaiting")
    answer = (answer or "").strip()

    if awaiting == "date":
        d = _parse_date_phrase(answer)
        if not d:
            return state, (
                "I couldn't understand that date. Please say **today**, **tomorrow**, "
                "**day after**, or type it as **dd/mm/yyyy**."
            )
        pending["date"] = d

    elif awaiting == "time":
        t = _parse_time_str_raw(answer)
        if not t:
            return state, (
                "I couldn't understand that time. Please enter something like "
                "**11am**, **12 pm**, or **11:23 am**."
            )
        pending["start_time"] = t

    elif awaiting == "duration":
        mins = _parse_duration_minutes(answer)
        if mins is None:
            return state, (
                "I couldn't understand that duration. Please say things like "
                "**20 mins**, **45 minutes**, or **2 hours**."
            )
        pending["duration_minutes"] = mins

    elif awaiting == "title":
        if not answer:
            return state, "Please provide a short one- or two-word title, like **walking**."
        pending["title"] = answer

    # clear awaiting; caller will decide if more is needed
    state["awaiting"] = None
    return state, None


def _finalize_creation(db, pending: Dict[str, Any]) -> Dict[str, Any]:
    """Actually create the appointment in the database."""
    date_ = pending["date"]
    start_time_ = pending["start_time"]
    duration_minutes = pending["duration_minutes"]
    title = pending["title"] or ""

    end_time_ = _compute_end_time(start_time_, duration_minutes)

    try:
        appt = create_appointment(
            db,
            date_=date_,
            start_time_=start_time_,
            end_time_=end_time_,
            description_=title,
            allow_overlap=False,
        )
    except ValueError as ve:
        # time conflict or similar
        return {
            "status": "error",
            "message": f"I couldn't create that appointment because: {ve}",
            "appointment": None,
        }

    msg = (
        f"Done! I created **“{title}”** on **{date_.isoformat()}** "
        f"from **{start_time_.strftime('%H:%M')}** to **{end_time_.strftime('%H:%M')}**."
    )
    return {
        "status": "created",
        "message": msg,
        "appointment": {
            "id": appt.id,
            "date": appt.date.isoformat(),
            "start_time": appt.start_time.strftime("%H:%M"),
            "end_time": appt.end_time.strftime("%H:%M"),
            "title": appt.description or "",
        },
    }


def handle_create_appointment_flow(
    db,
    raw_query: str,
    state_bucket: Dict[str, Dict[str, Any]],
    *,
    session_key: str = "default",
) -> Optional[Dict[str, Any]]:
    """
    Main entry point used by app.py.

    Returns:
      - None  -> not a create-appointment intent and not a continuation
      - dict  -> a response describing either:
          { "status": "need_more_info", "message": "...", "awaiting": "date" | ... }
          { "status": "created", "message": "...", "appointment": {...} }
          { "status": "error", "message": "..." }
    """
    raw = (raw_query or "").strip()
    if not raw:
        return None

    state = state_bucket.get(session_key)

    # 1) Continuation of an existing create flow?
    if state and state.get("intent") == "create_appointment" and state.get("awaiting"):
        state, error_msg = _apply_answer_to_state(raw, state)
        pending = state["pending"]
        missing = _next_missing(pending)

        if error_msg:
            # still missing same thing
            state_bucket[session_key] = state
            return {
                "flow": "create_appointment",
                "status": "need_more_info",
                "awaiting": state.get("awaiting"),
                "message": error_msg,
            }

        if missing:
            # ask for the next missing piece
            state["awaiting"] = missing
            state_bucket[session_key] = state
            return {
                "flow": "create_appointment",
                "status": "need_more_info",
                "awaiting": missing,
                "message": _prompt_for(missing),
            }

        # all fields present -> create appointment, then clear state
        result = _finalize_creation(db, pending)
        state_bucket.pop(session_key, None)
        result["flow"] = "create_appointment"
        return result

    # 2) New create-appointment intent?
    if not _is_create_intent(raw):
        return None  # let the rest of app.py handle it

    # initial parse
    parsed = _initial_parse(raw)
    pending = {
        "date": parsed["date"],
        "start_time": parsed["start_time"],
        "duration_minutes": parsed["duration_minutes"],
        "title": parsed["title"],
    }

    missing = _next_missing(pending)

    new_state = {
        "intent": "create_appointment",
        "pending": pending,
        "awaiting": missing,
    }
    state_bucket[session_key] = new_state

    if missing:
        # Ask the user the first clarifying question
        return {
            "flow": "create_appointment",
            "status": "need_more_info",
            "awaiting": missing,
            "message": _prompt_for(missing),
            "buttons": (
                [
                    {"label": "Today", "value": "today"},
                    {"label": "Tomorrow", "value": "tomorrow"},
                    {"label": "Day After", "value": "day after"},
                ] if missing == "date" else
                [
                    {"label": "9:00 AM", "value": "9:00 am"},
                    {"label": "3:00 PM", "value": "3:00 pm"},
                    {"label": "5:30 PM", "value": "5:30 pm"},
                ] if missing == "time" else
                [
                    {"label": "15 mins", "value": "15 mins"},
                    {"label": "30 mins", "value": "30 mins"},
                    {"label": "1 hour", "value": "1 hour"},
                ] if missing == "duration" else
                None
            ),
        }

    # no fields missing -> create immediately
    result = _finalize_creation(db, pending)
    state_bucket.pop(session_key, None)
    result["flow"] = "create_appointment"
    return result
