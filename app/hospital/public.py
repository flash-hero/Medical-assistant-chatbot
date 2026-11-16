"""PublicHospital: the subset of the profile exposed by GET /api/v1/hospital, resolved to one locale."""

from __future__ import annotations

from typing import Any

from core.schemas.hospital import HospitalProfile, PhoneContact


def _contact(c: PhoneContact, locale: str) -> dict[str, str]:
    return {"label": c.label.get(locale), "number": c.number, "hours": c.hours.get(locale) if c.hours else ""}


def public_hospital(profile: HospitalProfile, locale: str) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name.get(locale),
        "is_demo": profile.is_demo,
        "address": profile.address.get(locale),
        "main_phone": _contact(profile.main_phone, locale),
        "emergency": _contact(profile.emergency, locale),
        "crisis_lines": [_contact(c, locale) for c in profile.crisis_lines],
        "handoff": _contact(profile.handoff, locale),
        "visiting_hours": profile.visiting_hours.get(locale) if profile.visiting_hours else "",
        "departments": [
            {
                "id": d.id,
                "name": d.name.get(locale),
                "location": d.location.get(locale) if d.location else "",
                "hours": d.hours.get(locale) if d.hours else "",
                "accepts_appointments": d.accepts_appointments,
            }
            for d in profile.departments
        ],
    }
