"""Pydantic schemas for schedule CRUD."""

import uuid
import datetime as dt
import re

from pydantic import BaseModel, Field, ConfigDict, field_validator

_VALID_DAYS = {"sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"}
_TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")


class ScheduleBase(BaseModel):
    message_template_id: uuid.UUID
    days_of_week: list[str] = Field(..., min_length=1)
    time_of_day: str = Field(..., pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    is_active: bool = True

    @field_validator("days_of_week", mode="before")
    @classmethod
    def validate_days(cls, v: object) -> object:
        if isinstance(v, list):
            normalised = [d.strip().lower() for d in v]
            invalid = [d for d in normalised if d not in _VALID_DAYS]
            if invalid:
                raise ValueError(f"Invalid days: {invalid}. Must be full day names e.g. 'tuesday'.")
            return normalised
        return v

    @field_validator("time_of_day", mode="before")
    @classmethod
    def normalise_time(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if re.match(r"^\d{2}:\d{2}$", v):
                return v + ":00"
        return v


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    message_template_id: uuid.UUID | None = None
    days_of_week: list[str] | None = None
    time_of_day: str | None = None
    is_active: bool | None = None


class ScheduleRead(ScheduleBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: dt.datetime
