"""
Regression tests for the reminder due-check timezone bug.

Reminder.date/Reminder.time are stored as naive local wall-clock values (the
same convention as Appointment), never converted to UTC anywhere. The bug:
get_due_reminders() was being called with an aware UTC "now" (app.py used to
do _dt.now(_tz.utc)), so the due-check compared local-stored values against a
UTC clock — reminders fired early or late by the local UTC offset, and on
machines west of UTC, any reminder dated "today" could look overdue the
instant it was created, because UTC had already rolled to the next day.
"""
from datetime import date, datetime, time, timedelta

import crud


def _create_reminder(db, *, date_, time_, title):
    return crud.create_reminder(db, date_=date_, time_=time_, title=title)


class TestDueReminderClassification:
    """get_due_reminders() must correctly separate past-vs-future relative
    to whatever `now` it's given, independent of timezone concerns (those
    live entirely in what the caller passes as `now`)."""

    def test_past_reminder_is_due(self, db):
        now = datetime(2030, 6, 15, 12, 0, 0)
        _create_reminder(db, date_=now.date(), time_=(now - timedelta(minutes=5)).time(), title="past")

        due = crud.get_due_reminders(db, now=now)

        assert any(r.title == "past" for r in due)

    def test_future_reminder_is_not_due(self, db):
        now = datetime(2030, 6, 15, 12, 0, 0)
        _create_reminder(db, date_=now.date(), time_=(now + timedelta(minutes=5)).time(), title="future")

        due = crud.get_due_reminders(db, now=now)

        assert not any(r.title == "future" for r in due)

    def test_earlier_date_is_due_regardless_of_time(self, db):
        now = datetime(2030, 6, 15, 0, 30, 0)
        _create_reminder(db, date_=date(2030, 6, 14), time_=time(23, 59), title="yesterday-late")

        due = crud.get_due_reminders(db, now=now)

        assert any(r.title == "yesterday-late" for r in due)


class TestReminderDueCallSitesUseLocalTime:
    """Lock in the actual fix: every call site must pass a naive (local)
    datetime as `now`, not an aware UTC one — that convention mismatch was
    the entire bug. This exercises the real production code paths via
    monkeypatching get_due_reminders to capture what they actually pass."""

    @staticmethod
    def _spy(captured):
        original = crud.get_due_reminders

        def spy(db, now=None):
            captured["now"] = now
            return original(db, now=now)

        return spy

    def _assert_naive_now(self, captured):
        assert "now" in captured, "get_due_reminders was not called"
        assert captured["now"] is not None
        assert captured["now"].tzinfo is None, (
            "reminders_due must pass a naive local datetime (Reminder.date/time "
            "are naive local values) — got a timezone-aware datetime instead"
        )

    def test_app_reminders_due_action_uses_local_time(self, db, monkeypatch):
        # app.py does `from crud import get_due_reminders`, which binds its
        # own module-level name at import time — patching crud.get_due_reminders
        # afterward wouldn't affect that binding, so patch app's own name.
        import app as app_module

        captured = {}
        monkeypatch.setattr(app_module, "get_due_reminders", self._spy(captured))

        client = app_module.app.test_client()
        resp = client.post("/query", json={"action": "reminders_due"})
        assert resp.status_code == 200

        self._assert_naive_now(captured)

    def test_intents_reminders_handler_uses_local_time(self, db, monkeypatch):
        # Same binding subtlety as above: patch intents.reminders' own name.
        import intents.reminders as reminders_module

        captured = {}
        monkeypatch.setattr(reminders_module, "get_due_reminders", self._spy(captured))

        reminders_module.handle_reminder_action(db, "reminders_due", {})

        self._assert_naive_now(captured)
