"""POST /api/v1/appointments and POST /api/v1/feedback. Neither payload is ever sent to the language model.

Appointment requests are validated against the verified hospital profile (only departments that accept
appointment requests) and stored for staff with a 30-day retention, together with their audit event in one
transaction (review P15). Feedback comments are sanitised and redacted (e-mails, phone numbers, IDs, names)
before storage. Both are capped per session, per client per day and globally per day (review S7).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import authenticate, get_container
from app.api.errors import request_locale
from app.api.schemas import AppointmentBody, AppointmentCreated, FeedbackBody
from app.guardrails.pii import redact
from app.pipeline.forms import bookable_departments
from app.storage.repositories import AppointmentInput
from core.errors import DependencyUnavailable, InvalidInput, NotFound
from core.text import sanitize

router = APIRouter()


@router.post("/appointments", status_code=201)
async def create_appointment(body: AppointmentBody, request: Request) -> AppointmentCreated:
    c = get_container(request)
    auth = await authenticate(request, c)
    profile = c.profile()
    if profile is None:
        raise NotFound("appointment requests are not available")
    if body.department_id not in bookable_departments(profile):
        raise InvalidInput("unknown department", detail={"field": "department_id"})
    await c.rate.check_appointment(auth.session.session_id, auth.ip)
    data = AppointmentInput(
        session_id=auth.session.session_id,
        department_id=body.department_id,
        full_name=body.full_name,
        phone=body.phone,
        email=body.email,
        preferred_dates=body.preferred_dates,
        reason=body.reason,
    )
    try:
        code = await c.storage.appointments.create(data, audit={"department": body.department_id})
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database unavailable") from exc
    locale = request_locale(request) if "locale" in request.query_params else auth.session.locale
    message = c.texts.response("appointment_confirmed", locale, profile, request_id=code)
    return AppointmentCreated(request_id=code, message=message)


@router.post("/feedback", status_code=204)
async def create_feedback(body: FeedbackBody, request: Request) -> Response:
    c = get_container(request)
    auth = await authenticate(request, c)
    sid, turn_id = auth.session.session_id, str(body.turn_id)
    try:
        owned = c.registry.owns(turn_id, sid) or await c.storage.turns.belongs_to(turn_id, sid)
        if not owned:
            raise NotFound("unknown turn")
        await c.rate.check_feedback(sid, auth.ip)
        comment = redact(sanitize(body.comment).text, today=c.today()).text if body.comment else None
        await c.storage.feedback.add(
            session_id=sid, turn_id=turn_id, rating=body.rating, reason=body.reason, comment=comment or None
        )
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database unavailable") from exc
    return Response(status_code=204)
