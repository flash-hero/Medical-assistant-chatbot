"""Request and response bodies of the HTTP API (docs/contracts/api.md). Unknown fields are rejected."""

from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.schemas.chat import Locale
from core.text import sanitize

HARD_MESSAGE_CAP = 8000  # absolute cap; the configured AUSCULTA_MAX_MESSAGE_CHARS is checked in the route
_PHONE = re.compile(r"^\+?[0-9][0-9 ()\-.]{5,24}$")
# No whitespace, quotes, angle brackets or backticks: the address is shown to staff (review S18).
_EMAIL = re.compile(r"^[^@\s<>\"'`]{1,64}@[^@\s<>\"'`]{1,189}\.[^@\s<>\"'`]{2,}$")


class _Body(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


def _clean(value: str) -> str:
    """Remove smuggling/control characters from free-text form fields (they are shown to staff)."""
    return sanitize(value).text


class SessionCreate(_Body):
    locale: Locale = "en"


class SessionCreated(BaseModel):
    session_token: str
    session_id: str
    expires_at: str
    turns_left: int
    hospital: dict[str, Any] | None
    demo_mode: bool


class ChatBody(_Body):
    message: str = Field(min_length=1, max_length=HARD_MESSAGE_CAP)
    locale: Locale = "en"
    client_turn_id: UUID


class AppointmentBody(_Body):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=6, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    department_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    preferred_dates: str = Field(min_length=1, max_length=300)
    reason: str | None = Field(default=None, max_length=500)
    consent: Literal[True]

    @field_validator("full_name", "preferred_dates", "reason")
    @classmethod
    def _sanitised(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        if not _PHONE.match(value):
            raise ValueError("invalid phone number")
        return value

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        value = _clean(value)  # invisible / bidi / smuggling characters removed before the format check
        if not _EMAIL.match(value):
            raise ValueError("invalid e-mail address")
        return value


class AppointmentCreated(BaseModel):
    request_id: str
    message: str


class FeedbackBody(_Body):
    turn_id: UUID
    rating: Literal["up", "down"]
    reason: Literal["incorrect", "unsafe", "unhelpful", "other"] | None = None
    comment: str | None = Field(default=None, max_length=500)


class MetaInfo(BaseModel):
    app_version: str
    corpus_version: str
    prompt_hash: str
    models: dict[str, str]
    demo_mode: bool
