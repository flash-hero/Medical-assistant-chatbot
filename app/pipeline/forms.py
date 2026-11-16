"""Appointment request form (FormEvent). Its data goes to hospital staff via POST /api/v1/appointments and is
never sent to the language model."""

from __future__ import annotations

from app.pipeline.texts import Texts, form_label
from core.schemas.events import FormEvent, FormField
from core.schemas.hospital import HospitalProfile

REASON_MAX = 500
NAME_MAX = 120
DATES_MAX = 300


def bookable_departments(profile: HospitalProfile | None) -> tuple[str, ...]:
    if profile is None:
        return ()
    return tuple(d.id for d in profile.departments if d.accepts_appointments)


def appointment_form(profile: HospitalProfile | None, texts: Texts, locale: str) -> FormEvent | None:
    """The form, or None when no profile is loaded or no department accepts appointment requests.

    `department_id` options are department ids; the UI shows their names from GET /api/v1/hospital.
    `consent` is a one-option select because FormField has no checkbox kind (see the contract change request).
    """
    departments = bookable_departments(profile)
    if not departments:
        return None

    def label(name: str) -> str:
        return form_label(texts, ("fields", name), locale)

    fields = (
        FormField(name="full_name", label=label("full_name"), kind="text", required=True, max_length=NAME_MAX),
        FormField(name="phone", label=label("phone"), kind="tel", required=True, max_length=32),
        FormField(name="email", label=label("email"), kind="email", required=False, max_length=254),
        FormField(name="department_id", label=label("department_id"), kind="select", required=True, options=departments),
        FormField(
            name="preferred_dates", label=label("preferred_dates"), kind="textarea", required=True, max_length=DATES_MAX
        ),
        FormField(name="reason", label=label("reason"), kind="textarea", required=False, max_length=REASON_MAX),
        FormField(name="consent", label=label("consent"), kind="select", required=True, options=("yes",)),
    )
    return FormEvent(
        form_id="appointment_request",
        title=form_label(texts, ("title",), locale),
        description=form_label(texts, ("description",), locale),
        fields=fields,
    )
