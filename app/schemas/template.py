"""Pydantic schemas for message template CRUD."""

import uuid
import datetime as dt

from pydantic import BaseModel, Field, ConfigDict, field_validator


class TemplateBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    content: str | None = Field(None, min_length=1)


class TemplateRead(TemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime
