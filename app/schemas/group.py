"""Pydantic schemas for WhatsApp group CRUD."""

import uuid
import datetime as dt

from pydantic import BaseModel, Field, ConfigDict, field_validator


class GroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    whatsapp_group_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("name", "whatsapp_group_name", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class GroupCreate(GroupBase):
    pass


class GroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    whatsapp_group_name: str | None = Field(None, min_length=1, max_length=255)
    is_active: bool | None = None


class GroupRead(GroupBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    is_active: bool
    created_at: dt.datetime
