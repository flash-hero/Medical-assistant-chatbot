"""Drives the real ASGI app (app.main.create_app) in-process, one chat turn at a time.

Real mode (`open_real_harness`): the Gemini provider (production retry policy, spend-metered) wrapped in
CountingProvider; the live retriever (rag.retrieval.build_retriever on the `ausculta_corpus` alias) wrapped in
RecordingRetriever and, as in production, served only after rag.verify.verify_live_corpus accepted the live
collection; the real guardrails and engine from the config files. Only stateful stores differ: an SQLite file
under the P4 reports folder, in-memory sessions and rate limits (relaxed so that the eval's pacing, not the
per-client limits, decides the request rate).

`stop_after_guard=True` (safety suite): rewrite / answer calls park and the client disconnects as soon as the
turn reports `status: searching` (the guard has decided by then), so a turn costs at most the guard calls.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TextIO

import structlog
from limits import parse

from app.api.container import Container, Overrides
from app.guardrails.ingress import process_ingress
from app.limits.rate import RateRules
from app.limits.spend import MemorySpendMeter
from app.main import create_app
from app.pipeline.medical import MedicalResponder
from core.config import Settings
from core.errors import InvalidInput
from core.schemas.chat import Intent
from evals.fakes.asgi_driver import DriveResult, drive
from evals.p4.provider import HALT_ROLES, CountingProvider, CountingRetryPolicy
from evals.p4.results import TurnResult, passage_dicts, timed_payloads
from evals.p4.retrievers import HaltingRetriever, RecordingRetriever

SEARCHING = '"stage":"searching"'
TURN_TIMEOUT_S = 120.0
_RELAXED = "100000/minute"


def relaxed_rules(rules: RateRules) -> RateRules:
    """Per-client limits out of the way: the runner paces itself to stay inside the provider's quotas."""
    big = parse(_RELAXED)
    return replace(
        rules,
        per_ip=big,
        per_session=big,
        session_create_per_ip=big,
        session_create_global=big,
        safety_per_ip=big,
    )


@dataclass
class Harness:
    app: Any
    container: Container
    llm: CountingProvider
    retriever: RecordingRetriever | HaltingRetriever | Any
    retry_policy: CountingRetryPolicy | None = None
    stop_after_guard: bool = False
    _n: int = field(default=0, repr=False)

    def _client(self) -> tuple[str, int]:
        self._n += 1
        return (f"198.51.100.{self._n % 250 + 1}", 40000 + self._n % 20000)

    async def new_session(self, locale: str) -> str:
        res = await drive(self.app, "POST", "/api/v1/session", {"locale": locale}, client=self._client())
        if res.status != 201:
            raise RuntimeError(f"session creation failed: HTTP {res.status} {res.body[:200]}")
        return str(json.loads(res.body)["session_token"])

    def precheck_kinds(self, message: str) -> tuple[str, ...]:
        """The deterministic precheck the chat route runs first (lexicon + injection heuristics)."""
        try:
            ingress = process_ingress(
                message, max_chars=self.container.settings.max_message_chars, today=self.container.today()
            )
        except InvalidInput:
            return ("ingress_rejected",)
        pre = self.container.engine.precheck(ingress)
        return tuple(sorted({s.kind.value for s in pre.signals}))

    async def turn(self, token: str, message: str, locale: str) -> TurnResult:
        begin = getattr(self.retriever, "begin_turn", None)
        if begin is not None:
            begin()
        calls_before = len(self.llm.calls)
        retries_before = len(self.retry_policy.retries) if self.retry_policy else 0
        stop: Callable[[DriveResult], bool] | None = None
        if self.stop_after_guard:

            def stop(r: DriveResult) -> bool:
                return bool(r.chunks) and SEARCHING in r.chunks[-1].decode("utf-8", errors="replace")

        body = {"message": message, "locale": locale, "client_turn_id": str(uuid.uuid4())}
        headers = {"authorization": f"Bearer {token}", "accept": "text/event-stream"}
        res = await drive(
            self.app,
            "POST",
            "/api/v1/chat",
            body,
            headers,
            disconnect_when=stop,
            disconnect_after_s=TURN_TIMEOUT_S,
            client=self._client(),
        )
        return self._result(message, res, calls_before, retries_before)

    def _result(self, message: str, res: DriveResult, calls_before: int, retries_before: int) -> TurnResult:
        error = ""
        timed: list[tuple[float, dict[str, Any]]] = []
        if res.status == 200:
            try:
                timed = timed_payloads(res)
            except ValueError as exc:
                error = f"sse_parse_error: {exc}"
        else:
            error = f"http_{res.status}: {res.body[:200]}"
        payloads = tuple(p for _, p in timed)
        answer = next((p for p in reversed(payloads) if p.get("type") == "answer"), None)
        passages, confident = self._passages(answer)
        retries = (len(self.retry_policy.retries) - retries_before) if self.retry_policy else 0
        record = getattr(self.retriever, "turn_record", None)
        return TurnResult(
            message=message,
            http_status=res.status,
            payloads=payloads,
            times_s=tuple(t for t, _ in timed),
            elapsed_s=round(res.elapsed_s, 4),
            halted=self.stop_after_guard and res.disconnected_at is not None and res.finished_at is None,
            precheck_kinds=self.precheck_kinds(message),
            calls=tuple(c.to_dict(base=res.started_at) for c in self.llm.calls[calls_before:]),
            retries=retries,
            passages=passages,
            retrieval_confident=confident,
            error=error,
            retrievals=record(res.started_at) if record is not None else (),
        )

    def _passages(self, answer: dict[str, Any] | None) -> tuple[tuple[dict[str, Any], ...], bool | None]:
        """The passages the answer model saw, in prompt order ([n] = position n), as the medical path chose
        them (MedicalResponder._admissible: medication answers use drug-label passages only)."""
        results = getattr(self.retriever, "results", None)
        if not results:
            return (), None
        last = results[-1]
        passages = tuple(last.passages)
        if answer is not None and answer.get("intent") in {i.value for i in Intent}:
            passages = MedicalResponder._admissible(Intent(str(answer["intent"])), passages)
        return passage_dicts(passages), bool(last.confident)


def _quiet_logs(log_file: TextIO | None) -> None:
    """create_app logs to stderr; send the run's logs to a file instead (ids and codes only)."""
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=log_file or sys.stderr))


@asynccontextmanager
async def open_harness(
    settings: Settings,
    llm: CountingProvider,
    retriever: Any,
    *,
    corpus_verifier: Any = None,
    retry_policy: CountingRetryPolicy | None = None,
    stop_after_guard: bool = False,
    engine_config: Any = None,
    today: Any = None,
    log_file: TextIO | None = None,
) -> AsyncIterator[Harness]:
    overrides = Overrides(
        llm=llm,
        retriever=retriever,
        corpus_verifier=corpus_verifier,
        rate_rules=relaxed_rules,
        engine_config=engine_config,
        today=today,
    )
    app = create_app(settings, overrides=overrides)
    _quiet_logs(log_file)
    container: Container = app.state.container
    async with app.router.lifespan_context(app):
        await container.corpus_ready()
        state = getattr(container.retriever, "state", "verified")
        if state != "verified":
            raise RuntimeError(f"live corpus not verified ({state}): refusing to measure answers")
        yield Harness(app, container, llm, retriever, retry_policy, stop_after_guard)


def real_settings(db_path: Path) -> Settings:
    """Settings from .env (Gemini key, Qdrant), with the eval's own SQLite file and relaxed turn budget."""
    return Settings(
        AUSCULTA_ENV="test",
        AUSCULTA_LLM_BACKEND="gemini",
        DATABASE_URL=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        REDIS_URL=None,
        AUSCULTA_KILL_SWITCH=False,
    )


@asynccontextmanager
async def open_real_harness(
    settings: Settings,
    *,
    stop_after_guard: bool,
    max_generate: int | None,
    max_decide: int | None,
    log_file: TextIO | None = None,
) -> AsyncIterator[Harness]:
    """The production pipeline on the real Gemini provider and the live corpus (see module docstring)."""
    from app.llm.gemini_provider import GeminiProvider

    policy = CountingRetryPolicy()
    inner = GeminiProvider(settings, spend=MemorySpendMeter(settings.daily_spend_cap_usd), policy=policy)
    llm = CountingProvider(
        inner,
        tier=settings.gemini_tier,
        max_generate=max_generate,
        max_decide=max_decide,
        halt_roles=HALT_ROLES if stop_after_guard else frozenset(),
    )
    retriever: Any
    verifier: Any = None
    if stop_after_guard:
        retriever = HaltingRetriever()  # the safety decision never needs retrieval (no embedding model)
    else:
        from rag.retrieval import build_retriever
        from rag.verify import verify_live_corpus

        retriever = RecordingRetriever(build_retriever(settings, llm))
        verifier = verify_live_corpus
    async with open_harness(
        settings,
        llm,
        retriever,
        corpus_verifier=verifier,
        retry_policy=policy,
        stop_after_guard=stop_after_guard,
        log_file=log_file,
    ) as harness:
        yield harness


__all__ = ["Harness", "open_harness", "open_real_harness", "real_settings", "relaxed_rules"]
