"""Serve the live corpus only after it verified against its signed manifest (review S8/P6, API side).

VerifiedRetriever wraps the real retriever. At startup the container runs the verifier
(rag.verify.verify_live_corpus: every stored chunk re-hashed, point ids, count, HMAC of the manifest,
embedding model of this deployment) in a background task; until it succeeds, and for good if it fails,
retrieve() raises DependencyUnavailable and health() is False. Medical answers then degrade to the
"temporarily unavailable" template and /ready is 503, while emergency, self-harm and front-desk turns keep
working.
Fail closed: an exception of any kind in the check means "not verified".

Promotions and rollbacks made while the API runs are verified by the rag CLI itself (rag promote / rollback).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

import structlog

from core.config import Settings
from core.errors import DependencyUnavailable
from core.ports import Retriever
from core.schemas.chat import RetrievalQuery, RetrievalResult

log = structlog.get_logger(__name__)
CorpusVerifier = Callable[[Settings], Awaitable[Any]]
VerifyState = Literal["pending", "verified", "failed"]
REASON_CHARS = 300


class VerifiedRetriever:
    def __init__(self, inner: Retriever) -> None:
        self._inner = inner
        self.state: VerifyState = "pending"

    @property
    def corpus_version(self) -> str:
        return self._inner.corpus_version

    async def health(self) -> bool:
        return self.state == "verified" and bool(await self._inner.health())

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        if self.state != "verified":
            raise DependencyUnavailable(f"corpus not verified ({self.state})")
        return await self._inner.retrieve(query)

    async def verify(self, verifier: CorpusVerifier, settings: Any) -> None:
        try:
            verified = await verifier(settings)
        except Exception as exc:
            self.state = "failed"
            log.error("corpus_unverified", error=type(exc).__name__, reason=str(exc)[:REASON_CHARS])
            return
        self.state = "verified"
        log.info(
            "corpus_verified",
            collection=str(getattr(verified, "collection", "")),
            corpus_version=str(getattr(verified, "corpus_version", "")),
            embed_model=str(getattr(verified, "embed_model", "")),
            chunks=int(getattr(verified, "chunks", 0)),
        )

    async def warmup(self) -> None:
        warmup = getattr(self._inner, "warmup", None)
        if warmup is not None:
            await warmup()

    async def aclose(self) -> None:
        closer = getattr(self._inner, "aclose", None) or getattr(self._inner, "close", None)
        if closer is None:
            return
        result = closer()
        if hasattr(result, "__await__"):
            await result
