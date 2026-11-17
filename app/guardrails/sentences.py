"""Sentence segmentation for EN/FR/AR answers and a streaming buffer that releases complete sentences only.

Each Sentence keeps its trailing separator (" " or "\\n\\n") so that joining sentences reproduces the layout.
Citation markers that follow the full stop ("... fever. [1]") stay with the sentence they cite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# End of sentence: terminal punctuation (incl. Arabic ؟ and ellipsis), optional closing quotes/brackets and
# trailing citation markers, then whitespace. A newline always ends a sentence (list items, headings).
_BOUNDARY = re.compile(r"(?<=[.!?؟…])[\"'»”)\]]*(?:\s*\[\d+\])*(?=\s)|\n")
_ABBREVIATIONS = re.compile(
    r"(?:\b(?:e\.g|i\.e|etc|dr|mr|mrs|ms|vs|approx|no|fig|min|max|env|cf|p\.ex|ex|av|apr|j\.-c)\.|\b[a-z]\.)$",
    re.IGNORECASE,
)
_NUMBER_DOT = re.compile(r"\d\.$")


@dataclass(frozen=True)
class Sentence:
    text: str  # without the separator
    separator: str  # whitespace that followed it in the source ("" at the very end)

    @property
    def rendered(self) -> str:
        return self.text + self.separator


def _cut_points(text: str) -> list[int]:
    """Offsets right after each sentence end (before the separator)."""
    cuts: list[int] = []
    for m in _BOUNDARY.finditer(text):
        end = m.end() if m.group(0) != "\n" else m.start()
        head = text[:end].rstrip("\"'»”)] ")
        if m.group(0) != "\n" and (_ABBREVIATIONS.search(head) or _looks_like_decimal(text, end)):
            continue
        if not cuts or end > cuts[-1]:
            cuts.append(end)
    return cuts


def _looks_like_decimal(text: str, end: int) -> bool:
    return bool(_NUMBER_DOT.search(text[:end])) and end < len(text) and text[end : end + 1].isdigit()


def _sentences_from(text: str, cuts: list[int]) -> tuple[list[Sentence], int]:
    """Split `text` at `cuts`; returns sentences and the offset where the unconsumed remainder starts."""
    out: list[Sentence] = []
    pos = 0
    for cut in cuts:
        body = text[pos:cut]
        sep_end = cut
        while sep_end < len(text) and text[sep_end].isspace():
            sep_end += 1
        if sep_end == len(text):
            return out, pos  # separator may continue in the next chunk: keep this sentence pending
        if body.strip():
            out.append(Sentence(text=body.strip(), separator=_normal_sep(text[cut:sep_end])))
        pos = sep_end
    return out, pos


def _normal_sep(sep: str) -> str:
    if "\n\n" in sep:
        return "\n\n"
    return "\n" if "\n" in sep else " "


def split_sentences(text: str) -> list[Sentence]:
    """Split a complete answer into sentences (the last one gets an empty separator)."""
    text = text.strip()
    if not text:
        return []
    sentences, pos = _sentences_from(text + "\n", _cut_points(text + "\n"))
    tail = text[pos:].strip()
    if tail:
        sentences.append(Sentence(text=tail, separator=""))
    if sentences:
        sentences[-1] = Sentence(text=sentences[-1].text, separator="")
    return sentences


class SentenceBuffer:
    """Accumulates streamed chunks and releases complete sentences. Owned by a single turn task."""

    def __init__(self, max_pending_chars: int = 1200) -> None:
        self._pending = ""
        self._max = max_pending_chars

    def feed(self, chunk: str) -> list[Sentence]:
        self._pending += chunk
        sentences, pos = _sentences_from(self._pending, _cut_points(self._pending))
        self._pending = self._pending[pos:]
        if len(self._pending) > self._max:  # runaway sentence: release it rather than buffer forever
            sentences.append(Sentence(text=self._pending.strip(), separator=" "))
            self._pending = ""
        return sentences

    def flush(self) -> list[Sentence]:
        rest = self._pending.strip()
        self._pending = ""
        return [Sentence(text=rest, separator="")] if rest else []
