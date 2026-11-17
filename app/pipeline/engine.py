"""Turn orchestrator: emits core.schemas.events in the order the SSE contract requires.

  meta -> [safety ...] -> [notice(demo)] -> status(checking) -> [safety ...] -> route -> answer path -> done

Safety events come from the deterministic precheck BEFORE any model call, so the emergency and self-harm
templates need no model at all (they return in milliseconds even when every model call fails). Emergency
and self-harm turns carry NO further medical content. Injection / harmful / abusive turns get a refusal
and a strike; 3 strikes lock the session.

Session state changes only through atomic SessionStore.apply deltas: the turn count, the history window, the
precheck's sticky risks and its strike are saved before the guard call, so a cancelled turn never loses a
safety decision (review C13), and concurrent turns or workers never overwrite each other (P2/S5).

Every turn runs under a deadline (review P5): past it, the answer becomes the "busy" template. Any failure
after streamed text first sends a replacing "busy" answer, so unverified deltas never stay on screen (C15).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from functools import partial
from typing import cast

import structlog

from app.guardrails.ingress import IngressResult
from app.guardrails.intent_rules import heuristic_intent
from app.guardrails.router import GuardRouter, Precheck, RouteResult, RouterInput
from app.guardrails.safety_config import SAFETY_KINDS, STRIKE_KINDS
from app.hospital.frontdesk import answer_front_desk, hospital_keywords
from app.hospital.profile import ProfileState
from app.pipeline.forms import appointment_form
from app.pipeline.heuristics import fallback_language, mentions_population
from app.pipeline.medical import MedicalResponder, MedicalTurn
from app.pipeline.record import TurnTrace
from app.pipeline.session import SessionState, SessionStore, SessionUpdate
from app.pipeline.texts import Texts, contacts_for
from core.config import Settings
from core.errors import AusculaError
from core.schemas.chat import GuardVerdict, Intent, Locale, RiskKind
from core.schemas.events import (
    AnswerEvent,
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    MetaEvent,
    NoticeEvent,
    ReleaseInfo,
    SafetyEvent,
    StatusEvent,
)
from core.schemas.hospital import HospitalProfile

log = structlog.get_logger(__name__)
SAFETY_ORDER: tuple[RiskKind, ...] = (
    RiskKind.EMERGENCY,
    RiskKind.SELF_HARM,
    RiskKind.HARM_TO_OTHERS,
    RiskKind.ABUSE_DISCLOSURE,
)
STRIKE_TEMPLATES: tuple[tuple[RiskKind, str], ...] = (
    (RiskKind.HARMFUL_REQUEST, "refusal_harmful"),
    (RiskKind.INJECTION, "refusal_injection"),
    (RiskKind.ABUSIVE_USER, "refusal_abusive"),
)
MEDICAL_INTENTS = frozenset({Intent.MEDICAL_INFO, Intent.MEDICATION, Intent.SYMPTOM_INFO})
HIGH_RISK_HEURISTIC_INTENTS = frozenset({Intent.MEDICATION, Intent.SYMPTOM_INFO})
TEMPLATE_INTENTS = {Intent.SMALLTALK: "smalltalk", Intent.META: "meta", Intent.OUT_OF_SCOPE: "out_of_scope"}
SESSION_LIMIT_NOTICE_AT = 3
TURN_DEADLINE_S = 45.0  # review P5: retries + fallback must not hold an admission slot for minutes
HISTORY_WINDOW_MAX = 3  # review S17: the router and the rewriter never use more than 3 earlier user turns


@dataclass(frozen=True)
class TurnRequest:
    turn_id: str
    client_turn_id: str
    session: SessionState
    message: IngressResult
    locale: Locale
    precheck: Precheck


@dataclass(frozen=True)
class _Ctx:
    req: TurnRequest
    profile: HospitalProfile | None
    trace: TurnTrace


@dataclass
class _Seen:
    """What the turn has sent so far (decides how a failure or the deadline ends it)."""

    streamed: bool = False
    answered: bool = False

    def note(self, event: ChatEvent) -> None:
        self.streamed = self.streamed or event.type == "delta"
        self.answered = self.answered or event.type == "answer"


@dataclass(frozen=True)
class _Strikes:
    pre: bool  # the precheck already counted this turn's strike
    to_lock: int


@dataclass(frozen=True)
class _Turn:
    session: SessionState
    strikes: _Strikes


class TurnEngine:
    def __init__(
        self,
        *,
        router: GuardRouter,
        medical: MedicalResponder,
        texts: Texts,
        profile_state: ProfileState,
        sessions: SessionStore,
        settings: Settings,
        release: ReleaseInfo,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
        deadline_s: float = TURN_DEADLINE_S,
    ) -> None:
        self._router = router
        self._medical = medical
        self._texts = texts
        self._profiles = profile_state
        self._sessions = sessions
        self._settings = settings
        self._release = release
        self._today = today
        self._deadline_s = deadline_s
        self._window = min(settings.history_window_turns, HISTORY_WINDOW_MAX)

    @property
    def release(self) -> ReleaseInfo:
        return self._release

    @property
    def texts(self) -> Texts:
        return self._texts

    @property
    def safety_kinds_without_model(self) -> frozenset[RiskKind]:
        """Precheck kinds whose turn is answered from templates only (no model call can happen)."""
        return self._router.config.block_medical_after

    def precheck(self, message: IngressResult) -> Precheck:
        return self._router.precheck(message.text, message.sanitize_flags)

    async def run(self, req: TurnRequest, trace: TurnTrace) -> AsyncGenerator[ChatEvent, None]:
        ctx = _Ctx(req=req, profile=self._profiles.active(self._today()), trace=trace)
        yield MetaEvent(
            turn_id=req.turn_id,
            session_id=req.session.session_id,
            locale=req.locale,
            demo_mode=self._settings.demo_mode,
            release=trace.record.release,
        )
        trace.mark("meta")
        seen = _Seen()
        deadline = asyncio.timeout(self._deadline_s)
        try:
            async with deadline:
                async for ev in self._body(ctx):
                    seen.note(ev)
                    yield ev
        except Exception as exc:
            if isinstance(exc, TimeoutError) and deadline.expired():
                log.warning("turn_deadline_exceeded", turn_id=req.turn_id, deadline_s=self._deadline_s)
                trace.degrade("deadline")
                if not seen.answered:
                    yield self.busy_answer(req, trace, replaces=seen.streamed)
            else:
                if seen.streamed and not seen.answered:
                    yield self.busy_answer(req, trace, replaces=True)
                yield self._error_event(exc, req, trace)
        yield DoneEvent(turn_id=req.turn_id, turns_left=await self._turns_left(req))

    def _error_event(self, exc: Exception, req: TurnRequest, trace: TurnTrace) -> ErrorEvent:
        code = exc.code if isinstance(exc, AusculaError) else "internal_error"
        log.error("turn_failed", turn_id=req.turn_id, error=type(exc).__name__, code=code)
        trace.update(error_code=code)
        retry = exc.detail.get("retry_after_s") if isinstance(exc, AusculaError) else None
        return ErrorEvent(
            code=code,
            message=self._texts.error(code, req.locale),
            retry_after_s=float(retry) if isinstance(retry, (int, float)) else None,
        )

    def busy_answer(self, req: TurnRequest, trace: TurnTrace, *, replaces: bool) -> AnswerEvent:
        """The fixed "busy" answer that ends a turn which could not finish (deadline, failure after deltas)."""
        recorded = trace.record.language
        lang = cast("Locale", recorded) if recorded in ("en", "fr", "ar") else req.locale
        intent = Intent(trace.record.intent) if trace.record.intent else heuristic_intent(req.message.text)
        trace.degrade("busy")
        trace.update(mode="template", verified=False)
        return AnswerEvent(
            text=self._texts.response("busy", lang, self._profiles.active(self._today())),
            intent=intent,
            mode="template",
            verified=False,
            replaces_stream=replaces,
            show_seek_care=True,
            language=lang,
        )

    async def _turns_left(self, req: TurnRequest) -> int:
        try:
            session = await self._sessions.get(req.session.session_id) or req.session
        except Exception as exc:
            log.warning("session_reload_failed", error=type(exc).__name__)
            session = req.session.with_turn("", window=0)
        return max(0, self._settings.max_turns_per_session - session.turns_used)

    async def _save(self, session: SessionState, update: SessionUpdate) -> SessionState:
        """Apply one atomic delta; the returned state includes concurrent updates by other turns."""
        if update.is_empty:
            return session
        saved = await self._sessions.apply(session, update)
        return saved if saved is not None else session.applied(update)

    # ---- body ------------------------------------------------------------------------------------
    async def _body(self, ctx: _Ctx) -> AsyncIterator[ChatEvent]:
        req, trace = ctx.req, ctx.trace
        lang = req.locale
        pre_kinds = req.precheck.safety_kinds
        pre_strike = bool(frozenset(s.kind for s in req.precheck.signals) & STRIKE_KINDS)
        for ev in self._safety_events(pre_kinds, ctx, lang):  # life-critical text first, right after meta
            yield ev
        if self._settings.demo_mode and req.session.turns_used == 0:
            yield NoticeEvent(code="demo_mode", message=self._texts.notice("demo_mode", lang, ctx.profile))
        trace.update(
            risk_kinds=_names(s.kind for s in req.precheck.signals), redactions=req.message.redaction_total
        )
        strikes = _Strikes(pre=pre_strike, to_lock=self._router.config.strikes_to_lock)
        session = await self._save(  # before any model call: a cancel can no longer lose it (C13)
            req.session,
            SessionUpdate(
                turn_text=req.message.text,
                window=self._window,
                risks=pre_kinds,
                strike=pre_strike,
                strikes_to_lock=strikes.to_lock,
            ),
        )
        if pre_strike:
            trace.audit("strike", count=session.strikes, kinds="precheck")
        if pre_kinds & self._router.config.block_medical_after or session.locked:
            yield self._closing_answer(ctx, pre_kinds, heuristic_intent(req.message.text), lang)
            return
        yield StatusEvent(stage="checking")
        route = await self._route(ctx)
        async for event in self._after_route(ctx, _Turn(session, strikes), route, pre_kinds):
            yield event

    async def _route(self, ctx: _Ctx) -> RouteResult:
        req = ctx.req
        inp = RouterInput(
            text=req.message.text,
            history=req.session.user_history(),
            locale_hint=req.locale,
            sticky=req.session.sticky_risks,
            hospital_keywords=hospital_keywords(ctx.profile),
        )
        route = await self._router.route(inp, req.precheck)
        ctx.trace.mark("route")
        v = route.verdict
        if not v.classifier_available:
            ctx.trace.degrade("classifier_unavailable")
            lang = fallback_language(v.language, req.message.text, req.locale)
            if lang != v.language:
                v = v.model_copy(update={"language": lang})
                route = replace(route, verdict=v)
        ctx.trace.update(
            intent=v.intent.value,
            language=v.language,
            classifier=route.classifier,
            risk_kinds=_names(s.kind for s in route.current),
        )
        return route

    async def _after_route(
        self, ctx: _Ctx, turn: _Turn, route: RouteResult, pre_kinds: frozenset[RiskKind]
    ) -> AsyncIterator[ChatEvent]:
        v = route.verdict
        lang = v.language
        current = route.current_kinds()
        safety = current & SAFETY_KINDS
        for ev in self._safety_events(safety - pre_kinds, ctx, lang):
            yield ev
        session = await self._save(turn.session, SessionUpdate(risks=safety - turn.session.sticky_risks))
        if safety & self._router.config.block_medical_after:
            yield self._closing_answer(ctx, safety, v.intent, lang)
            return
        if route.blocked:
            # a provider block on the guard input: sticky risk, so later answers are verify-then-release (C8)
            await self._save(session, SessionUpdate(risks=current & STRIKE_KINDS))
            ctx.trace.audit("upstream_blocked", stage="guard")
            yield self._fixed("refusal_blocked", v.intent, lang, ctx, mode="refusal")
            return
        if current & STRIKE_KINDS:
            yield await self._strike(ctx, session, turn.strikes, current, v.intent, lang)
            return
        async for event in self._dispatch(ctx, session, v):
            yield event
        left = self._settings.max_turns_per_session - session.turns_used
        if 0 < left <= SESSION_LIMIT_NOTICE_AT:
            yield NoticeEvent(
                code="session_limit_near",
                message=self._texts.notice("session_limit_near", lang, ctx.profile, turns_left=left),
            )

    async def _strike(
        self,
        ctx: _Ctx,
        session: SessionState,
        strikes: _Strikes,
        current: frozenset[RiskKind],
        intent: Intent,
        lang: Locale,
    ) -> AnswerEvent:
        if not strikes.pre:  # the precheck did not count this turn's strike yet
            session = await self._save(session, SessionUpdate(strike=True, strikes_to_lock=strikes.to_lock))
            kinds = ",".join(sorted(k.value for k in current))
            ctx.trace.audit("strike", count=session.strikes, kinds=kinds)
        if session.locked:
            ctx.trace.audit("session_locked")
            return self._fixed("session_locked", intent, lang, ctx, mode="refusal")
        key = next(t for k, t in STRIKE_TEMPLATES if k in current)
        return self._fixed(key, intent, lang, ctx, mode="refusal")

    def _high_risk(self, ctx: _Ctx, session: SessionState, v: GuardVerdict) -> bool:
        """Verify-then-release: model verdict OR deterministic intent / population signals (review C6)."""
        text = ctx.req.message.text
        return (
            v.high_risk_medical
            or not v.classifier_available
            or bool(session.sticky_risks)
            or heuristic_intent(text, hospital_keywords(ctx.profile)) in HIGH_RISK_HEURISTIC_INTENTS
            or mentions_population(text)
        )

    async def _dispatch(self, ctx: _Ctx, session: SessionState, v: GuardVerdict) -> AsyncIterator[ChatEvent]:
        lang = v.language
        if v.intent in MEDICAL_INTENTS:
            turn = MedicalTurn(
                message=ctx.req.message.text,
                history=ctx.req.session.user_history(),
                verdict=v,
                high_risk=self._high_risk(ctx, session, v),
                profile=ctx.profile,
                on_input_blocked=partial(self._sticky, session),
            )
            async for ev in self._medical.respond(turn, ctx.trace):
                yield ev
            return
        if v.intent is Intent.HOSPITAL_ADMIN:
            yield self._front_desk(ctx, v.intent, lang)
            return
        if v.intent is Intent.APPOINTMENT:
            for ev in self._appointment(ctx, lang):
                yield ev
            return
        yield self._fixed(TEMPLATE_INTENTS[v.intent], v.intent, lang, ctx, mode="template")

    async def _sticky(self, session: SessionState, kind: RiskKind) -> None:
        await self._save(session, SessionUpdate(risks=frozenset({kind})))

    # ---- fixed answers ---------------------------------------------------------------------------
    def _safety_events(self, kinds: Iterable[RiskKind], ctx: _Ctx, lang: Locale) -> list[SafetyEvent]:
        events: list[SafetyEvent] = []
        wanted = set(kinds)
        for kind in SAFETY_ORDER:
            if kind not in wanted:
                continue
            t = self._texts.safety[kind.value]
            events.append(
                SafetyEvent(
                    kind=kind.value,  # type: ignore[arg-type]
                    template_id=t.template_id,
                    title=self._texts.render_safety(t.title, lang, ctx.profile),
                    message=self._texts.render_safety(t.message, lang, ctx.profile),
                    contacts=contacts_for(t.contacts, ctx.profile, lang),
                    language=lang,
                )
            )
            ctx.trace.audit("safety_template", kind=kind.value, template_id=t.template_id)
        if events:
            ctx.trace.mark("safety")
        return events

    def _closing_answer(
        self, ctx: _Ctx, kinds: frozenset[RiskKind], intent: Intent, lang: Locale
    ) -> AnswerEvent:
        first = next((k for k in SAFETY_ORDER if k in kinds), None)
        if first is None:  # locked session without a safety signal
            ctx.trace.audit("session_locked")
            return self._fixed("session_locked", intent, lang, ctx, mode="refusal")
        ctx.trace.update(mode="template", intent=ctx.trace.record.intent or intent.value)
        return AnswerEvent(
            text=self._texts.followup(first.value, lang, ctx.profile),
            intent=intent,
            mode="template",
            verified=False,
            language=lang,
        )

    def _fixed(self, key: str, intent: Intent, lang: Locale, ctx: _Ctx, *, mode: str) -> AnswerEvent:
        ctx.trace.update(mode=mode, intent=ctx.trace.record.intent or intent.value)
        if mode == "refusal":
            ctx.trace.audit("refusal", template=key)
        return AnswerEvent(
            text=self._texts.response(key, lang, ctx.profile),
            intent=intent,
            mode=mode,  # type: ignore[arg-type]
            verified=False,
            language=lang,
        )

    def _front_desk(self, ctx: _Ctx, intent: Intent, lang: Locale) -> AnswerEvent:
        if ctx.profile is None:
            return self._fixed("frontdesk_unavailable", intent, lang, ctx, mode="template")
        found = answer_front_desk(ctx.req.message.text, ctx.profile, self._texts, lang)
        if found is None:
            return self._fixed("frontdesk_no_match", intent, lang, ctx, mode="template")
        ctx.trace.update(mode="template")
        ctx.trace.audit("front_desk", matched=",".join(found.matched)[:200])
        return AnswerEvent(text=found.text, intent=intent, mode="template", verified=False, language=lang)

    def _appointment(self, ctx: _Ctx, lang: Locale) -> list[ChatEvent]:
        form = appointment_form(ctx.profile, self._texts, lang)
        if form is None:
            return [self._fixed("appointment_unavailable", Intent.APPOINTMENT, lang, ctx, mode="template")]
        intro = self._fixed("appointment_intro", Intent.APPOINTMENT, lang, ctx, mode="template")
        return [intro, form]


def _names(kinds: Iterable[RiskKind]) -> tuple[str, ...]:
    return tuple(sorted({k.value for k in kinds}))
