"""POST /api/v1/session and POST /api/v1/chat (SSE over POST).

The deterministic safety precheck runs FIRST, right after the token and the message length (review C9/P8).

Safety turns (precheck emergency / self-harm; answered from templates, no model call):
  safety bucket per client (429, generous) -> session state (401) -> idempotent replay -> stream.
  They bypass the kill switch, the ordinary rate limits, the turn budget, the one-turn-per-session lock (409),
  the per-client concurrency cap, the spend cap and the admission queue: the template is never delayed or
  refused by load, abuse controls or an operator pause.
Every other turn, in order (each failure is a JSON error, never a stream):
  kill switch (503) -> client / session rate limits (429) -> session state (401) -> idempotent replay
  -> session turn budget (429) -> one running turn per session (409) -> concurrent turns per client (429)
  -> [model-backed turns only] daily spend cap (503) -> admission slot (503 + Retry-After).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import anyio
from fastapi import APIRouter, Request
from sqlalchemy.exc import SQLAlchemyError

from app.api.container import Container
from app.api.deps import (
    bearer_token,
    client_ip,
    ensure_not_paused,
    ensure_spend_available,
    get_container,
    load_session,
)
from app.api.gate import TurnClaim
from app.api.schemas import ChatBody, SessionCreate, SessionCreated
from app.api.sse import SSEResponse
from app.api.tokens import TOKEN_LIFETIME
from app.api.turns import SlotGuard, TurnStream, replay_frames
from app.guardrails.ingress import IngressResult, process_ingress
from app.guardrails.router import Precheck
from app.hospital.public import public_hospital
from app.limits.rate import client_key
from app.pipeline.engine import TurnRequest
from app.pipeline.record import TurnRecord, TurnTrace
from app.pipeline.session import SessionState
from core.errors import DependencyUnavailable, InvalidInput, SessionExhausted

router = APIRouter()


@router.post("/session", status_code=201)
async def create_session(body: SessionCreate, request: Request) -> SessionCreated:
    c = get_container(request)
    await c.rate.check_session_create(client_ip(request, c.settings.trusted_proxy_count))
    now = datetime.now(UTC)
    expires = now + TOKEN_LIFETIME
    state = SessionState(session_id=str(uuid.uuid4()), locale=body.locale, created_at=now, expires_at=expires)
    try:
        await c.storage.sessions.create(state, demo_mode=c.settings.demo_mode)
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database unavailable") from exc
    await c.sessions.put(state)
    profile = c.profile()
    return SessionCreated(
        session_token=c.signer.issue(state.session_id, expires),
        session_id=state.session_id,
        expires_at=expires.isoformat(),
        turns_left=c.settings.max_turns_per_session,
        hospital=public_hospital(profile, body.locale) if profile is not None else None,
        demo_mode=c.settings.demo_mode,
    )


def _is_safety_turn(c: Container, precheck: Precheck) -> bool:
    return bool(precheck.safety_kinds & c.engine.safety_kinds_without_model)


@router.post("/chat")
async def chat(body: ChatBody, request: Request) -> SSEResponse:
    c = get_container(request)
    claims = c.signer.verify(bearer_token(request))
    ip = client_ip(request, c.settings.trusted_proxy_count)
    if len(body.message) > c.settings.max_message_chars:
        raise InvalidInput("message too long", detail={"max_chars": c.settings.max_message_chars})
    ingress = process_ingress(body.message, max_chars=c.settings.max_message_chars, today=c.today())
    precheck = await anyio.to_thread.run_sync(c.engine.precheck, ingress)
    turn = _Incoming(body, ingress, precheck, ip)
    if _is_safety_turn(c, precheck):
        return await _safety_turn(c, turn, claims.session_id)
    return await _model_turn(c, turn, claims.session_id)


@dataclass(frozen=True)
class _Incoming:
    body: ChatBody
    ingress: IngressResult
    precheck: Precheck
    ip: str

    @property
    def client_turn_id(self) -> str:
        return str(self.body.client_turn_id)


async def _safety_turn(c: Container, turn: _Incoming, session_id: str) -> SSEResponse:
    await c.rate.check_safety(turn.ip)
    session = await load_session(c, session_id)
    frames = await c.registry.replay(session.session_id, turn.client_turn_id)
    if frames is not None:
        return SSEResponse(replay_frames(frames))
    claim = TurnClaim(session.session_id, turn.client_turn_id, client_key(turn.ip), exclusive=False)
    await c.registry.begin(claim)
    stream = _turn_stream(c, turn, session, claim, slot=None)
    return SSEResponse(stream.frames(), on_close=stream.close)


async def _model_turn(c: Container, turn: _Incoming, session_id: str) -> SSEResponse:
    ensure_not_paused(c)
    await c.rate.check_ip(turn.ip)
    await c.rate.check_session(session_id)
    session = await load_session(c, session_id)
    frames = await c.registry.replay(session.session_id, turn.client_turn_id)
    if frames is not None:
        return SSEResponse(replay_frames(frames))
    if session.turns_used >= c.settings.max_turns_per_session:
        left_s = (session.expires_at - datetime.now(UTC)).total_seconds()
        raise SessionExhausted("turn budget used", detail={"retry_after_s": max(1.0, left_s)})
    claim = TurnClaim(session.session_id, turn.client_turn_id, client_key(turn.ip), exclusive=True)
    await c.registry.begin(claim)
    try:
        slot = None
        if not session.locked:  # a locked session is answered from a template: no model, no slot
            await ensure_spend_available(c)
            await c.admission.acquire()
            slot = SlotGuard(c.admission.release)
    except BaseException:
        await c.registry.finish(claim, "", None)  # give the claim back: the turn never started
        raise
    stream = _turn_stream(c, turn, session, claim, slot=slot)
    return SSEResponse(stream.frames(), on_close=stream.close)


def _turn_stream(
    c: Container, turn: _Incoming, session: SessionState, claim: TurnClaim, *, slot: SlotGuard | None
) -> TurnStream:
    turn_id = str(uuid.uuid4())
    request = TurnRequest(
        turn_id=turn_id,
        client_turn_id=turn.client_turn_id,
        session=session,
        message=turn.ingress,
        locale=turn.body.locale,
        precheck=turn.precheck,
    )
    trace = TurnTrace(
        TurnRecord(
            turn_id=turn_id,
            session_id=session.session_id,
            client_turn_id=turn.client_turn_id,
            release=c.release(),
        )
    )
    return TurnStream(
        engine=c.engine,
        request=request,
        trace=trace,
        gate=c.registry,
        claim=claim,
        persist=c.persist_turn,
        slot=slot,
        keepalive_s=c.keepalive_s,
        cancel_grace_s=c.cancel_grace_s,
    )
