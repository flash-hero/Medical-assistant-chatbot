"""openFDA drug labels (SPL) -> one Document per active-ingredient set.

Fetch: the 14 zip partitions listed in https://api.fda.gov/download.json (drug.label.partitions).
Parse: stream each zip member with ijson (never the whole JSON in RAM), keep only the newest label per
openfda.spl_set_id, group by active-ingredient set, choose ONE label per group (human prescription first,
then OTC; newest effective_time) and merge nothing else: the count of merged labels is recorded.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import ijson
import structlog

from core.schemas.document import Document, Section
from core.schemas.source import ContentType, Language, SourceRecord
from data_pipeline.fetch.client import Fetcher
from data_pipeline.parsers.common import build_document
from data_pipeline.parsers.openfda_select import IngredientGroup, IngredientIndex
from data_pipeline.paths import DataPaths

SOURCE_ID = "openfda_labels"
DOWNLOAD_INDEX = "https://api.fda.gov/download.json"
PARTITION_PREFIX = "https://download.open.fda.gov/drug/label/"
DAILYMED_URL = "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}"
BUILD_OPTIONS = {"min_chars": 150}
MAX_BRANDS, MAX_GENERICS, MAX_SUBSTANCES = 25, 10, 10
JURISDICTION = "US FDA label"
log = structlog.get_logger(__name__)


def partition_urls(download_json: dict[str, object]) -> list[str]:
    """Drug-label partition URLs from download.json; anything outside the label prefix is ignored."""
    try:
        partitions = download_json["results"]["drug"]["label"]["partitions"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise ValueError("download.json has no results.drug.label.partitions") from exc
    urls = [
        p["file"]
        for p in partitions
        if isinstance(p, dict) and str(p.get("file", "")).startswith(PARTITION_PREFIX)
    ]
    if not urls:
        raise ValueError("download.json lists no drug label partitions")
    return sorted(urls)


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> list[Path]:
    """Download the index, then each partition (robots-exempt: the zips are published in download.json)."""
    index = await fetcher.fetch(DOWNLOAD_INDEX, refresh=True)
    if index.path is None:
        raise RuntimeError(f"cannot read {DOWNLOAD_INDEX}: HTTP {index.status}")
    urls = partition_urls(json.loads(index.path.read_text(encoding="utf-8")))
    if limit is not None:
        urls = urls[:limit]
    files: list[Path] = []
    for url in urls:
        result = await fetcher.fetch(url, robots_exempt=True)
        if result.path is None:
            raise RuntimeError(f"cannot download {url}: HTTP {result.status}")
        files.append(result.path)
        log.info("partition_ready", url=url, bytes=result.size)
    return files


def iter_partition_records(zip_path: Path) -> Iterator[dict[str, object]]:
    """Stream label records from one zip partition without loading the JSON into memory."""
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.endswith(".json"):
                continue
            with archive.open(name) as handle:
                yield from ijson.items(handle, "results.item", use_float=True)


def _effective_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _title(group: IngredientGroup) -> str:
    best = group.best
    assert best is not None
    generic = (best.generic_name or group.key).title()
    brand = next((b for b, _ in group.brands.most_common() if b.casefold() != generic.casefold()), "")
    brand = best.brand_name if best.brand_name and best.brand_name.casefold() != generic.casefold() else brand
    return (
        f"{generic} ({brand.title() if brand.isupper() else brand}) - US drug label"
        if brand
        else f"{generic} - US drug label"
    )


def group_to_document(
    group: IngredientGroup, record: SourceRecord, retrieved_at: datetime
) -> Document | None:
    best = group.best
    if best is None:
        return None
    title = _title(group)
    sections = tuple(
        Section(
            section_id=name,
            heading_path=(title, name.replace("_", " ").capitalize()),
            text=text,
            kind=name,
        )
        for name, text in best.sections
    )
    synonyms = [
        *(b for b, _ in group.brands.most_common(MAX_BRANDS)),
        *(g for g, _ in group.generics.most_common(MAX_GENERICS)),
        *(s for s, _ in group.substances.most_common(MAX_SUBSTANCES)),
    ]
    return build_document(
        record,
        native_id=best.set_id,
        url=DAILYMED_URL.format(set_id=best.set_id),
        title=title,
        language=Language.EN,
        content_type=ContentType.DRUG_LABEL,
        sections=sections,
        retrieved_at=retrieved_at,
        synonyms=synonyms,
        reviewed_on=_effective_date(best.effective_time),
        metadata={
            "jurisdiction": JURISDICTION,
            "spl_set_id": best.set_id,
            "product_type": best.product_type,
            "route": list(best.route),
            "rxcui": list(best.rxcui),
            "manufacturer": best.manufacturer,
            "label_effective_time": best.effective_time,
            "merged_labels": group.merged,
            "ingredient_key": group.key,
            "truncated_sections": list(best.truncated),
        },
    )


def select_from_zips(zip_paths: list[Path]) -> IngredientIndex:
    index = IngredientIndex()
    for zip_path in zip_paths:
        before = index.stats["records"]
        for rec in iter_partition_records(zip_path):
            index.add(rec)
        log.info("partition_scanned", file=zip_path.name, records=index.stats["records"] - before)
    return index


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    zips = sorted(paths.raw_dir(record.id).rglob("drug-label-*-of-*.json.zip"))
    if not zips:
        raise FileNotFoundError(f"no drug-label zips under {paths.raw_dir(record.id)}; run fetch first")
    index = select_from_zips(zips)
    log.info("selection_done", groups=len(index.groups), **dict(index.stats))
    stamp = datetime.fromtimestamp(zips[-1].stat().st_mtime, tz=UTC)
    for group in sorted(index.chosen(), key=lambda g: g.key):
        doc = group_to_document(group, record, stamp)
        if doc is not None:
            yield doc
