"""Pydantic schemas for user authentication and profile."""

import re
import uuid
import datetime as dt

from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator

_PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{6,}$")


class UserBase(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    email: EmailStr = Field(..., max_length=255)

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("username", mode="before")
    @classmethod
    def normalise_username(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be 72 bytes or fewer.")
        if not _PASSWORD_RE.match(v):
            raise ValueError(
                "Password must have at least 6 characters, one uppercase, one lowercase, one digit, and one special character."
            )
        return v


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    wa_linked: bool
    created_at: dt.datetime


class UserLogin(BaseModel):
    username: str
    password: str


class UserToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
