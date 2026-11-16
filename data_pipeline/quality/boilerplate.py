"""Navigation / boilerplate removal for already-extracted plain text.

Two layers: (1) static patterns for lines that are never content (share buttons, "skip to", cookie notices,
print/back-to-top, page-review stamps), applied to every document; (2) a corpus-level filter that drops short
lines repeated across many documents of the same source (site chrome that survived extraction).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from core.schemas.document import Document, Section

_STATIC_LINE = re.compile(
    r"^\W*(?:"
    r"(?:skip (?:to|navigation|directly)|jump to|you are here|url of this page|page last (?:reviewed|updated)|"  # noqa: E501
    r"last (?:updated|reviewed|modified|medically reviewed)|official websites use|secure \.?gov websites|"
    r"to use the sharing features|we use cookies|accept (?:all )?cookies|was this (?:page|article|information)|"  # noqa: E501
    r"sign up for|follow us|copyright\s*(?:©|\(c\))|all rights reserved).*"
    r"|(?:back to top|share(?: this| on)?(?: page)?|print(?: this page)?|email(?: this)?|tweet|subscribe|"
    r"cookies?(?: policy| notice)?|rate this|breadcrumb|related (?:pages|topics|links)|on this page|"
    r"table of contents|contact us|privacy policy|terms of (?:use|service)|site map|menu|search|home|"
    r"español|en español|facebook|twitter|linkedin|instagram|youtube|pinterest|whatsapp)"
    r")\W*$",
    re.IGNORECASE,
)
_MIN_REPEAT_DOCS = 20
_MAX_REPEAT_WORDS = 14


def strip_static_boilerplate(text: str) -> str:
    kept = [line for line in text.split("\n") if not _STATIC_LINE.match(line.strip())]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _lines(doc: Document) -> Iterable[str]:
    for section in doc.sections:
        for line in section.text.split("\n"):
            stripped = line.strip()
            if stripped:
                yield stripped


@dataclass(frozen=True)
class RepeatedLineFilter:
    """Lines (<= 14 words) that occur in >= max(20, 2%) of a source's documents are chrome, not content."""

    boilerplate: frozenset[str]

    @classmethod
    def fit(cls, documents: Sequence[Document], *, min_docs: int = _MIN_REPEAT_DOCS) -> RepeatedLineFilter:
        counts: Counter[str] = Counter()
        for doc in documents:
            counts.update({line for line in _lines(doc) if len(line.split()) <= _MAX_REPEAT_WORDS})
        threshold = max(min_docs, int(0.02 * len(documents)))
        return cls(frozenset(line for line, n in counts.items() if n >= threshold))

    def apply(self, doc: Document) -> Document | None:
        """New Document without boilerplate lines, or None when nothing is left."""
        sections: list[Section] = []
        for section in doc.sections:
            kept = "\n".join(
                line for line in section.text.split("\n") if line.strip() not in self.boilerplate
            ).strip()
            if kept:
                sections.append(section.model_copy(update={"text": kept}))
        return doc.model_copy(update={"sections": tuple(sections)}) if sections else None


def clean_document(doc: Document) -> Document | None:
    """Apply the static patterns to every section; None when the document becomes empty."""
    sections: list[Section] = []
    for section in doc.sections:
        text = strip_static_boilerplate(section.text)
        if text:
            sections.append(section.model_copy(update={"text": text}))
    return doc.model_copy(update={"sections": tuple(sections)}) if sections else None
