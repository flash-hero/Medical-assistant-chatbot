"""Builds the turn engine from the config files, an LLMProvider and an optional Retriever.

Config files are loaded once at startup (`load_engine_config`); a malformed file raises ConfigFileError
there, never during a turn. The hospital profile is the exception: a missing, invalid or expired profile
only disables receptionist features (ProfileState.error), it never stops the app."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import structlog

from app.guardrails.groundedness import GroundednessVerifier
from app.guardrails.guard_prompts import GuardPrompts, load_guard_prompts
from app.guardrails.lexicon import LexiconMatcher, LexiconSettings, load_lexicon
from app.guardrails.output_checks import policy_ngrams
from app.guardrails.router import GuardRouter
from app.guardrails.safety_config import SafetyConfig, load_safety_config
from app.hospital.profile import ProfileState, load_profile
from app.pipeline.engine import TurnEngine
from app.pipeline.medical import MedicalResponder
from app.pipeline.prompts import PromptSet, load_prompt_set
from app.pipeline.rewrite import QueryRewriter
from app.pipeline.session import SessionStore
from app.pipeline.texts import Texts, load_texts
from core.config import Settings
from core.models import ModelRole, model_for
from core.ports import LLMProvider, Retriever
from core.schemas.events import ReleaseInfo

log = structlog.get_logger(__name__)
UNKNOWN_CORPUS = "none"
_RELEASE_ROLES = (
    ModelRole.ANSWER,
    ModelRole.ANSWER_FALLBACK,
    ModelRole.GUARD,
    ModelRole.GUARD_FALLBACK,
    ModelRole.REWRITE,
    ModelRole.VERIFY,
    ModelRole.EMBED,
)


@dataclass(frozen=True)
class EngineConfig:
    lexicon: LexiconMatcher
    safety: SafetyConfig
    guard_prompts: GuardPrompts
    prompts: PromptSet
    texts: Texts
    profile_state: ProfileState


def app_version() -> str:
    try:
        return importlib.metadata.version("ausculta")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def load_engine_config(profile_path: Path, *, canary: str | None = None) -> EngineConfig:
    safety = load_safety_config()
    return EngineConfig(
        lexicon=load_lexicon(settings=LexiconSettings(fuzzy_min_term_chars=safety.fuzzy_min_term_chars)),
        safety=safety,
        guard_prompts=load_guard_prompts(),
        prompts=load_prompt_set(canary=canary),
        texts=load_texts(),
        profile_state=load_profile(profile_path),
    )


def release_info(settings: Settings, prompts: PromptSet, corpus_version: str) -> ReleaseInfo:
    models = {role.value: model_for(role, settings.gemini_tier).model_id for role in _RELEASE_ROLES}
    if settings.llm_backend == "fake":
        models = {role: f"fake:{model_id}" for role, model_id in models.items()}
    return ReleaseInfo(
        app_version=app_version(),
        corpus_version=corpus_version or UNKNOWN_CORPUS,
        prompt_hash=prompts.prompt_hash,
        models=models,
    )


def corpus_version_of(retriever: Retriever | None) -> str:
    """The retriever's corpus version, or UNKNOWN_CORPUS when there is none or it cannot be read."""
    if retriever is None:
        return UNKNOWN_CORPUS
    try:
        return retriever.corpus_version or UNKNOWN_CORPUS
    except Exception as exc:
        log.warning("corpus_version_unavailable", error=type(exc).__name__)
        return UNKNOWN_CORPUS


def build_engine(
    config: EngineConfig,
    *,
    llm: LLMProvider,
    retriever: Retriever | None,
    sessions: SessionStore,
    settings: Settings,
    today: Callable[[], date] | None = None,
) -> TurnEngine:
    safety = config.safety
    router = GuardRouter(llm, config.lexicon, config.guard_prompts, safety)
    verifier = GroundednessVerifier(
        llm, config.guard_prompts.verify, safety.groundedness, timeout_s=safety.timeouts.verify_s
    )
    medical = MedicalResponder(
        llm=llm,
        retriever=retriever,
        rewriter=QueryRewriter(llm, config.prompts.rewrite_system, timeout_s=safety.timeouts.rewrite_s),
        verifier=verifier,
        prompts=config.prompts,
        texts=config.texts,
        safety=safety,
        policy_ngrams=policy_ngrams(config.prompts.system_prompt, config.prompts.canary),
    )
    corpus = corpus_version_of(retriever)
    extra = {"today": today} if today is not None else {}
    return TurnEngine(
        router=router,
        medical=medical,
        texts=config.texts,
        profile_state=config.profile_state,
        sessions=sessions,
        settings=settings,
        release=release_info(settings, config.prompts, corpus),
        **extra,
    )
