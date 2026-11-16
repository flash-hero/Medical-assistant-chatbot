"""Composition root: builds every long-lived object of the API from Settings (plus test overrides).

LLM        AUSCULTA_LLM_BACKEND=gemini -> GeminiProvider (spend-metered); =fake -> scripted FakeLLMProvider
Retriever  rag.retrieval.build_retriever, imported lazily; None (medical answers degrade to a fixed
           "temporarily unavailable" text) when the module cannot be imported or fails to build.
           With the fake LLM backend a FakeRetriever with synthetic passages is used.
Stores     sessions: memory or Redis (REDIS_URL); relational: SQLite (dev) or Postgres (DATABASE_URL)
Limits     per-IP / per-session rate limits, admission control, daily spend cap, kill switch
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import anyio
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.tokens import SessionTokenSigner
from app.api.turns import TurnRegistry
from app.config_files import ConfigFileError
from app.guardrails.ingress import process_ingress
from app.limits.admission import AdmissionController
from app.limits.rate import RateLimiter, rules_from_settings, storage_uri
from app.limits.spend import KillSwitch, MemorySpendMeter, RedisSpendMeter
from app.pipeline.engine import TurnEngine
from app.pipeline.factory import EngineConfig, build_engine, load_engine_config
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
    registry: TurnRegistry
    keepalive_s: float
    cancel_grace_s: float
    today: Callable[[], date]
    started: bool = field(default=False)

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
        try:
            purged = await self.storage.appointments.purge_expired()
            log.info("appointments_purged", contacts=purged.contacts, requests=purged.requests)
        except Exception as exc:
            log.error("appointment_purge_failed", error=type(exc).__name__)
        await self.warm_up()
        self.started = True

    async def warm_up(self) -> None:
        """Pay one-time costs (thread-pool backend import, lexicon and regex caches) before the first turn,
        so the first emergency message is as fast as every later one."""
        sample = process_ingress(
            WARM_UP_MESSAGE, max_chars=self.settings.max_message_chars, today=self.today()
        )
        await anyio.to_thread.run_sync(self.engine.precheck, sample)

    async def shutdown(self) -> None:
        await self.db.dispose()
        await _close_quietly(self.retriever, "retriever")
        await _close_quietly(self.llm, "llm")  # the Gemini provider owns an HTTP client
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
    if settings.env in ("staging", "prod"):
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
    retriever = build_retriever_or_none(settings, llm) if ov.retriever is _UNSET else ov.retriever
    sessions: SessionStore = (
        RedisSessionStore(redis_client) if redis_client is not None else MemorySessionStore()
    )
    config = ov.engine_config or load_engine_config(settings.hospital_profile_path)
    db = make_engine(settings.database_url)
    return Container(
        settings=settings,
        config=config,
        llm=llm,
        retriever=retriever,
        sessions=sessions,
        db=db,
        storage=Storage.from_factory(session_factory(db)),
        rate=RateLimiter(storage_uri(settings), rules_from_settings(settings)),
        admission=AdmissionController(settings.llm_concurrency, settings.queue_max, settings.queue_wait_s),
        spend=spend,
        kill_switch=KillSwitch(settings.kill_switch, settings.data_root),
        signer=SessionTokenSigner(_session_secret(settings)),
        engine=build_engine(
            config, llm=llm, retriever=retriever, sessions=sessions, settings=settings, today=today
        ),
        registry=TurnRegistry(),
        keepalive_s=ov.keepalive_s,
        cancel_grace_s=ov.cancel_grace_s,
        today=today,
    )
