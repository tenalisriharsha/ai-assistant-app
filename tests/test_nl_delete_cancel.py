"""
Regression test for a real-data-loss bug in the NL "cancel/delete" handler.

handle_nl_delete_cancel only recognizes a title via patterns like "titled X"
/ "called X" / "named X" (see _extract_title_from_text). A bare "cancel X"
doesn't match any of those, so title extraction silently fails — and the
no-date fallback then searched the next 7 days with NO title filter at all,
deleting whatever single appointment happened to be alone in that window,
regardless of whether it had anything to do with what was asked.

Concretely: "cancel Dentist Checkup" (a title that never existed) deleted an
unrelated appointment 5 days out, and reported success.

The fix: only widen the no-date search to the next 7 days when a title was
actually extracted (and filter by it there too). Without a title, the
search stays capped at today — never a blind guess across a wider window.
"""
from datetime import date, time, timedelta

import app as app_module
import crud
import database


def _client():
    return app_module.app.test_client()


def _assert_deleted(appt_id):
    # The delete happens in a different session (the Flask test client's own
    # with_db() session). Checking via a brand-new session avoids the
    # source session's identity map, which raises ObjectDeletedError rather
    # than returning None for an instance it had previously loaded.
    fresh = database.SessionLocal()
    try:
        assert crud.get_appointment_by_id(fresh, appt_id) is None
    finally:
        fresh.close()


def test_nonexistent_title_does_not_delete_an_unrelated_appointment(db):
    # A lone appointment several days out, unrelated to the query below.
    decoy_date = date.today() + timedelta(days=5)
    decoy = crud.create_appointment(db, decoy_date, time(10, 0), time(11, 0), "New event")

    resp = _client().post("/query", json={"query": "cancel Dentist Checkup"})

    assert resp.status_code == 404
    assert "No matching appointment found" in resp.get_json().get("error", "")

    # The decoy must still exist — this is the actual bug: it used to get
    # deleted even though its title has nothing to do with "Dentist Checkup".
    still_there = crud.get_appointment_by_id(db, decoy.id)
    assert still_there is not None


def test_no_title_no_date_still_deletes_the_sole_appointment_today(db):
    # This convenience case must keep working: no title, no date keyword at
    # all (so this actually exercises the no-date fallback, not the
    # separate target_date branch), but exactly one appointment today ->
    # delete it.
    today = date.today()
    appt = crud.create_appointment(db, today, time(15, 0), time(15, 30), "Team Sync")

    resp = _client().post("/query", json={"query": "cancel my appointment"})

    assert resp.status_code == 200
    assert resp.get_json().get("deleted") is True
    _assert_deleted(appt.id)


def test_extracted_title_still_widens_search_to_the_week(db):
    # When a title IS successfully extracted (via "titled X" / "called X" /
    # "named X"), the week-wide search must still work as before.
    target_date = date.today() + timedelta(days=3)
    appt = crud.create_appointment(db, target_date, time(9, 0), time(9, 30), "Dentist Checkup")

    resp = _client().post(
        "/query", json={"query": "cancel the appointment titled Dentist Checkup"}
    )

    assert resp.status_code == 200
    assert resp.get_json().get("deleted") is True
    _assert_deleted(appt.id)
