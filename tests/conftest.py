import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway SQLite file instead of the real appointments.db.
# This must run before any test module imports models/database/crud/app,
# since the DB URL is read once at import time.
_tmp_dir = tempfile.mkdtemp(prefix="scheduler_ai_test_")
os.environ["SCHEDULER_DB_URL"] = f"sqlite:///{os.path.join(_tmp_dir, 'test_appointments.db')}"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import database  # noqa: E402  (import triggers init_db()/ensure_schema() against the temp DB)
from models import Appointment, Reminder  # noqa: E402


@pytest.fixture()
def db():
    """A session against the isolated test database, wiped clean after each test."""
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()
        cleanup = database.SessionLocal()
        cleanup.query(Appointment).delete()
        cleanup.query(Reminder).delete()
        cleanup.commit()
        cleanup.close()
