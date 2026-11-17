"""Composition root: builds every long-lived object of the API from Settings (plus test overrides).

LLM        AUSCULTA_LLM_BACKEND=gemini -> GeminiProvider (spend-metered); =fake -> scripted FakeLLMProvider
Retriever  rag.retrieval.build_retriever, imported lazily; None (medical answers degrade to a fixed
           "temporarily unavailable" text) when the module cannot be imported or fails to build.
           With the fake LLM backend a FakeRetriever with synthetic passages is used. Warmed up at startup
           (BM25 analysers, query-embedding model) so the first turn does not block the event loop (P12).
           The real retriever serves only after rag.verify.verify_live_corpus accepted the live collection
           (S8/P6; app/api/corpus.py), checked in a startup task.
Stores     sessions + turn gate: memory, or Redis (REDIS_URL) shared by every worker (P2/S5);
           relational: SQLite (dev) or Postgres (DATABASE_URL), purged hourly by retention (S6/P7)
Limits     per-IP / per-session rate limits, admission control, daily spend cap, kill switch
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import anyio
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.corpus import CorpusVerifier, VerifiedRetriever
from app.api.gate import MemoryTurnGate, RedisTurnGate, TurnGate
from app.api.tokens import SessionTokenSigner
from app.config_files import ConfigFileError
from app.guardrails.ingress import process_ingress
from app.limits.admission import AdmissionController
from app.limits.rate import RateLimiter, RateRules, rules_from_settings, storage_uri
from app.limits.spend import KillSwitch, MemorySpendMeter, RedisSpendMeter
from app.pipeline.engine import TURN_DEADLINE_S, TurnEngine
from app.pipeline.factory import EngineConfig, build_engine, load_engine_config, with_policies
from app.pipeline.record import TurnRecord
from app.pipeline.session import MemorySessionStore, RedisSessionStore, SessionStore
from app.storage.db import create_schema, is_sqlite, make_engine, ping, session_factory
from app.storage.repositories import Storage
from core.config import Settings
from core.ports import LLMProvider, Retriever, SpendMeter
from core.schemas.events import ReleaseInfo
from core.schemas.hospital import HospitalProfile

log = structlog.get_logger(__name__)
KEEPALIVE_S = 15.0
CANCEL_GRACE_S = 1.0
PURGE_INTERVAL_S = 60 * 60.0
WARM_UP_MESSAGE = "warm-up: what are the visiting hours?"
_UNSET: Any = object()


@dataclass(frozen=True)
class Overrides:
    """Injection points for tests and local tooling (production passes none)."""

    llm: LLMProvider | None = None
    retriever: Retriever | None = _UNSET
    engine_config: EngineConfig | None = None
    keepalive_s: float = KEEPALIVE_S
    cancel_grace_s: float = CANCEL_GRACE_S
    today: Callable[[], date] | None = None
    redis_client: Any = None
    rate_rules: Callable[[RateRules], RateRules] | None = None
    purge_interval_s: float = PURGE_INTERVAL_S
    turn_deadline_s: float | None = None
    corpus_verifier: CorpusVerifier | None = _UNSET  # default: verify the real retriever, nothing else


@dataclass
class Container:
    settings: Settings
    config: EngineConfig
    llm: LLMProvider
    retriever: Retriever | None
    sessions: SessionStore
    db: AsyncEngine
    storage: Storage
    rate: RateLimiter
    admission: AdmissionController
    spend: SpendMeter
    kill_switch: KillSwitch
    signer: SessionTokenSigner
    engine: TurnEngine
    registry: TurnGate
    keepalive_s: float
    cancel_grace_s: float
    today: Callable[[], date]
    redis: Any = None
    purge_interval_s: float = PURGE_INTERVAL_S
    corpus_verifier: CorpusVerifier | None = None
    started: bool = field(default=False)
    _purge_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _corpus_task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def texts(self) -> Any:
        return self.config.texts

    def profile(self) -> HospitalProfile | None:
        return self.config.profile_state.active(self.today())

    def release(self) -> ReleaseInfo:
        """Release tuple of the next turn (follows corpus promotions made while the API runs)."""
        base = self.engine.release
        if self.retriever is None:
            return base
        try:
            corpus = self.retriever.corpus_version or base.corpus_version
        except Exception:
            corpus = base.corpus_version
        return base.model_copy(update={"corpus_version": corpus})

    async def startup(self) -> None:
        if self.started:
            return
        if is_sqlite(self.settings.database_url) or self.settings.env in ("dev", "test"):
            await create_schema(self.db)
        await self.warm_up()
        if self._purge_task is None or self._purge_task.done():
            self._purge_task = asyncio.create_task(self._purge_loop(), name="retention-purge")
        if (
            self.corpus_verifier is not None
            and isinstance(self.retriever, VerifiedRetriever)
            and self._corpus_task is None
        ):
            check = self.retriever.verify(self.corpus_verifier, self.settings)
            self._corpus_task = asyncio.create_task(check, name="corpus-verify")
        self.started = True

    async def corpus_ready(self) -> None:
        """Wait for the startup corpus verification (tests, tooling); returns at once when there is none."""
        if self._corpus_task is not None:
            await asyncio.shield(self._corpus_task)

    async def warm_up(self) -> None:
        """Pay one-time costs before the first turn: the thread-pool backend import, lexicon and regex caches
        (so the first emergency message is as fast as every later one) and the retriever's BM25 analysers and
        query-embedding model (review P12). A failed retriever warm-up only costs a slower first answer."""
        sample = process_ingress(
            WARM_UP_MESSAGE, max_chars=self.settings.max_message_chars, today=self.today()
        )
        await anyio.to_thread.run_sync(self.engine.precheck, sample)
        warmup = getattr(self.retriever, "warmup", None)
        if warmup is None:
            return
        try:
            await warmup()
        except Exception as exc:
            log.warning("retriever_warmup_failed", error=type(exc).__name__)

    async def purge_once(self) -> None:
        """Retention purge of every table (idempotent; every worker may run it)."""
        try:
            counts = await self.storage.purge_expired()
        except Exception as exc:
            log.error("retention_purge_failed", error=type(exc).__name__)
            return
        log.info("retention_purged", **counts)

    async def _purge_loop(self) -> None:
        while True:
            await self.purge_once()
            await asyncio.sleep(self.purge_interval_s)

    async def shutdown(self) -> None:
        for task in (self._purge_task, self._corpus_task):
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
        self._purge_task = self._corpus_task = None
        await self.db.dispose()
        await _close_quietly(self.retriever, "retriever")
        await _close_quietly(self.llm, "llm")  # the Gemini provider owns an HTTP client
        await _close_quietly(self.redis, "redis")  # review P17
        self.started = False

    async def persist_turn(self, record: TurnRecord) -> None:
        await self.storage.turns.save(record)
        state = await self.sessions.get(record.session_id)
        if state is not None:
            await self.storage.sessions.update_counters(state)

    async def ready_checks(self) -> dict[str, bool]:
        checks = {
            "database": await ping(self.db),
            "sessions": await self.sessions.ping(),
            "rate_limiter": await self.rate.ping(),
            "retriever": False,
            "hospital_profile": self.profile() is not None,
        }
        if self.retriever is not None:
            try:
                checks["retriever"] = bool(await self.retriever.health())
            except Exception:
                checks["retriever"] = False
        return checks


async def _close_quietly(resource: object, name: str) -> None:
    """Call resource.aclose() or resource.close() (sync or async); shutdown must finish even if it fails."""
    closer = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if closer is None:
        return
    try:
        result = closer()
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:
        log.warning("resource_close_failed", resource=name, error=type(exc).__name__)


# ---- builders ------------------------------------------------------------------------------------
def _session_secret(settings: Settings) -> bytes:
    if settings.session_secret is not None:
        secret = settings.session_secret.get_secret_value().encode("utf-8")
        if len(secret) < 32:
            raise ConfigFileError("AUSCULTA_SESSION_SECRET must be at least 32 characters")
        return secret
    if settings.env in ("staging", "prod"):  # also refused by Settings itself; kept as defence in depth
        raise ConfigFileError("AUSCULTA_SESSION_SECRET is required outside dev/test")
    log.warning("session_secret_ephemeral", hint="tokens become invalid on restart")
    return os.urandom(32)


def _redis(settings: Settings, overrides: Overrides) -> Any:
    if overrides.redis_client is not None:
        return overrides.redis_client
    if not settings.redis_url:
        return None
    import redis.asyncio as redis_asyncio

    return redis_asyncio.from_url(settings.redis_url)


def _llm(settings: Settings, overrides: Overrides, spend: SpendMeter) -> LLMProvider:
    if overrides.llm is not None:
        return overrides.llm
    if settings.llm_backend == "fake":
        from evals.fakes.scripted import scripted_provider

        return scripted_provider()
    from app.llm.factory import build_llm_provider

    return build_llm_provider(settings, spend=spend)


def build_retriever_or_none(settings: Settings, llm: LLMProvider) -> Retriever | None:
    """The real retriever, or None when rag is not importable / cannot be built (answers then degrade)."""
    if settings.llm_backend == "fake":
        from evals.fakes.fake_retriever import FakeRetriever

        return FakeRetriever()
    try:
        from rag.retrieval import build_retriever
    except Exception as exc:
        log.warning("retriever_import_failed", error=type(exc).__name__)
        return None
    try:
        return build_retriever(settings, llm)
    except Exception as exc:
        log.warning("retriever_build_failed", error=type(exc).__name__)
        return None


def build_container(settings: Settings, overrides: Overrides | None = None) -> Container:
    ov = overrides or Overrides()
    today = ov.today or (lambda: datetime.now(UTC).date())
    redis_client = _redis(settings, ov)
    spend: SpendMeter = (
        RedisSpendMeter(redis_client, settings.daily_spend_cap_usd)
        if redis_client is not None
        else MemorySpendMeter(settings.daily_spend_cap_usd)
    )
    llm = _llm(settings, ov, spend)
    retriever, verifier = _retriever_and_verifier(settings, ov, llm)
    sessions: SessionStore = (
        RedisSessionStore(redis_client) if redis_client is not None else MemorySessionStore()
    )
    gate: TurnGate = RedisTurnGate(redis_client) if redis_client is not None else MemoryTurnGate()
    config = with_policies(ov.engine_config or load_engine_config(settings.hospital_profile_path), settings)
    rules = rules_from_settings(settings)
    db = make_engine(settings.database_url)
    return Container(
        settings=settings,
        config=config,
        llm=llm,
        retriever=retriever,
        sessions=sessions,
        db=db,
        storage=Storage.from_factory(session_factory(db)),
        rate=RateLimiter(storage_uri(settings), ov.rate_rules(rules) if ov.rate_rules else rules),
        admission=AdmissionController(settings.llm_concurrency, settings.queue_max, settings.queue_wait_s),
        spend=spend,
        kill_switch=KillSwitch(settings.kill_switch, settings.data_root),
        signer=SessionTokenSigner(_session_secret(settings)),
        engine=build_engine(
            config,
            llm=llm,
            retriever=retriever,
            sessions=sessions,
            settings=settings,
            today=today,
            deadline_s=ov.turn_deadline_s or TURN_DEADLINE_S,
        ),
        registry=gate,
        keepalive_s=ov.keepalive_s,
        cancel_grace_s=ov.cancel_grace_s,
        today=today,
        redis=redis_client,
        purge_interval_s=ov.purge_interval_s,
        corpus_verifier=verifier,
    )


def _retriever_and_verifier(
    settings: Settings, ov: Overrides, llm: LLMProvider
) -> tuple[Retriever | None, CorpusVerifier | None]:
    """The retriever to serve and how its corpus is verified. The real one (not the fake backend, not a test
    override) is always checked with rag.verify.verify_live_corpus; a test may pass its own verifier."""
    real = ov.retriever is _UNSET and settings.llm_backend != "fake"
    retriever = build_retriever_or_none(settings, llm) if ov.retriever is _UNSET else ov.retriever
    verifier = ov.corpus_verifier
    if verifier is _UNSET:
        verifier = _live_corpus_verifier() if real else None
    if retriever is None or verifier is None:
        return retriever, None
    return VerifiedRetriever(retriever), verifier


def _live_corpus_verifier() -> CorpusVerifier:
    from rag.verify import verify_live_corpus

    return verify_live_corpus
