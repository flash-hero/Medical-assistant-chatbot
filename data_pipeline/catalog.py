"""Which source modules exist, and how to run one.

A source module exposes:
  SOURCE_ID: str
  async fetch(fetcher, paths, *, limit=None) -> object       download raw files (optional for local-only
  sources)
  parse(paths, record) -> Iterator[Document]                  raw files -> Documents (pre-gate)
  BUILD_OPTIONS: dict   keyword arguments for pipeline.build_corpus (min_chars, check_language, ...)
  optional
  FETCH_CONFIG: FetchConfig                                   per-source politeness overrides
  optional
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType
from typing import Any

from core.schemas.source import SourceRecord, SourceStatus
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.paths import DataPaths
from data_pipeline.pipeline import BuildReport, build_corpus
from data_pipeline.registry import get_source

MODULES: dict[str, str] = {
    "medlineplus_topics": "data_pipeline.parsers.medlineplus_topics",
    "medlineplus_genetics": "data_pipeline.parsers.medlineplus_genetics",
    "openfda_labels": "data_pipeline.parsers.openfda_labels",
    "niddk": "data_pipeline.parsers.niddk",
    "nci_pdq": "data_pipeline.parsers.nci_pdq",
    "cdc": "data_pipeline.parsers.cdc",
    "cdc_vis": "data_pipeline.parsers.cdc_vis",
    "nccih": "data_pipeline.parsers.nih_institutes",
    "niams": "data_pipeline.parsers.nih_institutes",
    "nichd": "data_pipeline.parsers.nih_institutes",
    "nei": "data_pipeline.parsers.nih_institutes",
    "nhlbi": "data_pipeline.parsers.nih_institutes",
    "nimh": "data_pipeline.parsers.nih_institutes",
    "wikipedia_medicine": "data_pipeline.parsers.wikipedia",
    "bdpm": "data_pipeline.parsers.bdpm",
    "has_publications": "data_pipeline.parsers.has_publications",
}


def load_module(source_id: str) -> ModuleType:
    if source_id not in MODULES:
        raise KeyError(f"no module registered for source {source_id!r}")
    return importlib.import_module(MODULES[source_id])


def sources_for_wave(wave: int, records: tuple[SourceRecord, ...]) -> list[str]:
    return [r.id for r in records if r.wave == wave and r.status is SourceStatus.ACTIVE and r.id in MODULES]


async def run_fetch(
    source_id: str, paths: DataPaths, *, limit: int | None = None, rps: float | None = None
) -> None:
    record = get_source(source_id)
    if record is None:
        raise KeyError(f"unknown source {source_id!r}")
    module = load_module(source_id)
    config: FetchConfig = (
        module.fetch_config_for(source_id)
        if hasattr(module, "fetch_config_for")
        else getattr(module, "FETCH_CONFIG", FetchConfig())
    )
    if rps is not None:
        config = FetchConfig(**{**config.__dict__, "default_rps": rps})
    fetch_fn: Callable[..., Any] | None = getattr(module, "fetch", None)
    if fetch_fn is None:
        return
    async with Fetcher(record, paths.ensure(), config) as fetcher:
        await fetch_fn(fetcher, paths, limit=limit)


def run_parse(source_id: str, paths: DataPaths, *, limit: int | None = None) -> BuildReport:
    record = get_source(source_id)
    if record is None:
        raise KeyError(f"unknown source {source_id!r}")
    module = load_module(source_id)
    options: dict[str, Any] = dict(
        module.build_options_for(source_id)
        if hasattr(module, "build_options_for")
        else getattr(module, "BUILD_OPTIONS", {})
    )
    documents = module.parse(paths, record)
    if limit is not None:
        documents = (doc for index, doc in enumerate(documents) if index < limit)
        options["write_marker"] = False  # a truncated run must never signal "complete" to the RAG track
    return build_corpus(record, documents, paths, **options)
