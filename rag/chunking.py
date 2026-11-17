"""Structure-aware chunker: core.schemas.document.Document -> tuple[Chunk, ...].

Rules
  - never cross section boundaries; consecutive tiny sibling sections (same parent heading, same kind) are
    merged into one group, except for drug labels, which always keep one or more chunks per section
  - target 350-500 estimated tokens, ~10% overlap made of whole sentences, lists and tables kept whole
  - chunk text is an exact substring of the (group) text, so citations quote the source verbatim
  - deterministic ids: chunk_id = f"{doc_id}#{section_id}#{ordinal}", parent_id = f"{doc_id}#{section_id}"
  - checksum = sha256(context_header + "\\n" + text), the embedding-cache key
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from core.schemas.document import Chunk, Document, Section
from core.schemas.source import ContentType
from rag.segment import segment
from rag.tokens import estimate_tokens


@dataclass(frozen=True)
class ChunkerConfig:
    min_tokens: int = 350
    max_tokens: int = 500
    hard_max_tokens: int = 600  # only to keep a runt chunk from standing alone
    runt_tokens: int = 80
    overlap_ratio: float = 0.10
    small_section_tokens: int = 120
    no_merge_content_types: frozenset[ContentType] = field(
        default_factory=lambda: frozenset({ContentType.DRUG_LABEL})
    )

    @property
    def overlap_tokens(self) -> int:
        return int(self.max_tokens * self.overlap_ratio)


DEFAULT_CONFIG = ChunkerConfig()


@dataclass(frozen=True)
class SectionGroup:
    section_id: str
    heading_path: tuple[str, ...]
    text: str
    kind: str | None


# ---- range planning ----------------------------------------------------------------------------------
def _overlap_start(tokens: Sequence[int], start: int, end: int, cfg: ChunkerConfig) -> int:
    """First unit of the next chunk: trailing whole units of [start, end) worth <= overlap_tokens, reduced
    until the overlap plus the next new unit fits in max_tokens."""
    s, overlap = end, 0
    while s - 1 > start and overlap + tokens[s - 1] <= cfg.overlap_tokens:
        s -= 1
        overlap += tokens[s]
    while s < end and overlap + tokens[end] > cfg.max_tokens:
        overlap -= tokens[s]
        s += 1
    return s


def _goal(tokens: Sequence[int], cfg: ChunkerConfig) -> float:
    total, overlap = sum(tokens), cfg.overlap_tokens
    target = (cfg.min_tokens + cfg.max_tokens) / 2
    n_chunks = max(2, math.ceil((total - overlap) / max(1.0, target - overlap)))
    per_chunk = (total + (n_chunks - 1) * overlap) / n_chunks
    return min(float(cfg.max_tokens), max(float(cfg.min_tokens), per_chunk))


def _absorb_tail(acc: int, rest: int, cfg: ChunkerConfig) -> bool:
    if rest <= 0:
        return False
    fits_soft = rest < cfg.min_tokens / 2 and acc + rest <= cfg.max_tokens
    fits_hard = rest < cfg.runt_tokens and acc + rest <= cfg.hard_max_tokens
    return fits_soft or fits_hard


def plan_ranges(tokens: Sequence[int], cfg: ChunkerConfig = DEFAULT_CONFIG) -> list[tuple[int, int]]:
    """Plan unit ranges [start, end) per chunk. Consecutive ranges overlap by whole units only."""
    n = len(tokens)
    if n == 0:
        return []
    if sum(tokens) <= cfg.max_tokens:
        return [(0, n)]
    goal = _goal(tokens, cfg)
    ranges: list[tuple[int, int]] = []
    start, prev_end = 0, 0
    while True:
        end, acc = start, 0
        while end < n:
            forced = end <= prev_end  # overlap units plus at least one new unit
            limit = cfg.max_tokens if acc >= cfg.runt_tokens else cfg.hard_max_tokens
            if not forced and (acc + tokens[end] > limit or acc >= goal):
                break
            acc += tokens[end]
            end += 1
        if _absorb_tail(acc, sum(tokens[end:]), cfg):
            end = n  # absorb a tiny tail instead of emitting a runt chunk
        ranges.append((start, end))
        if end >= n:
            return ranges
        start, prev_end = _overlap_start(tokens, start, end, cfg), end


# ---- headers -----------------------------------------------------------------------------------------
def publisher_label(attribution: str, fallback: str) -> str:
    """'Source: MedlinePlus, U.S. National Library of Medicine' -> 'MedlinePlus'."""
    text = attribution.strip()
    head, sep, tail = text.partition(":")
    if sep and head.strip().casefold() == "source":
        text = tail.strip()
    label = text.split(",")[0].strip()
    return label or fallback


def context_header(
    publisher: str, title: str, heading_path: Sequence[str], language: str, reviewed_on: date | None
) -> str:
    path = list(heading_path)
    if path and path[0].strip().casefold() == title.strip().casefold():
        path = path[1:]
    parts = [publisher, " > ".join([title, *path]), str(language)]
    if reviewed_on is not None:
        parts.append(f"reviewed {reviewed_on.isoformat()}")
    return " | ".join(parts)


# ---- section grouping --------------------------------------------------------------------------------
def _common_prefix(paths: Sequence[tuple[str, ...]]) -> tuple[str, ...]:
    prefix: list[str] = []
    for parts in zip(*paths, strict=False):
        if any(p != parts[0] for p in parts):
            break
        prefix.append(parts[0])
    return tuple(prefix)


def _group_tokens(group: Sequence[Section], lang: str) -> int:
    return sum(estimate_tokens(s.text, lang) + len(s.heading_path[-1:]) * 4 for s in group)


def _can_merge(group: Sequence[Section], sec: Section, lang: str, cfg: ChunkerConfig) -> bool:
    """A tiny section joins its neighbour within the same document root ("Inheritance pattern: Autosomal
    dominant." should not be a chunk of its own). Each group holds at most one non-tiny section."""
    if group[0].heading_path[:1] != sec.heading_path[:1]:
        return False
    small = cfg.small_section_tokens
    return _group_tokens([sec], lang) < small or _group_tokens(group, lang) < small


def _group_kind(sections: Sequence[Section]) -> str | None:
    kinds = list(dict.fromkeys(s.kind for s in sections if s.kind))
    return "+".join(kinds) if kinds else None


def _to_group(sections: Sequence[Section]) -> SectionGroup:
    if len(sections) == 1:
        s = sections[0]
        return SectionGroup(s.section_id, s.heading_path, s.text.strip(), s.kind)
    common = _common_prefix([s.heading_path for s in sections])
    parts = []
    for s in sections:
        own = s.heading_path[len(common) :]
        parts.append(f"{' > '.join(own)}\n{s.text.strip()}" if own else s.text.strip())
    sid = "+".join(s.section_id for s in sections)
    return SectionGroup(sid, common, "\n\n".join(parts), _group_kind(sections))


def group_sections(doc: Document, cfg: ChunkerConfig = DEFAULT_CONFIG) -> tuple[SectionGroup, ...]:
    sections = [s for s in doc.sections if s.text.strip()]
    if doc.content_type in cfg.no_merge_content_types:
        return tuple(_to_group([s]) for s in sections)
    groups: list[list[Section]] = []
    for sec in sections:
        if groups and _can_merge(groups[-1], sec, str(doc.language), cfg):
            groups[-1] = [*groups[-1], sec]
        else:
            groups.append([sec])
    return tuple(_to_group(g) for g in groups)


# ---- chunks ------------------------------------------------------------------------------------------
def _make_chunk(doc: Document, group: SectionGroup, ordinal: int, text: str, header: str) -> Chunk:
    parent_id = f"{doc.doc_id}#{group.section_id}"
    return Chunk(
        chunk_id=f"{parent_id}#{ordinal}",
        doc_id=doc.doc_id,
        source_id=doc.source_id,
        section_id=group.section_id,
        parent_id=parent_id,
        ordinal=ordinal,
        heading_path=group.heading_path,
        text=text,
        context_header=header,
        title=doc.title,
        url=doc.url,
        language=doc.language,
        content_type=doc.content_type,
        trust_tier=doc.trust_tier,
        reuse_mode=doc.reuse_mode,
        attribution=doc.attribution,
        reviewed_on=doc.reviewed_on,
        section_kind=group.kind,
        token_estimate=estimate_tokens(text, str(doc.language)),
        checksum=hashlib.sha256(f"{header}\n{text}".encode()).hexdigest(),
    )


def chunk_group(doc: Document, group: SectionGroup, publisher: str, cfg: ChunkerConfig) -> list[Chunk]:
    lang = str(doc.language)
    units = segment(group.text, lang, max_unit_tokens=cfg.max_tokens)
    header = context_header(publisher, doc.title, group.heading_path, lang, doc.reviewed_on)
    ranges = plan_ranges([u.tokens for u in units], cfg)
    return [
        _make_chunk(doc, group, i, group.text[units[s].start : units[e - 1].end], header)
        for i, (s, e) in enumerate(ranges)
    ]


def chunk_document(
    doc: Document, *, publisher: str | None = None, config: ChunkerConfig = DEFAULT_CONFIG
) -> tuple[Chunk, ...]:
    label = publisher or publisher_label(doc.attribution, doc.source_id)
    chunks: list[Chunk] = []
    for group in group_sections(doc, config):
        chunks.extend(chunk_group(doc, group, label, config))
    return tuple(chunks)
