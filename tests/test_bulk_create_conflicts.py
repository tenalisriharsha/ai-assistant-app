"""
Regression tests for the bulk_create_appointments in-batch conflict gap.

bulk_create_appointments(allow_overlap=False) used to pre-check each entry's
conflicts with a plain DB query, but nothing in the batch is committed until
the very end (session autoflush=False) — so two overlapping entries within
the *same* batch couldn't see each other and both got created. The fix
tracks entries already validated earlier in the same batch, mirroring the
pattern already used correctly in bulk_create_appointments_lenient.
"""
from datetime import date, time

import pytest

import crud


DAY = date(2031, 3, 10)


def test_overlapping_entries_in_same_batch_are_rejected(db):
    entries = [
        {"date": DAY, "start_time": time(10, 0), "end_time": time(11, 0), "description": "A"},
        {"date": DAY, "start_time": time(10, 30), "end_time": time(11, 30), "description": "B overlaps A"},
    ]

    with pytest.raises(ValueError):
        crud.bulk_create_appointments(db, entries, allow_overlap=False)

    # No partial commit: neither entry should have been persisted.
    assert crud.get_appointments_by_date(db, DAY) == []


def test_non_overlapping_entries_in_same_batch_all_succeed(db):
    entries = [
        {"date": DAY, "start_time": time(9, 0), "end_time": time(10, 0), "description": "A"},
        {"date": DAY, "start_time": time(10, 0), "end_time": time(11, 0), "description": "B back-to-back"},
    ]

    created = crud.bulk_create_appointments(db, entries, allow_overlap=False)

    assert len(created) == 2
    assert len(crud.get_appointments_by_date(db, DAY)) == 2


def test_conflict_against_pre_existing_appointment_is_still_caught(db):
    crud.bulk_create_appointments(
        db,
        [{"date": DAY, "start_time": time(9, 0), "end_time": time(10, 0), "description": "Existing"}],
        allow_overlap=False,
    )

    with pytest.raises(ValueError):
        crud.bulk_create_appointments(
            db,
            [{"date": DAY, "start_time": time(9, 30), "end_time": time(9, 45), "description": "Conflicts"}],
            allow_overlap=False,
        )

    assert len(crud.get_appointments_by_date(db, DAY)) == 1
