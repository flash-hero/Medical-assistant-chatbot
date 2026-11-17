"""RAG-specific errors (stable machine codes, same base class as core.errors)."""

from __future__ import annotations

from core.errors import AusculaError


class SourceNotIndexable(AusculaError):
    """The source is missing from the registry, or not ACTIVE (hold / excluded / non-commercial)."""

    code, http_status = "source_not_indexable", 409


class CorpusNotReady(AusculaError):
    """The data track has not published the source yet (no normalized/_ready marker)."""

    code, http_status = "corpus_not_ready", 409


class EmbeddingQuotaExhausted(AusculaError):
    """The provider's DAILY embedding quota is spent (or a per-minute limit never clears).
    Progress is already in the embedding cache; re-running the same build resumes with zero repeats."""

    code, http_status = "embedding_quota_exhausted", 429

    def __init__(self, message: str = "", *, embedded: int, remaining: int, scope: str) -> None:
        super().__init__(message, detail={"embedded": embedded, "remaining": remaining, "scope": scope})
        self.embedded = embedded
        self.remaining = remaining
        self.scope = scope


class IndexMismatch(AusculaError):
    """An existing collection's schema does not match what this build expects."""

    code, http_status = "index_mismatch", 409


class CorpusUnverified(IndexMismatch):
    """A collection does not match its signed manifest (or cannot be checked): never serve or promote it."""

    code, http_status = "corpus_unverified", 503


class GateFailed(AusculaError):
    """Promotion refused: the collection has no passing retrieval-gate report."""

    code, http_status = "retrieval_gate_failed", 409
