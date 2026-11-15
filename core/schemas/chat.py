"""Chat-turn domain types shared by app (engine), rag (retrieval) and evals."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from core.schemas.source import ContentType, Language, ReuseMode

Locale = Literal["en", "fr", "ar"]


class Intent(StrEnum):
    MEDICAL_INFO = "medical_info"  # general information about a condition, test, body, prevention
    MEDICATION = "medication"  # questions about a medicine (always verify-then-release)
    SYMPTOM_INFO = "symptom_info"  # describes symptoms (information only; never a triage verdict)
    HOSPITAL_ADMIN = "hospital_admin"  # hours, departments, contacts, directions, insurance, documents
    APPOINTMENT = "appointment"  # wants to book / change / cancel -> appointment request form
    SMALLTALK = "smalltalk"
    META = "meta"  # asks about the assistant itself
    OUT_OF_SCOPE = "out_of_scope"


class RiskKind(StrEnum):
    EMERGENCY = "emergency"  # possible acute emergency now
    SELF_HARM = "self_harm"  # suicidal ideation / self-harm
    HARM_TO_OTHERS = "harm_to_others"
    ABUSE_DISCLOSURE = "abuse_disclosure"  # domestic / sexual / child abuse disclosed
    INJECTION = "injection"  # tries to override rules / extract instructions
    HARMFUL_REQUEST = "harmful_request"  # wants instructions to cause harm (overdose methods, etc.)
    ABUSIVE_USER = "abusive_user"  # insults / harassment aimed at the assistant


class Population(StrEnum):
    PREGNANCY = "pregnancy"
    BREASTFEEDING = "breastfeeding"
    CHILD = "child"
    OLDER_ADULT = "older_adult"


class Signal(BaseModel):
    """One piece of evidence for a risk, from a specific detector."""

    model_config = ConfigDict(frozen=True)

    kind: RiskKind
    source: Literal["lexicon", "classifier", "upstream_block", "sanitizer", "session_sticky"]
    score: float = Field(ge=0.0, le=1.0)
    detail: str = ""


class GuardVerdict(BaseModel):
    """Output of the guard/router stage. Deterministic signals are OR-ed with the classifier: fail safe."""

    model_config = ConfigDict(frozen=True)

    language: Locale
    intent: Intent
    intent_confidence: float = Field(ge=0.0, le=1.0)
    risks: tuple[Signal, ...] = ()
    populations: tuple[Population, ...] = ()
    classifier_available: bool = True

    def has(self, kind: RiskKind) -> bool:
        return any(s.kind is kind for s in self.risks)

    @property
    def high_risk_medical(self) -> bool:
        """Answers that must be verified before anything is shown (verify-then-release)."""
        return self.intent in (Intent.MEDICATION, Intent.SYMPTOM_INFO) or bool(self.populations)


class HistoryTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant"]
    text: str  # already sanitised + redacted


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    standalone_query: str  # de-contextualised question in the user's language
    search_queries: tuple[str, ...] = ()  # extra queries (e.g. English translation, synonyms)
    language: Locale
    filters: dict[str, list[str]] = Field(default_factory=dict)  # e.g. {"content_type": ["drug_label"]}
    top_k: int = Field(default=8, ge=1, le=20)


class RetrievedPassage(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    doc_id: str
    source_id: str
    title: str
    url: HttpUrl
    heading_path: tuple[str, ...] = ()
    text: str  # chunk text, possibly expanded with its parent section (small-to-big)
    language: Language
    content_type: ContentType
    trust_tier: int
    reuse_mode: ReuseMode
    attribution: str
    reviewed_on: date | None = None
    score: float  # final ranking score (higher is better)
    scores: dict[str, float] = Field(default_factory=dict)  # per-stage scores: dense, sparse, rrf, rerank


class RetrievalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    passages: tuple[RetrievedPassage, ...]
    confident: bool  # False -> engine must abstain ("I don't have reliable information on that")
    confidence: float = Field(ge=0.0, le=1.0)
    reranked: bool = False
    timings_ms: dict[str, float] = Field(default_factory=dict)
    corpus_version: str = ""


class Citation(BaseModel):
    """What the UI shows for a [n] marker. Built server-side from RetrievedPassage, never from model text."""

    model_config = ConfigDict(frozen=True)

    n: int = Field(ge=1)
    title: str
    publisher: str  # from attribution
    url: HttpUrl
    heading: str = ""
    reviewed_on: date | None = None
    language: Language
    snippet: str = Field(max_length=600)
