"""Hospital profile: the ONLY source of hospital facts, phone numbers and emergency contacts.

Loaded from AUSCULTA_HOSPITAL_PROFILE (YAML). Receptionist features are disabled when it fails validation
or is expired. Phone-like strings in model output must appear in `allowed_numbers()`.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

_PHONE = re.compile(r"^\+?[0-9][0-9 ()\-.]{1,24}$")


class L10n(BaseModel):
    """Localised string. English is mandatory; missing FR/AR fall back to English with a flag in the UI."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    en: str = Field(min_length=1)
    fr: str | None = None
    ar: str | None = None

    def get(self, locale: str) -> str:
        return getattr(self, locale, None) or self.en


class PhoneContact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: L10n
    number: str
    hours: L10n | None = None

    @model_validator(mode="after")
    def _valid_number(self) -> PhoneContact:
        if not _PHONE.match(self.number):
            raise ValueError(f"invalid phone number format: {self.number!r}")
        return self


class Department(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: L10n
    description: L10n | None = None
    location: L10n | None = None  # building / floor
    phone: str | None = None
    hours: L10n | None = None
    accepts_appointments: bool = False
    keywords: tuple[str, ...] = ()  # EN/FR/AR synonyms for matching


class FAQ(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    question: L10n
    answer: L10n
    keywords: tuple[str, ...] = ()


class HospitalProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: L10n
    is_demo: bool = True  # demo profiles show a banner and fictional data
    country: str = Field(min_length=2, max_length=2)  # ISO 3166-1 alpha-2
    timezone: str
    address: L10n
    website: HttpUrl | None = None
    main_phone: PhoneContact
    emergency: PhoneContact  # national emergency number for the hospital's country
    crisis_lines: tuple[PhoneContact, ...] = ()  # suicide / mental-health crisis lines
    poison_control: PhoneContact | None = None
    handoff: PhoneContact  # human contact offered in every conversation
    visiting_hours: L10n | None = None
    documents_to_bring: L10n | None = None
    insurance: L10n | None = None
    directions: L10n | None = None
    departments: tuple[Department, ...] = ()
    faqs: tuple[FAQ, ...] = ()
    verified_by: str
    verified_on: date
    expires_on: date

    def allowed_numbers(self) -> frozenset[str]:
        """Digits-only forms of every number the assistant may ever output."""
        nums = [self.main_phone.number, self.emergency.number, self.handoff.number]
        nums += [c.number for c in self.crisis_lines]
        nums += [self.poison_control.number] if self.poison_control else []
        nums += [d.phone for d in self.departments if d.phone]
        return frozenset(re.sub(r"\D", "", n) for n in nums)

    def is_valid_on(self, day: date) -> bool:
        return self.verified_on <= day <= self.expires_on
