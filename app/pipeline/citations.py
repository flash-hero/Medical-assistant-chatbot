"""Citations are built server-side from RetrievedPassage objects, never from model text: the model only emits
[n] markers, and the server resolves n to the passage it supplied at position n.

A drug-label citation names its jurisdiction after the publisher ("U.S. Food and Drug Administration · US FDA
label"), because a label approved in one country may differ from the product sold where the reader lives
(review C7)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING

from core.schemas.chat import Citation, Locale, RetrievedPassage
from core.schemas.source import ContentType

if TYPE_CHECKING:
    from app.pipeline.texts import Texts

SNIPPET_CHARS = 600
# data_pipeline/sources/registry.yaml ids of drug-label sources -> jurisdiction key (responses.yaml labels)
LABEL_JURISDICTION: Mapping[str, str] = MappingProxyType(
    {"openfda_labels": "us", "bdpm": "fr", "ema_product_information": "eu"}
)


def snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 1].rsplit(" ", 1)[0]
    return cut + "…"


def publisher_of(passage: RetrievedPassage, texts: Texts | None, locale: str) -> str:
    if passage.content_type is not ContentType.DRUG_LABEL or texts is None:
        return passage.attribution
    jurisdiction = LABEL_JURISDICTION.get(passage.source_id, "unknown")
    tag = texts.response(f"label_jurisdiction_{jurisdiction}", locale, None)
    return f"{passage.attribution} · {tag}"


def build_citations(
    passages: Sequence[RetrievedPassage],
    cited: Iterable[int],
    *,
    texts: Texts | None = None,
    locale: str = "en",
) -> tuple[Citation, ...]:
    out: list[Citation] = []
    for n in sorted(set(cited)):
        if not 1 <= n <= len(passages):
            continue
        p = passages[n - 1]
        out.append(
            Citation(
                n=n,
                title=p.title,
                publisher=publisher_of(p, texts, locale),
                url=p.url,
                heading=" > ".join(p.heading_path),
                reviewed_on=p.reviewed_on,
                language=p.language,
                snippet=snippet(p.text),
            )
        )
    return tuple(out)


def needs_source_language_note(citations: Iterable[Citation], answer_language: Locale) -> bool:
    return any(c.language.value != answer_language for c in citations)
