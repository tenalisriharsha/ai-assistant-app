"""
Regression tests for the conversational create-appointment flow's session
handling: two clients must not share/clobber each other's in-progress flow,
and abandoned flows must eventually be pruned instead of growing forever.
"""
import app as app_module


def _client():
    return app_module.app.test_client()


def test_two_session_ids_do_not_share_flow_state(db):
    client = _client()

    # Both start the flow "fresh" behind what would be the same IP in curl,
    # but with distinct X-Session-Id headers (what the real frontend sends).
    r1 = client.post("/query", json={"query": "create appointment"}, headers={"X-Session-Id": "session-A"})
    r2 = client.post("/query", json={"query": "create appointment"}, headers={"X-Session-Id": "session-B"})
    assert r1.get_json()["awaiting"] == "date"
    assert r2.get_json()["awaiting"] == "date"

    # Answer them differently and confirm each session advances independently.
    rA = client.post("/query", json={"query": "today"}, headers={"X-Session-Id": "session-A"})
    rB = client.post("/query", json={"query": "tomorrow"}, headers={"X-Session-Id": "session-B"})

    assert rA.get_json()["awaiting"] == "time"
    assert rB.get_json()["awaiting"] == "time"

    # Session A must still be answering about "today", unaffected by B's "tomorrow".
    rA2 = client.post("/query", json={"query": "9:00 am"}, headers={"X-Session-Id": "session-A"})
    rB2 = client.post("/query", json={"query": "3:00 pm"}, headers={"X-Session-Id": "session-B"})

    rA3 = client.post("/query", json={"query": "15 mins"}, headers={"X-Session-Id": "session-A"})
    rB3 = client.post("/query", json={"query": "30 mins"}, headers={"X-Session-Id": "session-B"})

    rA4 = client.post("/query", json={"query": "Meeting A"}, headers={"X-Session-Id": "session-A"})
    rB4 = client.post("/query", json={"query": "Meeting B"}, headers={"X-Session-Id": "session-B"})

    apptA = rA4.get_json()["appointment"]
    apptB = rB4.get_json()["appointment"]

    assert apptA["title"] == "Meeting A"
    assert apptA["start_time"] == "09:00"
    assert apptB["title"] == "Meeting B"
    assert apptB["start_time"] == "15:00"
    assert apptA["date"] != apptB["date"]  # "today" vs "tomorrow"


def test_stale_sessions_are_pruned(monkeypatch):
    app_module.CREATE_APPT_SESSIONS.clear()
    app_module.CREATE_APPT_SESSION_TOUCHED.clear()

    now = app_module._dt.now().timestamp()
    app_module.CREATE_APPT_SESSIONS["stale"] = {"intent": "create_appointment", "awaiting": "date"}
    app_module.CREATE_APPT_SESSION_TOUCHED["stale"] = now - (2 * app_module.CREATE_APPT_SESSION_TTL_SECONDS)

    app_module.CREATE_APPT_SESSIONS["fresh"] = {"intent": "create_appointment", "awaiting": "time"}
    app_module.CREATE_APPT_SESSION_TOUCHED["fresh"] = now

    app_module._prune_stale_create_sessions()

    assert "stale" not in app_module.CREATE_APPT_SESSIONS
    assert "fresh" in app_module.CREATE_APPT_SESSIONS
