"""Deterministic in-process fake of core.ports.Retriever (synthetic passages, no network, no Qdrant).

Features: fixed or callable passages, confidence switch, latency and failure injection, call log.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from core.schemas.chat import RetrievalQuery, RetrievalResult, RetrievedPassage
from core.schemas.source import ContentType, Language, ReuseMode

SYNTHETIC_PASSAGES: tuple[tuple[str, str, str], ...] = (
    (
        "Fever",
        "Fever basics",
        "A fever is a body temperature of 38 °C or higher. Most fevers in adults go away within 3 days. "
        "Drinking fluids and resting can help you feel better.",
    ),
    (
        "Fever",
        "When to get help",
        "See a doctor if a fever lasts more than 3 days, or if it comes with a stiff neck, confusion or "
        "trouble breathing. Call emergency services for signs of a medical emergency.",
    ),
    (
        "Paracetamol (acetaminophen) label",
        "Directions",
        "Adults and children 12 years and over: 500 mg to 1,000 mg every 4 to 6 hours as needed. "
        "Do not take more than 4,000 mg in 24 hours. Ask a doctor or pharmacist before use if you have liver disease.",
    ),
)


def make_passage(
    n: int,
    text: str,
    *,
    title: str = "Synthetic topic",
    heading: str = "Overview",
    language: Language = Language.EN,
    reuse: ReuseMode = ReuseMode.PARAPHRASE_OK,
    content_type: ContentType = ContentType.CONDITION,
) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=f"fake:doc{n}#s1#0",
        doc_id=f"fake:doc{n}",
        source_id="fake_source",
        title=title,
        url=f"https://example.org/fake/{n}",  # type: ignore[arg-type]
        heading_path=(title, heading),
        text=text,
        language=language,
        content_type=content_type,
        trust_tier=1,
        reuse_mode=reuse,
        attribution="Synthetic test source",
        reviewed_on=date(2026, 1, 1),
        score=1.0 - n * 0.01,
        scores={"rrf": 1.0 - n * 0.01},
    )


def default_passages() -> tuple[RetrievedPassage, ...]:
    return tuple(
        make_passage(i, text, title=title, heading=heading)
        for i, (title, heading, text) in enumerate(SYNTHETIC_PASSAGES, 1)
    )


@dataclass
class FakeRetriever:
    passages: Sequence[RetrievedPassage] | Callable[[RetrievalQuery], Sequence[RetrievedPassage]] = field(
        default_factory=default_passages
    )
    confident: bool = True
    confidence: float = 0.9
    error: Exception | None = None
    latency_s: float = 0.0
    healthy: bool = True
    version: str = "fake-corpus-1"
    calls: list[RetrievalQuery] = field(default_factory=list)

    @property
    def corpus_version(self) -> str:
        return self.version

    async def health(self) -> bool:
        return self.healthy

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.calls.append(query)
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        if self.error is not None:
            raise self.error
        found = self.passages(query) if callable(self.passages) else self.passages
        return RetrievalResult(
            passages=tuple(found)[: query.top_k],
            confident=self.confident,
            confidence=self.confidence if self.confident else 0.1,
            reranked=False,
            timings_ms={"retrieval_ms": 1.0},
            corpus_version=self.version,
        )
