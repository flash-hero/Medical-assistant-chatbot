"""Selection logic for openFDA drug labels: one label per active-ingredient set.

Pure functions plus one small mutable accumulator (`IngredientIndex`) that keeps, per ingredient set, only the
best candidate seen so far, so a 5 GB JSON stream never has to fit in RAM.

Ranking of candidates inside one ingredient set (best first):
  1. product type: human prescription label, then human OTC label (everything else is ignored)
  2. number of patient-relevant sections present, then their total length (richest label)
  3. newest effective_time
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# Patient-relevant label fields, in the order they are emitted inside a Document.
KEEP_FIELDS: tuple[str, ...] = (
    "boxed_warning",
    "indications_and_usage",
    "purpose",
    "active_ingredient",
    "dosage_and_administration",
    "dosage_forms_and_strengths",
    "contraindications",
    "do_not_use",
    "warnings_and_cautions",
    "warnings",
    "precautions",
    "general_precautions",
    "when_using",
    "ask_doctor",
    "ask_doctor_or_pharmacist",
    "stop_use",
    "adverse_reactions",
    "drug_interactions",
    "use_in_specific_populations",
    "pregnancy",
    "pregnancy_or_breast_feeding",
    "lactation",
    "nursing_mothers",
    "pediatric_use",
    "geriatric_use",
    "overdosage",
    "information_for_patients",
    "patient_medication_information",
    "spl_patient_package_insert",
    "spl_medguide",
    "instructions_for_use",
    "keep_out_of_reach_of_children",
)
# Section fields whose companion "<field>_table" HTML is rendered as text and appended.
TABLE_FIELDS = frozenset(
    {
        "indications_and_usage",
        "dosage_and_administration",
        "dosage_forms_and_strengths",
        "contraindications",
        "warnings_and_cautions",
        "adverse_reactions",
        "drug_interactions",
        "use_in_specific_populations",
    }
)
# Explicitly dropped (documented): clinical_pharmacology, nonclinical_toxicology, clinical_studies,
# how_supplied, references, package_label_principal_display_panel, description, mechanism_of_action, ...
CAPS: Mapping[str, int] = {"adverse_reactions": 6000}
DEFAULT_CAP = 14000
PRODUCT_RANK = {"HUMAN PRESCRIPTION DRUG": 0, "HUMAN OTC DRUG": 1}
_SALT_WORDS = frozenset(
    [
        "hydrochloride",
        "hcl",
        "sodium",
        "potassium",
        "calcium",
        "magnesium",
        "sulfate",
        "sulphate",
        "phosphate",
        "maleate",
        "mesylate",
        "besylate",
        "tartrate",
        "bitartrate",
        "succinate",
        "fumarate",
        "citrate",
        "acetate",
        "bromide",
        "hydrobromide",
        "chloride",
        "nitrate",
        "dihydrate",
        "monohydrate",
        "anhydrous",
        "hemihydrate",
        "trihydrate",
        "disodium",
        "dipotassium",
        "tosylate",
        "hyclate",
        "lactate",
        "gluconate",
        "oxide",
        "carbonate",
        "bicarbonate",
        "hydroxide",
        "propionate",
        "valerate",
        "dipropionate",
    ]
)
_HEADING_PREFIX: Mapping[str, str] = {
    "boxed_warning": r"boxed warning|warning",
    "indications_and_usage": r"\d*\.?\s*indications?(?: ?(?:&|and) ?usage)?|uses?",
    "dosage_and_administration": r"\d*\.?\s*dosage(?: ?(?:&|and) ?administration)?|directions?",
    "dosage_forms_and_strengths": r"\d*\.?\s*dosage forms(?: ?(?:&|and) ?strengths)?",
    "contraindications": r"\d*\.?\s*contraindications?",
    "warnings_and_cautions": r"\d*\.?\s*warnings(?: ?(?:&|and) ?(?:cautions|precautions))?",
    "warnings": r"warnings?",
    "precautions": r"precautions?",
    "adverse_reactions": r"\d*\.?\s*adverse reactions?",
    "drug_interactions": r"\d*\.?\s*drug interactions?",
    "overdosage": r"overdosage|overdose",
    "pregnancy": r"pregnancy",
    "pediatric_use": r"pediatric use",
    "geriatric_use": r"geriatric use",
    "information_for_patients": r"information for patients(?:/caregivers)?",
    "purpose": r"purposes?",
    "do_not_use": r"do not use",
    "ask_doctor": r"ask (?:a )?doctor",
    "stop_use": r"stop use",
    "keep_out_of_reach_of_children": r"keep out of reach of children",
}
_PREFIX_RES = {
    name: re.compile(rf"^\s*(?:{pattern})\b\s*[:.\-]?\s*", re.IGNORECASE)
    for name, pattern in _HEADING_PREFIX.items()
}
_SUBSECTION_BREAK = re.compile(r"(?<=[.!?])\s+(?=\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\s+[A-Z])")
_THIRD_PARTY = re.compile(r"not in the public domain|third[- ]party copy ?rights may apply", re.IGNORECASE)


def first(values: object) -> str:
    if isinstance(values, list) and values:
        return str(values[0]).strip()
    return ""


def as_list(values: object) -> list[str]:
    return [str(v).strip() for v in values if str(v).strip()] if isinstance(values, list) else []


def normalise_ingredient(name: str) -> str:
    """Lower-case, drop salt/hydrate words (unless that would empty the name), collapse spaces."""
    tokens = re.findall(r"[a-z0-9\-]+", name.casefold())
    kept = [t for t in tokens if t not in _SALT_WORDS]
    return " ".join(kept or tokens)


def ingredient_key(openfda: Mapping[str, object]) -> str:
    names = as_list(openfda.get("substance_name")) or as_list(openfda.get("generic_name"))
    normalised = sorted({normalise_ingredient(n) for n in names if n})
    return " + ".join(n for n in normalised if n)


def field_text(raw: object, name: str) -> str:
    """Join the list of strings of one label field, drop the repeated heading, break sub-sections."""
    parts = [str(p).strip() for p in raw] if isinstance(raw, list) else ([str(raw).strip()] if raw else [])
    parts = [p for p in parts if p]
    if not parts:
        return ""
    pattern = _PREFIX_RES.get(name)
    if pattern is not None:
        parts[0] = pattern.sub("", parts[0], count=1)
    text = "\n\n".join(parts)
    return _SUBSECTION_BREAK.sub("\n\n", text).strip()


def cap_text(text: str, limit: int) -> tuple[str, bool]:
    """Truncate at a sentence/paragraph boundary near the limit. Returns (text, was_truncated)."""
    if len(text) <= limit:
        return text, False
    window = text[:limit]
    cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("; "))
    return (window[: cut + 1] if cut > limit // 2 else window).rstrip(), True


@dataclass(frozen=True)
class LabelCandidate:
    set_id: str
    effective_time: str
    product_type: str
    generic_name: str
    brand_name: str
    manufacturer: str
    rxcui: tuple[str, ...]
    route: tuple[str, ...]
    sections: tuple[tuple[str, str], ...]  # (field, text) in KEEP_FIELDS order
    truncated: tuple[str, ...] = ()

    def rank(self) -> tuple[int, int, int, str]:
        return (
            -PRODUCT_RANK[self.product_type],
            len(self.sections),
            sum(len(t) for _, t in self.sections),
            self.effective_time,
        )


@dataclass
class IngredientGroup:
    key: str
    best: LabelCandidate | None = None
    merged: int = 0
    brands: Counter[str] = field(default_factory=Counter)
    generics: Counter[str] = field(default_factory=Counter)
    substances: Counter[str] = field(default_factory=Counter)
    types: Counter[str] = field(default_factory=Counter)


def build_candidate(record: Mapping[str, object]) -> LabelCandidate | None:
    """Reduce one raw openFDA label record to the patient-relevant candidate (None when not eligible)."""
    openfda = record.get("openfda")
    if not isinstance(openfda, dict) or not openfda:
        return None
    product_type = first(openfda.get("product_type"))
    if product_type not in PRODUCT_RANK:
        return None
    sections: list[tuple[str, str]] = []
    truncated: list[str] = []
    for name in KEEP_FIELDS:
        text = field_text(record.get(name), name)
        if name in TABLE_FIELDS and record.get(f"{name}_table"):
            text = (text + "\n\n" + _tables_text(record.get(f"{name}_table"))).strip()
        if not text or _THIRD_PARTY.search(text):
            continue
        text, was_cut = cap_text(text, CAPS.get(name, DEFAULT_CAP))
        sections.append((name, text))
        if was_cut:
            truncated.append(name)
    set_id = first(openfda.get("spl_set_id")) or str(record.get("set_id", ""))
    if not sections or not set_id:
        return None
    return LabelCandidate(
        set_id=set_id,
        effective_time=str(record.get("effective_time", "")),
        product_type=product_type,
        generic_name=first(openfda.get("generic_name")) or first(openfda.get("substance_name")),
        brand_name=first(openfda.get("brand_name")),
        manufacturer=first(openfda.get("manufacturer_name")),
        rxcui=tuple(as_list(openfda.get("rxcui"))),
        route=tuple(as_list(openfda.get("route"))),
        sections=tuple(sections),
        truncated=tuple(truncated),
    )


def _tables_text(raw: object) -> str:
    from data_pipeline.parsers.htmltext import iter_events, parse_fragment

    blocks: list[str] = []
    for markup in raw if isinstance(raw, list) else [raw]:
        try:
            blocks.extend(e.text for e in iter_events(parse_fragment(str(markup))) if e.kind == "block")
        except ValueError:
            continue
    return "\n\n".join(blocks)


class IngredientIndex:
    """Streaming accumulator: feed it raw records, read the chosen label per ingredient set at the end."""

    def __init__(self) -> None:
        self.groups: dict[str, IngredientGroup] = {}
        self._seen: dict[str, str] = {}
        self.stats: Counter[str] = Counter()

    def add(self, record: Mapping[str, object]) -> None:
        self.stats["records"] += 1
        openfda = record.get("openfda")
        key = ingredient_key(openfda) if isinstance(openfda, dict) else ""
        if not key:
            self.stats["no_openfda_identity"] += 1
            return
        candidate = build_candidate(record)
        if candidate is None:
            self.stats["not_eligible"] += 1
            return
        previous_time = self._seen.get(candidate.set_id)
        if previous_time is not None:
            self.stats["duplicate_set_id"] += 1
            if candidate.effective_time <= previous_time:
                return
        self._seen[candidate.set_id] = candidate.effective_time
        group = self.groups.setdefault(key, IngredientGroup(key))
        if previous_time is None:
            group.merged += 1
        self._tally(group, candidate, openfda if isinstance(openfda, dict) else {})
        if (
            group.best is None
            or candidate.rank() > group.best.rank()
            or candidate.set_id == group.best.set_id
        ):
            group.best = candidate

    @staticmethod
    def _tally(group: IngredientGroup, candidate: LabelCandidate, openfda: Mapping[str, object]) -> None:
        group.types[candidate.product_type] += 1
        group.brands.update(b for b in as_list(openfda.get("brand_name")))
        group.generics.update(as_list(openfda.get("generic_name")))
        group.substances.update(as_list(openfda.get("substance_name")))

    def chosen(self) -> Iterable[IngredientGroup]:
        return (g for g in self.groups.values() if g.best is not None)
