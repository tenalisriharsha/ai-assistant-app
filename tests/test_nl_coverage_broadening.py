"""
Regression tests for broadened NL fast-path coverage.

A systematic sweep of free-form NL phrases across every capability found
that, without a Groq API key (the default for local dev — the naive local
fallback parser handles what fast-path handlers miss), several common
phrasings had no coverage at all and returned "Unable to parse query":

  - "what's on my calendar this week" / "what do I have this week"
  - "what are my reminders"
  - "schedule a call with the dentist tomorrow at 3pm" (no literal
    "appointment"/"meeting" word, so it fell through to the naive parser,
    which silently misread it as a date-only retrieval instead of erroring
    or creating anything)

These tests lock in the new handle_nl_show_timeframe, handle_nl_list_reminders,
and the broadened handle_nl_create_fallback trigger.
"""
from datetime import date, time, timedelta

import app as app_module
import crud


def _client():
    return app_module.app.test_client()


def test_what_do_i_have_this_week(db):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    appt = crud.create_appointment(db, monday, time(9, 0), time(9, 30), "Standup")

    resp = _client().post("/query", json={"query": "what do I have this week"})

    assert resp.status_code == 200
    titles = [a["title"] for a in resp.get_json()["appointments"]]
    assert "Standup" in titles


def test_whats_on_my_calendar_today(db):
    today = date.today()
    appt = crud.create_appointment(db, today, time(14, 0), time(14, 30), "Sync")

    resp = _client().post("/query", json={"query": "what's on my calendar today"})

    assert resp.status_code == 200
    titles = [a["title"] for a in resp.get_json()["appointments"]]
    assert "Sync" in titles


def test_my_schedule_this_month_is_not_swallowed_by_create_verb_check(db):
    # "schedule" appears here as a noun ("my schedule"), not a create verb —
    # must not be rejected by the create-verb exclusion.
    resp = _client().post("/query", json={"query": "my schedule this month"})
    assert resp.status_code == 200
    assert "appointments" in resp.get_json()


def test_what_are_my_reminders(db):
    r = crud.create_reminder(db, date_=date.today(), time_=time(17, 0), title="call mom")

    resp = _client().post("/query", json={"query": "what are my reminders"})

    assert resp.status_code == 200
    titles = [x["title"] for x in resp.get_json()["reminders"]]
    assert "call mom" in titles


def test_reminder_create_still_wins_over_list_reminders(db):
    # "remind me..." must still create a reminder, not get swallowed by the
    # new list-reminders handler.
    resp = _client().post("/query", json={"query": "remind me at 3pm to call Alex"})
    assert resp.status_code == 200
    assert resp.get_json().get("reminder", {}).get("title") == "call Alex"


def test_create_without_the_word_appointment_or_meeting(db):
    resp = _client().post(
        "/query",
        json={"query": "schedule a call with the dentist tomorrow at 3pm for 30 minutes"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("created") is not None
    assert body["created"]["start_time"] == "15:00:00"
    # Direct-object title extraction: not the generic "New appointment" default.
    assert "dentist" in body["created"]["title"].lower()


def test_create_with_the_word_appointment_still_works(db):
    # Existing, previously-working phrasing must be unaffected. Deliberately
    # starts with "book" rather than "schedule an appointment"/"create
    # appointment" — those exact prefixes are intercepted earlier by the
    # separate multi-turn conversational flow (flows/create_appointment_flow.py).
    # Also avoids "called/titled/named X" + a timeframe word together, which
    # a separate, pre-existing handler (handle_nl_title_tomorrow) claims
    # first as a title search — unrelated to the change under test here.
    resp = _client().post(
        "/query",
        json={"query": "book an appointment tomorrow at 2pm"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("created") is not None
    assert body["created"]["start_time"] == "14:00:00"
