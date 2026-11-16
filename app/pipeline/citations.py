"""Citations are built server-side from RetrievedPassage objects, never from model text: the model only emits [n]
markers, and the server resolves n to the passage it supplied at position n."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from core.schemas.chat import Citation, Locale, RetrievedPassage

SNIPPET_CHARS = 600


def snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 1].rsplit(" ", 1)[0]
    return cut + "…"


def build_citations(passages: Sequence[RetrievedPassage], cited: Iterable[int]) -> tuple[Citation, ...]:
    out: list[Citation] = []
    for n in sorted(set(cited)):
        if not 1 <= n <= len(passages):
            continue
        p = passages[n - 1]
        out.append(
            Citation(
                n=n,
                title=p.title,
                publisher=p.attribution,
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
