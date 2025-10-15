# schemas.py

from pydantic import BaseModel, model_validator
from datetime import date, time, datetime
from typing import Optional


# -----------------------------
# Base (shared) fields
# -----------------------------
class AppointmentBase(BaseModel):
    # Required (existing)
    date: date
    start_time: time
    end_time: time

    # Existing optional
    description: Optional[str] = None

    # New optional (all non-breaking)
    title: Optional[str] = None
    label: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    modality: Optional[str] = None           # 'zoom', 'in-person', etc.
    timezone: Optional[str] = None           # e.g., 'America/Los_Angeles'
    attendees: Optional[str] = None          # keep string for DB-compat; can store CSV/JSON
    recurrence_rule: Optional[str] = None    # e.g., iCal RRULE
    reminder_offset_min: Optional[int] = None
    tentative: Optional[bool] = None
    is_all_day: Optional[bool] = None
    notes: Optional[str] = None
    external_id: Optional[str] = None

    # Pydantic v2 config
    model_config = {
        "from_attributes": True,  # ORM mode
        "json_encoders": {
            date: lambda v: v.isoformat(),
            time: lambda v: v.isoformat(),
            datetime: lambda v: v.isoformat(),
        },
    }

    # Ensure valid time window on base/create models
    @model_validator(mode="after")
    def _validate_time_window(self):
        # Only enforce when both are present (they are required here)
        if self.start_time and self.end_time and not (self.end_time > self.start_time):
            raise ValueError("end_time must be after start_time")
        return self


# For creates; inherits everything from base (all new fields are optional)
class AppointmentCreate(AppointmentBase):
    """Payload for creating a new appointment."""
    pass


# For partial updates (all fields optional)
class AppointmentUpdate(BaseModel):
    date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    description: Optional[str] = None

    title: Optional[str] = None
    label: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    modality: Optional[str] = None
    timezone: Optional[str] = None
    attendees: Optional[str] = None
    recurrence_rule: Optional[str] = None
    reminder_offset_min: Optional[int] = None
    tentative: Optional[bool] = None
    is_all_day: Optional[bool] = None
    notes: Optional[str] = None
    external_id: Optional[str] = None

    model_config = {
        "from_attributes": True,
        "json_encoders": {
            date: lambda v: v.isoformat(),
            time: lambda v: v.isoformat(),
            datetime: lambda v: v.isoformat(),
        },
    }

    # Only validate time ordering if both times are provided in a partial update
    @model_validator(mode="after")
    def _validate_partial_time_window(self):
        if self.start_time is not None and self.end_time is not None:
            if not (self.end_time > self.start_time):
                raise ValueError("end_time must be after start_time on update")
        return self


# A tiny helper for selecting an appointment without an ID
# (used by update/delete endpoints and NL flows)
class AppointmentSelector(BaseModel):
    id: Optional[int] = None
    date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    term: Optional[str] = None  # search by title/description substring

    model_config = {
        "from_attributes": True,
        "json_encoders": {
            date: lambda v: v.isoformat(),
            time: lambda v: v.isoformat(),
            datetime: lambda v: v.isoformat(),
        },
    }


# Response model
class Appointment(AppointmentBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None