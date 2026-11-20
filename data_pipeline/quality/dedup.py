"""Exact and near-duplicate detection.

Exact: sha256 of the normalised body (section text only, titles excluded) so two pages with the same text
but different titles collapse. Near: MinHash (128 permutations) over word 5-shingles with LSH banding
(16 bands x 8 rows) to find candidates, confirmed by the signature-estimated Jaccard similarity.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from core.schemas.document import Document
from data_pipeline.quality.fastpath import fast_detection_form as detection_form

NUM_PERM = 128
BANDS = 16
ROWS = NUM_PERM // BANDS
SHINGLE = 5
DEFAULT_THRESHOLD = 0.85
_rng = np.random.default_rng(20261115)  # fixed seed: signatures are reproducible between runs
_A = _rng.integers(1, 2**62, size=NUM_PERM, dtype=np.uint64) | np.uint64(1)
_B = _rng.integers(0, 2**62, size=NUM_PERM, dtype=np.uint64)


def body_text(doc: Document) -> str:
    return "\n".join(section.text for section in doc.sections)


def exact_key(doc: Document) -> str:
    return hashlib.sha256(detection_form(body_text(doc)).encode("utf-8")).hexdigest()


def shingles(text: str, size: int = SHINGLE) -> set[int]:
    words = detection_form(text).split()
    if len(words) < size:
        words = words + [""] * (size - len(words))
    out: set[int] = set()
    for i in range(len(words) - size + 1):
        gram = " ".join(words[i : i + size]).encode("utf-8")
        out.add(int.from_bytes(hashlib.blake2b(gram, digest_size=8).digest(), "little"))
    return out


def signature(text: str) -> np.ndarray:
    hashes = np.fromiter(shingles(text), dtype=np.uint64)
    mixed = hashes[:, None] * _A[None, :] + _B[None, :]  # wraps modulo 2**64 on purpose
    return np.asarray(mixed.min(axis=0))


def estimated_jaccard(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(a == b))


@dataclass(frozen=True)
class DuplicateGroup:
    kept: str  # doc_id that is kept
    dropped: tuple[str, ...]
    kind: str  # "exact" | "near"


def find_duplicates(
    documents: Sequence[Document], *, threshold: float = DEFAULT_THRESHOLD
) -> tuple[frozenset[str], list[DuplicateGroup]]:
    """Return (doc_ids to drop, groups). The first document in input order is kept in each group."""
    dropped: set[str] = set()
    groups: dict[tuple[str, str], list[str]] = {}
    seen_exact: dict[str, str] = {}
    survivors: list[Document] = []
    for doc in documents:
        key = exact_key(doc)
        if key in seen_exact:
            dropped.add(doc.doc_id)
            groups.setdefault((seen_exact[key], "exact"), []).append(doc.doc_id)
        else:
            seen_exact[key] = doc.doc_id
            survivors.append(doc)
    near_drop, near_groups = _near_duplicates(survivors, threshold)
    dropped |= near_drop
    for kept, members in near_groups.items():
        groups.setdefault((kept, "near"), []).extend(members)
    return frozenset(dropped), [DuplicateGroup(k, tuple(v), kind) for (k, kind), v in groups.items()]


def _near_duplicates(docs: Sequence[Document], threshold: float) -> tuple[set[str], dict[str, list[str]]]:
    buckets: dict[tuple[int, bytes], list[int]] = {}
    signatures = [signature(body_text(d)) for d in docs]
    dropped: set[str] = set()
    groups: dict[str, list[str]] = {}
    for idx, sig in enumerate(signatures):
        match = _first_match(idx, sig, signatures, buckets, dropped, threshold)
        if match is not None:
            keeper = docs[match].doc_id
            dropped.add(docs[idx].doc_id)
            groups.setdefault(keeper, []).append(docs[idx].doc_id)
            continue
        for band in range(BANDS):
            key = (band, sig[band * ROWS : (band + 1) * ROWS].tobytes())
            buckets.setdefault(key, []).append(idx)
    return dropped, groups


def _first_match(
    idx: int,
    sig: np.ndarray,
    signatures: Sequence[np.ndarray],
    buckets: dict[tuple[int, bytes], list[int]],
    dropped: set[str],
    threshold: float,
) -> int | None:
    candidates: set[int] = set()
    for band in range(BANDS):
        candidates.update(buckets.get((band, sig[band * ROWS : (band + 1) * ROWS].tobytes()), ()))
    best: tuple[float, int] | None = None
    for cand in sorted(candidates):
        score = estimated_jaccard(sig, signatures[cand])
        if score >= threshold and (best is None or score > best[0]):
            best = (score, cand)
    return best[1] if best else None


def near_duplicate_rate(documents: Iterable[Document], *, threshold: float = DEFAULT_THRESHOLD) -> float:
    """Share of documents with a near-duplicate partner within the given sample (exact copies included)."""
    docs = list(documents)
    if not docs:
        return 0.0
    dropped, _ = find_duplicates(docs, threshold=threshold)
    return len(dropped) / len(docs)
