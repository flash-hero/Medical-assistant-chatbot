"""Guard and router: deterministic signals (lexicon + injection heuristics) OR one GUARD decide call.

Final verdict = lexicon OR classifier OR upstream block. A provider block on the guard input is a risk signal,
never
a crash. When the decide call fails, a GUARD_FALLBACK JSON classifier runs; when both fail the verdict has
classifier_available=False and relies on deterministic signals and heuristics only.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import structlog

from app.guardrails.guard_classifier import ClassifierOutput, run_classifier
from app.guardrails.guard_prompts import GuardPrompts
from app.guardrails.injection import detect_injection
from app.guardrails.intent_rules import heuristic_intent, heuristic_language
from app.guardrails.lexicon import LexiconMatcher
from app.guardrails.safety_config import SAFETY_KINDS, SafetyConfig
from core.errors import UpstreamBlocked
from core.ports import LLMProvider
from core.schemas.chat import GuardVerdict, Intent, Locale, Population, RiskKind, Signal

log = structlog.get_logger(__name__)
MAX_HISTORY_TURNS = 3


@dataclass(frozen=True)
class Precheck:
    """Deterministic, model-free signals for one message (computed in a few milliseconds)."""

    signals: tuple[Signal, ...]
    lexicon_langs: frozenset[str] = frozenset()

    @property
    def safety_kinds(self) -> frozenset[RiskKind]:
        return frozenset(s.kind for s in self.signals if s.kind in SAFETY_KINDS)

    def has(self, kind: RiskKind) -> bool:
        return any(s.kind is kind for s in self.signals)


@dataclass(frozen=True)
class RouteResult:
    verdict: GuardVerdict
    current: tuple[Signal, ...]  # signals raised by THIS message (sticky ones excluded)
    blocked: bool = False
    classifier: str = "none"  # "decide" | "fallback" | "none"
    model_id: str | None = None
    error: str | None = None

    def current_kinds(self) -> frozenset[RiskKind]:
        return frozenset(s.kind for s in self.current)


@dataclass(frozen=True)
class RouterInput:
    text: str  # sanitised + redacted current message
    history: tuple[str, ...] = ()  # earlier user messages (sanitised + redacted), oldest first
    locale_hint: Locale = "en"
    sticky: frozenset[RiskKind] = frozenset()
    hospital_keywords: tuple[str, ...] = field(default=())


class GuardRouter:
    def __init__(
        self, llm: LLMProvider, lexicon: LexiconMatcher, prompts: GuardPrompts, config: SafetyConfig
    ) -> None:
        self._llm = llm
        self._lexicon = lexicon
        self._prompts = prompts
        self._cfg = config

    @property
    def config(self) -> SafetyConfig:
        return self._cfg

    def precheck(self, text: str, sanitize_flags: Iterable[str] = ()) -> Precheck:
        lex = self._lexicon.assess(text)  # one scan for both signals and languages
        signals = list(lex.signals)
        inj = detect_injection(text, smuggling_flags=sanitize_flags)
        if inj.flagged(self._cfg.injection_min_score):
            signals.append(inj.signal())
        return Precheck(signals=tuple(signals), lexicon_langs=lex.languages)

    async def route(self, inp: RouterInput, pre: Precheck) -> RouteResult:
        payload = classifier_input(self._prompts.preamble, inp.text, inp.history[-MAX_HISTORY_TURNS:])
        try:
            # asyncio.timeout, not wait_for: on Python 3.11 wait_for swallows an outer task.cancel() when the
            # classifier finishes in the same loop iteration, so a cancelled turn would keep running.
            async with asyncio.timeout(self._cfg.timeouts.router_s * 2):
                out = await run_classifier(self._llm, self._prompts, payload)
        except UpstreamBlocked as exc:
            return self._blocked_result(inp, pre, exc)
        except TimeoutError:
            out = None
        return self._combine(inp, pre, out)

    def _blocked_result(self, inp: RouterInput, pre: Precheck, exc: UpstreamBlocked) -> RouteResult:
        kind = RiskKind.INJECTION if exc.reason == "jailbreak" else RiskKind.HARMFUL_REQUEST
        block = Signal(kind=kind, source="upstream_block", score=1.0, detail=f"guard:{exc.reason}"[:60])
        log.info("guard_upstream_blocked", reason=exc.reason)
        base = self._combine(inp, pre, None)
        current = (*base.current, block)
        verdict = base.verdict.model_copy(update={"risks": (*base.verdict.risks, block)})
        return RouteResult(
            verdict=verdict, current=current, blocked=True, classifier="none", error="upstream_blocked"
        )

    def _combine(self, inp: RouterInput, pre: Precheck, out: ClassifierOutput | None) -> RouteResult:
        current = list(pre.signals)
        if out is not None:
            current.extend(self._classifier_signals(out, pre))
        sticky = tuple(
            Signal(kind=k, source="session_sticky", score=1.0)
            for k in sorted(inp.sticky - {s.kind for s in current}, key=lambda k: k.value)
        )
        intent, intent_conf = self._intent(inp, out)
        verdict = GuardVerdict(
            language=self._language(inp, pre, out),
            intent=intent,
            intent_confidence=intent_conf,
            risks=(*current, *sticky),
            populations=self._populations(out),
            classifier_available=out is not None,
        )
        return RouteResult(
            verdict=verdict,
            current=tuple(current),
            classifier=out.source if out else "none",
            model_id=out.model_id if out else None,
            error=None if out else "classifier_unavailable",
        )

    def _classifier_signals(self, out: ClassifierOutput, pre: Precheck) -> list[Signal]:
        signals: list[Signal] = []
        for kind, prob in out.risks.items():
            if prob >= self._cfg.threshold(kind) and not pre.has(kind):
                signals.append(
                    Signal(kind=kind, source="classifier", score=round(prob, 3), detail=out.source)
                )
        return signals

    def _intent(self, inp: RouterInput, out: ClassifierOutput | None) -> tuple[Intent, float]:
        if out is not None and out.intent_confidence >= self._cfg.intent_min_confidence:
            return out.intent, out.intent_confidence
        return heuristic_intent(inp.text, inp.hospital_keywords), 0.0

    def _language(self, inp: RouterInput, pre: Precheck, out: ClassifierOutput | None) -> Locale:
        if out is not None and out.language_confidence >= self._cfg.language_min_confidence:
            return out.language
        if pre.lexicon_langs & {"ar", "arabizi"}:
            return "ar"
        return heuristic_language(inp.text, inp.locale_hint)

    def _populations(self, out: ClassifierOutput | None) -> tuple[Population, ...]:
        if out is None:
            return ()
        return tuple(p for p, prob in out.populations.items() if prob >= self._cfg.population_threshold)


def _neutralise(text: str) -> str:
    return text.replace("<", "‹").replace(">", "›")


def classifier_input(preamble: str, current: str, history: Sequence[str]) -> str:
    """Flatten the current message and up to 3 earlier user turns into nonce-delimited data blocks."""
    nonce = secrets.token_hex(6)
    blocks = [
        f'<user_message role="earlier" n="{i}" nonce="{nonce}">\n{_neutralise(t)}\n'
        f'</user_message nonce="{nonce}">'
        for i, t in enumerate(history, 1)
    ]
    blocks.append(
        f'<user_message role="current" nonce="{nonce}">\n{_neutralise(current)}\n'
        f'</user_message nonce="{nonce}">'
    )
    return preamble + "\n\n" + "\n".join(blocks)


def risk_kinds(signals: Iterable[Signal]) -> frozenset[RiskKind]:
    return frozenset(s.kind for s in signals)


def strongest(signals: Iterable[Signal]) -> Mapping[RiskKind, Signal]:
    best: dict[RiskKind, Signal] = {}
    for s in signals:
        if s.kind not in best or s.score > best[s.kind].score:
            best[s.kind] = s
    return best
