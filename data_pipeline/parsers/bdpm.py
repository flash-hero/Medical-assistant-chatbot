"""French public medicines database (BDPM) open-data files -> one Document per marketed medicine.

What the files contain (https://base-donnees-publique.medicaments.gouv.fr/telechargement, read 2026-11-16):
tab-separated tables, windows-1252, no header row, monthly update. They carry facts, not prose: the name,
form, routes and holder of each speciality (CIS_bdpm), its composition (CIS_COMPO), prescription conditions
(CIS_CPD), the HAS Transparency Commission opinions on "service medical rendu" with a short free-text
rationale (CIS_HAS_SMR) and the generic group (CIS_GENER). They do NOT contain the summary of product
characteristics or the package leaflet (neither indications, posology nor side effects), so a BDPM document
answers "what is in this medicine, how is it dispensed, what did the HAS say about its benefit", never "how
do I take it".

Licence: Licence Ouverte (Etalab 1.0), commercial reuse allowed with the source and the date of the last
update; the download page adds "do not alter the data or distort its meaning", hence reuse_mode quote_only.
The text of each document is a fixed French template around the unmodified field values.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import structlog

from core.schemas.document import Document, Section
from core.schemas.source import ContentType, Language, SourceRecord
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.fetch.naming import url_to_relpath
from data_pipeline.parsers.common import build_document
from data_pipeline.paths import DataPaths

SOURCE_ID = "bdpm"
BASE = "https://base-donnees-publique.medicaments.gouv.fr"
FILES: tuple[str, ...] = (
    "CIS_bdpm",
    "CIS_COMPO_bdpm",
    "CIS_HAS_SMR_bdpm",
    "CIS_CPD_bdpm",
    "CIS_GENER_bdpm",
)
FETCH_CONFIG = FetchConfig(default_rps=0.5, timeout_s=120.0)
BUILD_OPTIONS = {"min_chars": 120}
ACTIVE_STATUS = "Autorisation active"
MARKETED = "Commercialisée"
MAX_SMR_OPINIONS = 3
ENCODING = "cp1252"
_TAGS = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<br\s*/?>", re.I)
_GENERIC_TYPES = {
    "0": "princeps (médicament de référence)",
    "1": "générique",
    "2": "générique par complémentarité posologique",
    "3": "générique substituable",
    "4": "générique substituable",
}
log = structlog.get_logger(__name__)


def file_url(name: str) -> str:
    return f"{BASE}/download/file/{name}.txt"


def page_url(cis: str) -> str:
    return f"{BASE}/medicament/{cis}/extrait"


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> int:
    """Download the five tables. `limit` is ignored: the files are small and only meaningful whole."""
    ok = 0
    for name in FILES:
        result = await fetcher.fetch(file_url(name), refresh=True)
        if result.path is None:
            raise RuntimeError(f"cannot download {name}: HTTP {result.status}")
        ok += 1
    return ok


def read_table(path: Path) -> list[list[str]]:
    """Tab-separated rows of a BDPM file (windows-1252, CRLF); blank lines are skipped."""
    text = path.read_bytes().decode(ENCODING, errors="replace")
    return [line.split("\t") for line in text.splitlines() if line.strip()]


def clean_text(value: str) -> str:
    """BDPM free text uses <br> for line breaks; any other markup is removed."""
    with_breaks = _BREAK.sub("\n", value)
    lines = (" ".join(_TAGS.sub("", line).split()) for line in with_breaks.split("\n"))
    return "\n".join(line for line in lines if line)


def parse_fr_date(text: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class Speciality:
    cis: str
    name: str
    form: str
    routes: tuple[str, ...]
    status: str
    procedure: str
    marketing: str
    authorised_on: date | None
    holder: str
    enhanced_monitoring: bool


@dataclass
class Tables:
    specialities: list[Speciality] = field(default_factory=list)
    composition: dict[str, list[list[str]]] = field(default_factory=lambda: defaultdict(list))
    smr: dict[str, list[list[str]]] = field(default_factory=lambda: defaultdict(list))
    prescription: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    generics: dict[str, list[list[str]]] = field(default_factory=lambda: defaultdict(list))


def _speciality(row: Sequence[str]) -> Speciality | None:
    if len(row) < 12 or not row[0].strip() or not row[1].strip():
        return None
    return Speciality(
        cis=row[0].strip(),
        name=clean_text(row[1]),
        form=row[2].strip(),
        routes=tuple(r.strip() for r in row[3].split(";") if r.strip()),
        status=row[4].strip(),
        procedure=row[5].strip(),
        marketing=row[6].strip(),
        authorised_on=parse_fr_date(row[7]),
        holder=" ".join(row[10].split()),
        enhanced_monitoring=row[11].strip().lower() == "oui",
    )


def load_tables(raw_dir: Path) -> Tables:
    def table(name: str) -> list[list[str]]:
        return read_table(raw_dir / url_to_relpath(file_url(name)))

    tables = Tables()
    tables.specialities = [s for s in map(_speciality, table("CIS_bdpm")) if s]
    for row in table("CIS_COMPO_bdpm"):
        if len(row) >= 7:
            tables.composition[row[0].strip()].append(row)
    for row in table("CIS_HAS_SMR_bdpm"):
        if len(row) >= 6:
            tables.smr[row[0].strip()].append(row)
    for row in table("CIS_CPD_bdpm"):
        if len(row) >= 2 and row[1].strip():
            tables.prescription[row[0].strip()].append(row[1].strip())
    for row in table("CIS_GENER_bdpm"):
        if len(row) >= 4:
            tables.generics[row[2].strip()].append(row)
    return tables


# ---- sections -------------------------------------------------------------------------------------
def _presentation(spec: Speciality) -> str:
    lines = [f"{spec.name}.", f"Forme pharmaceutique : {spec.form}."]
    if spec.routes:
        lines.append(f"Voie(s) d'administration : {', '.join(spec.routes)}.")
    if spec.holder:
        lines.append(f"Titulaire de l'autorisation de mise sur le marché : {spec.holder}.")
    lines.append(f"Statut administratif : {spec.status}. Procédure d'autorisation : {spec.procedure}.")
    if spec.authorised_on:
        lines.append(
            f"Date d'autorisation de mise sur le marché : {spec.authorised_on.strftime('%d/%m/%Y')}."
        )
    lines.append(f"État de commercialisation : {spec.marketing}.")
    if spec.enhanced_monitoring:
        lines.append("Ce médicament fait l'objet d'une surveillance renforcée.")
    return "\n\n".join(lines)


def _composition(rows: Sequence[Sequence[str]]) -> tuple[str, list[str]]:
    lines: list[str] = []
    substances: list[str] = []
    for row in rows:
        element, name, dosage, reference, nature = (
            c.strip() for c in (row[1], row[3], row[4], row[5], row[6])
        )
        label = "Substance active" if nature == "SA" else "Fraction thérapeutique"
        quantity = " ".join(filter(None, [dosage, f"pour {reference}" if reference else ""]))
        lines.append(f"- {label} ({element}) : {name}" + (f" : {quantity}" if quantity else ""))
        if nature == "SA":
            substances.append(name)
    return "\n".join(lines), substances


def _smr_text(rows: Sequence[Sequence[str]]) -> str:
    ordered = sorted(rows, key=lambda r: parse_fr_date(r[3]) or date.min, reverse=True)[:MAX_SMR_OPINIONS]
    blocks: list[str] = []
    for row in ordered:
        when = parse_fr_date(row[3])
        stamp = when.strftime("%d/%m/%Y") if when else row[3].strip()
        blocks.append(
            f"Avis de la Commission de la transparence du {stamp} ({row[2].strip()}), "
            f"niveau de SMR : {row[4].strip()}.\n{clean_text(row[5])}"
        )
    return "\n\n".join(blocks)


def _generic_text(rows: Sequence[Sequence[str]]) -> str:
    lines = []
    for row in rows:
        kind = _GENERIC_TYPES.get(row[3].strip(), "")
        suffix = f" Cette spécialité est un(e) {kind}." if kind else ""
        lines.append(f"Groupe générique n° {row[0].strip()} : {clean_text(row[1])}.{suffix}")
    return "\n\n".join(lines)


def _sections(spec: Speciality, tables: Tables) -> tuple[tuple[Section, ...], list[str]]:
    path = (spec.name,)
    parts: list[tuple[str, str, str]] = [("summary", "", _presentation(spec))]
    substances: list[str] = []
    if comp := tables.composition.get(spec.cis):
        text, substances = _composition(comp)
        parts.append(("composition", "Composition", text))
    if rules := tables.prescription.get(spec.cis):
        parts.append(
            (
                "prescription",
                "Conditions de prescription et de délivrance",
                "\n".join(f"- {r}" for r in rules),
            )
        )
    if opinions := tables.smr.get(spec.cis):
        parts.append(("smr", "Avis de la HAS sur le service médical rendu (SMR)", _smr_text(opinions)))
    if groups := tables.generics.get(spec.cis):
        parts.append(("generic", "Groupe générique", _generic_text(groups)))
    sections = tuple(
        Section(section_id=f"s{i}", heading_path=path + ((head,) if head else ()), text=text, kind=kind)
        for i, (kind, head, text) in enumerate(parts)
        if text.strip()
    )
    return sections, substances


def speciality_to_document(
    spec: Speciality, tables: Tables, record: SourceRecord, retrieved_at: datetime
) -> Document | None:
    if spec.status != ACTIVE_STATUS or spec.marketing != MARKETED:
        return None
    sections, substances = _sections(spec, tables)
    return build_document(
        record,
        native_id=spec.cis,
        url=page_url(spec.cis),
        title=spec.name,
        language=Language.FR,
        content_type=ContentType.DRUG_LABEL,
        sections=sections,
        retrieved_at=retrieved_at,
        synonyms=substances,
        published_on=spec.authorised_on,
        metadata={
            "cis": spec.cis,
            "dosage_form": spec.form,
            "routes": list(spec.routes),
            "active_substances": substances,
            "holder": spec.holder,
            "authorisation_procedure": spec.procedure,
            "has_smr_opinions": len(tables.smr.get(spec.cis, [])),
            "text_scope": "administrative and composition data only; no SmPC or leaflet text",
        },
    )


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    raw_dir = paths.raw_dir(record.id)
    main = raw_dir / url_to_relpath(file_url("CIS_bdpm"))
    if not main.exists():
        raise FileNotFoundError(f"{main} is missing; run fetch first")
    stamp = datetime.fromtimestamp(main.stat().st_mtime, tz=UTC)
    tables = load_tables(raw_dir)
    for spec in tables.specialities:
        doc = speciality_to_document(spec, tables, record, stamp)
        if doc is not None:
            yield doc
