"""P4 evaluation items: what each suite sends through the real pipeline.

  safety   every item of evals/safety/sets whose expected_kinds contain emergency or self_harm (the same
           denominator as the lexicon-only evaluator), plus every hard negative (false positives, not gated)
  quality  answerable gold questions (evals/retrieval/gold), a deterministic sample of the same base questions
           in EN / FR / AR (ordered by SHA-256 of the base id)
  dose     evals/p4/sets/dose.jsonl: synthetic questions whose answers carry doses or quantities with units
  refusal  evals/p4/sets/refusal.jsonl: requests for a diagnosis, a personal dose or a triage verdict
  latency  the first quality questions again, for a latency re-measure in a quiet window (`*_rerun` records)

Quality exclusions (evals/p4/sets/quality_exclusions.jsonl): gold questions whose answer the product may not
take from the live index, by base id (every language), each with its rule and reason. They stay in the
sample and are run, but `answered_rate_answerable` leaves them out (a breakdown record keeps the rate over
every item). Rules: `gold_not_in_index` (the gold chunk is not in the live collection) and
`medication_needs_drug_label` (a medication question by the guard's intent definition, i.e. about a
medicine's side effects, interactions, doses or how a named medicine works, which review C7 answers only from
drug-label passages, while the live index holds none). The rule is applied by reading the question over the
whole pool, never by outcome.

Items are ordered round-robin by language so that `--limit N` keeps the languages balanced.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

from evals.retrieval.gold import load_gold
from evals.safety.sets import HARD_NEGATIVE, load_heldout, load_sets, split_of

LANGS: tuple[str, ...] = ("en", "fr", "ar")
GATED_KINDS: tuple[str, ...] = ("emergency", "self_harm")
SUITES: tuple[str, ...] = ("safety", "quality", "dose", "refusal", "latency")
SETS_DIR = Path(__file__).resolve().parent / "sets"
GOLD_DIR = Path(__file__).resolve().parents[1] / "retrieval" / "gold"
DEFAULT_QUALITY_PER_LANG = 60
_ITEM_FIELDS = frozenset({"id", "lang", "text", "category", "notes", "history"})
EXCLUSIONS_PATH = SETS_DIR / "quality_exclusions.jsonl"
EXCLUSION_RULES: tuple[str, ...] = ("gold_not_in_index", "medication_needs_drug_label")


class ItemFormatError(ValueError):
    """An evals/p4/sets file is malformed."""


@dataclass(frozen=True)
class EvalItem:
    suite: str
    id: str
    lang: str
    turns: tuple[str, ...]  # user messages, oldest first; the last one is the item's question
    category: str = ""
    expected_kinds: frozenset[str] = frozenset()
    split: str = ""
    meta: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def to_dict(self) -> dict[str, object]:
        return {
            "suite": self.suite,
            "id": self.id,
            "lang": self.lang,
            "turns": list(self.turns),
            "category": self.category,
            "expected_kinds": sorted(self.expected_kinds),
            "split": self.split,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> EvalItem:
        turns = raw.get("turns") or []
        kinds = raw.get("expected_kinds") or []
        meta = raw.get("meta") or {}
        assert isinstance(turns, list)
        assert isinstance(kinds, list)
        assert isinstance(meta, dict)
        return cls(
            suite=str(raw["suite"]),
            id=str(raw["id"]),
            lang=str(raw["lang"]),
            turns=tuple(str(t) for t in turns),
            category=str(raw.get("category", "")),
            expected_kinds=frozenset(str(k) for k in kinds),
            split=str(raw.get("split", "")),
            meta=MappingProxyType({str(k): str(v) for k, v in meta.items()}),
        )


def round_robin(items: Iterable[EvalItem]) -> list[EvalItem]:
    """Interleave items by language (en, fr, ar, en, ...), keeping each language's own order."""
    by_lang: dict[str, list[EvalItem]] = {}
    for item in items:
        by_lang.setdefault(item.lang, []).append(item)
    order = [lang for lang in LANGS if lang in by_lang] + sorted(set(by_lang) - set(LANGS))
    out: list[EvalItem] = []
    for i in range(max((len(v) for v in by_lang.values()), default=0)):
        out.extend(by_lang[lang][i] for lang in order if i < len(by_lang[lang]))
    return out


# ---- safety -------------------------------------------------------------------------------------------
def safety_items() -> list[EvalItem]:
    heldout = load_heldout()
    out: list[EvalItem] = []
    for s in load_sets():
        gated = s.expected_kinds & set(GATED_KINDS)
        if not gated and s.category != HARD_NEGATIVE:
            continue
        out.append(
            EvalItem(
                suite="safety",
                id=s.id,
                lang=s.lang,
                turns=s.turns,
                category=s.category,
                expected_kinds=s.expected_kinds,
                split=split_of(s, heldout),
                meta=MappingProxyType({"variety": s.variety}),
            )
        )
    return round_robin(out)


# ---- quality ------------------------------------------------------------------------------------------
def base_id(qid: str) -> str:
    """'g000-P1-en' -> 'g000-P1' (the same question in every language shares the base id)."""
    head, _, tail = qid.rpartition("-")
    return head if tail in LANGS else qid


def _rank(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def quality_items(per_lang: int = DEFAULT_QUALITY_PER_LANG, gold_dir: Path = GOLD_DIR) -> list[EvalItem]:
    rows = [r for r in load_gold(gold_dir) if r.answerable]
    out: list[EvalItem] = []
    for lang in LANGS:
        mine = sorted((r for r in rows if r.language == lang), key=lambda r: (_rank(base_id(r.qid)), r.qid))
        for r in mine[:per_lang]:
            out.append(
                EvalItem(
                    suite="quality",
                    id=r.qid,
                    lang=lang,
                    turns=(r.question,),
                    category="answerable",
                    meta=MappingProxyType(
                        {
                            "relevant_doc_id": r.relevant_doc_id or "",
                            "relevant_chunk_ids": ",".join(r.relevant_chunk_ids),
                            "status": r.status,
                        }
                    ),
                )
            )
    return round_robin(out)


def load_quality_exclusions(path: Path = EXCLUSIONS_PATH) -> Mapping[str, str]:
    """base id -> "rule: reason" for the quality questions left out of answered_rate_answerable."""
    if not path.exists():
        return MappingProxyType({})
    out: dict[str, str] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        where = f"{path.name}:{n}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ItemFormatError(f"{where}: invalid JSON ({exc.msg})") from exc
        if not isinstance(raw, dict) or set(raw) != {"base_id", "rule", "reason"}:
            raise ItemFormatError(f"{where}: fields must be exactly base_id, rule, reason")
        base, rule, reason = (str(raw[k]).strip() for k in ("base_id", "rule", "reason"))
        if rule not in EXCLUSION_RULES or not base or len(reason) < 20:
            raise ItemFormatError(f"{where}: rule must be one of {EXCLUSION_RULES}, with a base_id, a reason")
        if base in out:
            raise ItemFormatError(f"{where}: duplicate base_id {base}")
        out[base] = f"{rule}: {reason}"
    return MappingProxyType(out)


def is_excluded(item: EvalItem, exclusions: Mapping[str, str]) -> bool:
    return item.suite in ("quality", "latency") and base_id(item.id) in exclusions


# ---- dose / refusal (evals/p4/sets) -------------------------------------------------------------------
def _parse_line(raw: object, suite: str, where: str) -> EvalItem:
    if not isinstance(raw, dict):
        raise ItemFormatError(f"{where}: each line must be a JSON object")
    extra = set(raw) - _ITEM_FIELDS
    if extra:
        raise ItemFormatError(f"{where}: unknown fields {sorted(extra)}")
    for key in ("id", "lang", "text", "category"):
        if not isinstance(raw.get(key), str) or not str(raw[key]).strip():
            raise ItemFormatError(f"{where}: '{key}' must be a non-empty string")
    if raw["lang"] not in LANGS or not str(raw["id"]).startswith(f"{raw['lang']}-"):
        raise ItemFormatError(f"{where}: lang must be one of {LANGS} and prefix the id")
    history = raw.get("history", [])
    if not isinstance(history, list) or not all(isinstance(h, str) and h.strip() for h in history):
        raise ItemFormatError(f"{where}: 'history' must be a list of non-empty strings")
    return EvalItem(
        suite=suite,
        id=str(raw["id"]),
        lang=str(raw["lang"]),
        turns=(*history, str(raw["text"])),
        category=str(raw["category"]),
        meta=MappingProxyType({"notes": str(raw.get("notes", ""))}),
    )


def load_item_file(path: Path, suite: str, categories: Sequence[str]) -> list[EvalItem]:
    items: list[EvalItem] = []
    seen: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        where = f"{path.name}:{n}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ItemFormatError(f"{where}: invalid JSON ({exc.msg})") from exc
        item = _parse_line(raw, suite, where)
        if item.category not in categories:
            raise ItemFormatError(f"{where}: category must be one of {tuple(categories)}")
        if item.id in seen:
            raise ItemFormatError(f"{where}: duplicate id {item.id}")
        seen.add(item.id)
        items.append(item)
    return round_robin(items)


DOSE_CATEGORIES: tuple[str, ...] = ("numeric_fact", "supplement_dose", "drug_label_dose")
REFUSAL_CATEGORIES: tuple[str, ...] = ("diagnosis", "personal_dosing", "triage")


def dose_items(path: Path = SETS_DIR / "dose.jsonl") -> list[EvalItem]:
    return load_item_file(path, "dose", DOSE_CATEGORIES)


def refusal_items(path: Path = SETS_DIR / "refusal.jsonl") -> list[EvalItem]:
    return load_item_file(path, "refusal", REFUSAL_CATEGORIES)


def suite_items(suite: str, *, quality_per_lang: int = DEFAULT_QUALITY_PER_LANG) -> list[EvalItem]:
    if suite == "safety":
        return safety_items()
    if suite == "quality":
        return quality_items(quality_per_lang)
    if suite == "dose":
        return dose_items()
    if suite == "refusal":
        return refusal_items()
    if suite == "latency":  # the same quality questions, asked again in a quiet window (latency only)
        return [replace(i, suite="latency") for i in quality_items(quality_per_lang)]
    raise ValueError(f"unknown suite {suite!r}")
