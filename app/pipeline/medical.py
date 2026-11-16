"""Medical answer path: rewrite -> retrieve -> abstain if not confident -> generate -> check -> release.

High-risk answers (GuardVerdict.high_risk_medical, classifier unavailable, sticky risk) are generated off-screen,
checked (output checks + numeric grounding + groundedness) and released as one AnswerEvent(mode="verified").
Low-risk answers stream as sentence-buffered DeltaEvents that already passed the inline checks, then a final
AnswerEvent (replaces_stream=True when post-checks changed the text). Degrade ladder: (rerank skipping happens
inside the retriever) -> ANSWER_FALLBACK model -> static "busy" answer that still shows the emergency number.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing
from dataclasses import dataclass, replace

import structlog

from app.guardrails.groundedness import GroundednessVerifier
from app.guardrails.output_checks import CheckContext, check_answer, check_sentence
from app.guardrails.safety_config import SafetyConfig
from app.guardrails.sentences import Sentence, SentenceBuffer
from app.pipeline.citations import build_citations, needs_source_language_note
from app.pipeline.prompts import PromptSet, build_answer_prompt
from app.pipeline.record import TurnTrace
from app.pipeline.rewrite import QueryRewriter
from app.pipeline.texts import Texts
from core.errors import AusculaError, UpstreamBlocked, UpstreamError
from core.models import ModelRole
from core.ports import GenerationRequest, LLMProvider, Retriever
from core.schemas.chat import GuardVerdict, Intent, RetrievalResult, RetrievedPassage
from core.schemas.events import AnswerEvent, ChatEvent, DeltaEvent, NoticeEvent, StatusEvent
from core.schemas.hospital import HospitalProfile

log = structlog.get_logger(__name__)


class _Leak(Exception):
    """A canary token or the system prompt appeared in the model output."""


@dataclass(frozen=True)
class MedicalTurn:
    message: str
    history: tuple[str, ...]
    verdict: GuardVerdict
    high_risk: bool
    profile: HospitalProfile | None


@dataclass(frozen=True)
class _Final:
    text: str
    cited: tuple[int, ...]
    verified: bool
    abstain: str | None = None  # reason when the answer must abstain
    blocked: bool = False


class MedicalResponder:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        retriever: Retriever | None,
        rewriter: QueryRewriter,
        verifier: GroundednessVerifier,
        prompts: PromptSet,
        texts: Texts,
        safety: SafetyConfig,
        policy_ngrams: frozenset[tuple[str, ...]],
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._rewriter = rewriter
        self._verifier = verifier
        self._prompts = prompts
        self._texts = texts
        self._cfg = safety
        self._policy_ngrams = policy_ngrams

    # ---- entry point -----------------------------------------------------------------------------
    async def respond(self, turn: MedicalTurn, trace: TurnTrace) -> AsyncIterator[ChatEvent]:
        lang, intent = turn.verdict.language, turn.verdict.intent
        if self._retriever is None:
            trace.degrade("retrieval_unavailable")
            yield self._notice("degraded", lang, turn.profile)
            yield self._template("retrieval_unavailable", turn, "template")
            return
        yield StatusEvent(stage="searching")
        result, standalone = await self._retrieve(turn, trace)
        if result is None:
            yield self._notice("degraded", lang, turn.profile)
            yield self._template("retrieval_unavailable", turn, "template")
            return
        if not result.confident or not result.passages:
            trace.update(mode="abstain")
            yield self._abstain(turn)
            return
        passages = result.passages
        ctx = CheckContext(
            canary=self._prompts.canary,
            policy_ngrams=self._policy_ngrams,
            allowed_numbers=turn.profile.allowed_numbers() if turn.profile else frozenset(),
            passages=tuple(p.text for p in passages),
        )
        request = GenerationRequest(
            role=ModelRole.ANSWER,
            system=self._prompts.system_prompt,
            prompt=build_answer_prompt(message=turn.message, standalone=standalone, language=lang, passages=passages),
        )
        flow = self._verified if turn.high_risk else self._streamed
        async for ev in flow(turn, trace, request, ctx, passages):
            yield ev
        log.debug("medical_answer_done", intent=intent.value)

    # ---- retrieval ---------------------------------------------------------------------------------
    async def _retrieve(self, turn: MedicalTurn, trace: TurnTrace) -> tuple[RetrievalResult | None, str]:
        v = turn.verdict
        outcome = await self._rewriter.rewrite(turn.message, turn.history, v.language, v.intent)
        if outcome.error:
            trace.degrade("rewrite_failed")
        standalone = outcome.query.standalone_query
        trace.mark("rewrite")
        if self._retriever is None:
            return None, standalone
        try:
            result = await asyncio.wait_for(self._retriever.retrieve(outcome.query), self._cfg.timeouts.retrieval_s)
        except (AusculaError, TimeoutError, OSError) as exc:
            log.warning("retrieval_failed", error=type(exc).__name__)
            trace.degrade("retrieval_failed")
            return None, standalone
        trace.mark("retrieval")
        corpus = result.corpus_version or trace.record.release.corpus_version
        trace.update(release=trace.record.release.model_copy(update={"corpus_version": corpus}))
        return result, standalone

    # ---- generation --------------------------------------------------------------------------------
    async def _generate_text(self, request: GenerationRequest, trace: TurnTrace) -> str:
        """ANSWER, then ANSWER_FALLBACK on any upstream error except a block. Raises UpstreamError if both fail."""
        try:
            return (await self._llm.generate(request)).text
        except UpstreamBlocked:
            raise
        except UpstreamError as exc:
            if request.role is ModelRole.ANSWER_FALLBACK:
                raise
            log.warning("answer_failed_using_fallback", error=exc.code)
            trace.degrade("fallback_model")
        return (await self._llm.generate(replace(request, role=ModelRole.ANSWER_FALLBACK))).text

    async def _verified(
        self,
        turn: MedicalTurn,
        trace: TurnTrace,
        request: GenerationRequest,
        ctx: CheckContext,
        passages: Sequence[RetrievedPassage],
    ) -> AsyncIterator[ChatEvent]:
        yield StatusEvent(stage="verifying")
        try:
            text = await self._generate_text(request, trace)
        except UpstreamBlocked as exc:
            yield self._blocked(turn, trace, exc, replaces=False)
            return
        except UpstreamError:
            yield self._busy(turn, trace, replaces=False)
            return
        trace.mark("generation")
        checks = check_answer(text, ctx)
        self._record_violations(trace, checks.violations)
        if checks.fatal:
            yield self._leak(turn, trace, replaces=False)
            return
        kept = [Sentence(c.text, s.separator) for s, c in checks.sentences if c.kept]
        final = await self._finalize(kept, [c.citations for _, c in checks.sentences if c.kept], passages)
        trace.mark("verify")
        for ev in self._release(turn, trace, final, passages, mode="verified", streamed_text=None):
            yield ev

    async def _streamed(
        self,
        turn: MedicalTurn,
        trace: TurnTrace,
        request: GenerationRequest,
        ctx: CheckContext,
        passages: Sequence[RetrievedPassage],
    ) -> AsyncIterator[ChatEvent]:
        yield StatusEvent(stage="writing")
        emitted: list[Sentence] = []
        cites: list[tuple[int, ...]] = []
        try:
            async for delta in self._stream_deltas(request, ctx, emitted, cites, trace):
                yield delta
        except _Leak:
            yield self._leak(turn, trace, replaces=bool(emitted))
            return
        except UpstreamBlocked as exc:
            yield self._blocked(turn, trace, exc, replaces=bool(emitted))
            return
        except UpstreamError as exc:
            log.warning("stream_failed", error=exc.code, emitted=len(emitted))
            trace.degrade("fallback_model")
            async for ev in self._after_stream_failure(turn, trace, request, ctx, passages, bool(emitted)):
                yield ev
            return
        trace.mark("generation")
        streamed_text = _join(emitted)
        final = await self._finalize(emitted, cites, passages)
        trace.mark("verify")
        for ev in self._release(turn, trace, final, passages, mode="streamed", streamed_text=streamed_text):
            yield ev

    async def _stream_deltas(
        self,
        request: GenerationRequest,
        ctx: CheckContext,
        emitted: list[Sentence],
        cites: list[tuple[int, ...]],
        trace: TurnTrace,
    ) -> AsyncIterator[DeltaEvent]:
        buffer = SentenceBuffer()
        async with aclosing(self._llm.stream(request)) as stream:
            async for chunk in stream:
                for sentence in buffer.feed(chunk.text):
                    delta = self._admit(sentence, ctx, emitted, cites, trace)
                    if delta is not None:
                        yield delta
        for sentence in buffer.flush():
            delta = self._admit(sentence, ctx, emitted, cites, trace)
            if delta is not None:
                yield delta

    def _admit(
        self,
        sentence: Sentence,
        ctx: CheckContext,
        emitted: list[Sentence],
        cites: list[tuple[int, ...]],
        trace: TurnTrace,
    ) -> DeltaEvent | None:
        c = check_sentence(sentence.text, ctx)
        self._record_violations(trace, c.violations)
        if c.fatal:
            raise _Leak
        if not c.kept:
            return None
        prefix = emitted[-1].separator if emitted else ""
        emitted.append(Sentence(c.text, sentence.separator or " "))
        cites.append(c.citations)
        trace.mark("first_delta")
        return DeltaEvent(text=prefix + c.text)

    async def _after_stream_failure(
        self,
        turn: MedicalTurn,
        trace: TurnTrace,
        request: GenerationRequest,
        ctx: CheckContext,
        passages: Sequence[RetrievedPassage],
        replaces: bool,
    ) -> AsyncIterator[ChatEvent]:
        fallback = replace(request, role=ModelRole.ANSWER_FALLBACK)
        if not replaces:
            async for ev in self._verified(turn, trace, fallback, ctx, passages):
                yield ev
            return
        try:
            text = (await self._llm.generate(fallback)).text
        except UpstreamBlocked as exc:
            yield self._blocked(turn, trace, exc, replaces=True)
            return
        except UpstreamError:
            yield self._busy(turn, trace, replaces=True)
            return
        checks = check_answer(text, ctx)
        if checks.fatal:
            yield self._leak(turn, trace, replaces=True)
            return
        kept = [Sentence(c.text, s.separator) for s, c in checks.sentences if c.kept]
        final = await self._finalize(kept, [c.citations for _, c in checks.sentences if c.kept], passages)
        for ev in self._release(turn, trace, final, passages, mode="streamed", streamed_text=""):
            yield ev

    # ---- post-checks -----------------------------------------------------------------------------
    async def _finalize(
        self, kept: list[Sentence], cites: Sequence[tuple[int, ...]], passages: Sequence[RetrievedPassage]
    ) -> _Final:
        if not kept:
            return _Final("", (), False, abstain="empty_after_checks")
        if not any(cites):
            return _Final("", (), False, abstain="no_citation")
        result = await self._verifier.verify([s.text for s in kept], [p.text for p in passages])
        if result.blocked:
            return _Final("", (), False, blocked=True)
        if not result.available:
            return _Final(_join(kept), _flat(cites), verified=False)
        survivors = [(s, c) for s, c, ok in zip(kept, cites, result.supported, strict=True) if ok]
        gcfg = self._cfg.groundedness
        if len(survivors) / len(kept) < gcfg.min_kept_ratio or not any(c for _, c in survivors):
            return _Final("", (), False, abstain="unsupported")
        return _Final(_join([s for s, _ in survivors]), _flat([c for _, c in survivors]), verified=True)

    def _release(
        self,
        turn: MedicalTurn,
        trace: TurnTrace,
        final: _Final,
        passages: Sequence[RetrievedPassage],
        *,
        mode: str,
        streamed_text: str | None,
    ) -> list[ChatEvent]:
        replaces = streamed_text is not None and final.text != streamed_text
        if final.blocked:
            return [self._blocked(turn, trace, UpstreamBlocked(reason="verify", stage="prompt"), replaces=replaces)]
        if final.abstain or (mode == "verified" and not final.verified):
            trace.audit("abstain", reason=final.abstain or "verifier_unavailable")
            trace.update(mode="abstain")
            return [self._abstain(turn, replaces=streamed_text is not None)]
        citations = build_citations(passages, final.cited)
        note = needs_source_language_note(citations, turn.verdict.language)
        trace.update(mode=mode, verified=final.verified)
        events: list[ChatEvent] = []
        if note:
            events.append(self._notice("source_language", turn.verdict.language, turn.profile))
        events.append(
            AnswerEvent(
                text=final.text,
                citations=citations,
                intent=turn.verdict.intent,
                mode=mode,  # type: ignore[arg-type]
                verified=final.verified,
                replaces_stream=replaces,
                source_language_note=note,
                show_seek_care=True,
            )
        )
        return events

    # ---- fixed answers ---------------------------------------------------------------------------
    def _template(self, key: str, turn: MedicalTurn, mode: str, *, replaces: bool = False) -> AnswerEvent:
        lang = turn.verdict.language
        return AnswerEvent(
            text=self._texts.response(key, lang, turn.profile),
            intent=turn.verdict.intent,
            mode=mode,  # type: ignore[arg-type]
            verified=False,
            replaces_stream=replaces,
            show_seek_care=key in ("abstain", "retrieval_unavailable", "busy"),
        )

    def _abstain(self, turn: MedicalTurn, *, replaces: bool = False) -> AnswerEvent:
        lang = turn.verdict.language
        text = self._texts.response("abstain", lang, turn.profile)
        if turn.profile is not None:
            text += " " + self._texts.response("abstain_handoff", lang, turn.profile)
        return AnswerEvent(
            text=text,
            intent=turn.verdict.intent,
            mode="abstain",
            verified=False,
            replaces_stream=replaces,
            show_seek_care=True,
        )

    def _busy(self, turn: MedicalTurn, trace: TurnTrace, *, replaces: bool) -> AnswerEvent:
        trace.degrade("busy")
        trace.update(mode="template")
        return self._template("busy", turn, "template", replaces=replaces)

    def _blocked(self, turn: MedicalTurn, trace: TurnTrace, exc: UpstreamBlocked, *, replaces: bool) -> AnswerEvent:
        trace.audit("upstream_blocked", stage=exc.stage, reason=exc.reason[:40])
        trace.update(mode="refusal")
        return self._template("refusal_blocked", turn, "refusal", replaces=replaces)

    def _leak(self, turn: MedicalTurn, trace: TurnTrace, *, replaces: bool) -> AnswerEvent:
        log.error("output_leak_detected")
        trace.audit("canary_or_prompt_leak")
        trace.update(mode="refusal")
        return self._template("refusal_injection", turn, "refusal", replaces=replaces)

    def _notice(self, code: str, lang: str, profile: HospitalProfile | None) -> NoticeEvent:
        return NoticeEvent(code=code, message=self._texts.notice(code, lang, profile))  # type: ignore[arg-type]

    @staticmethod
    def _record_violations(trace: TurnTrace, violations: Sequence[str]) -> None:
        for v in dict.fromkeys(violations):
            trace.audit("output_violation", category=v)


def _join(sentences: Sequence[Sentence]) -> str:
    return "".join(s.text + s.separator for s in sentences).strip()


def _flat(cites: Sequence[tuple[int, ...]]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(n for c in cites for n in c))


__all__ = ["Intent", "MedicalResponder", "MedicalTurn"]
