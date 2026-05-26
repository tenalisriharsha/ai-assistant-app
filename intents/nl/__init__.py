"""NL intent dispatcher — runs fast-path handlers in priority order."""

from typing import Optional
from flask import Response

from .handlers import (
    handle_nl_delete_cancel,
    handle_nl_reminders,
    handle_nl_free_availability,
    handle_nl_count_month,
    handle_nl_title_month,
    handle_nl_title_week,
    handle_nl_title_next_month,
    handle_nl_title_today,
    handle_nl_title_tomorrow,
    handle_nl_title_any,
    handle_nl_count_next_n_days,
    handle_nl_after_time,
    handle_nl_rename,
    handle_nl_delete_by_title,
    handle_nl_create_fallback,
    handle_nl_recurring,
    handle_human_date,
    handle_show_on_date,
    handle_recurring_weekly_fastpath,
)

# Ordered list of NL fast-path handlers.
# Each handler returns a Flask Response if matched, or None to fall through.
HANDLERS = [
    handle_nl_delete_cancel,
    handle_nl_reminders,
    handle_nl_free_availability,
    handle_nl_count_month,
    handle_nl_title_month,
    handle_nl_title_week,
    handle_nl_title_next_month,
    handle_nl_title_today,
    handle_nl_title_tomorrow,
    handle_nl_title_any,
    handle_nl_count_next_n_days,
    handle_nl_after_time,
    handle_nl_rename,
    handle_nl_delete_by_title,
    handle_nl_create_fallback,
    handle_nl_recurring,
    handle_human_date,
    handle_show_on_date,
    handle_recurring_weekly_fastpath,
]


def dispatch_nl(db, query: str, q_lower: str, data: dict) -> Optional[Response]:
    """Run all NL fast-path handlers in order. Return first match or None."""
    for handler in HANDLERS:
        result = handler(db, query, q_lower, data)
        if result is not None:
            return result
    return None
