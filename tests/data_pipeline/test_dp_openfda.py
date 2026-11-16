from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from core.schemas.source import SourceRecord
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.parsers import openfda_labels as labels
from data_pipeline.parsers import openfda_select as select
from data_pipeline.paths import DataPaths
from data_pipeline.registry import get_source

STAMP = datetime(2026, 11, 15, tzinfo=UTC)


def _label(
    set_id: str = "set-1",
    *,
    generic: str = "metformin hydrochloride",
    brand: str = "GLUCOPHAGE",
    product: str = "HUMAN PRESCRIPTION DRUG",
    effective: str = "20250101",
    **fields: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "effective_time": effective,
        "openfda": {
            "spl_set_id": [set_id],
            "generic_name": [generic],
            "substance_name": [generic.upper()],
            "brand_name": [brand],
            "product_type": [product],
            "manufacturer_name": ["ACME PHARMA"],
            "rxcui": ["861007"],
            "route": ["ORAL"],
        },
        "indications_and_usage": [
            f"INDICATIONS AND USAGE Metformin is indicated as an adjunct to diet. {set_id}"
        ],
        "warnings": ["WARNINGS Lactic acidosis is a rare but serious complication."],
    }
    record.update(fields)
    return record


# ---- openfda_select ------------------------------------------------------------------------------
def test_normalise_ingredient_drops_salts_but_never_empties_the_name() -> None:
    assert select.normalise_ingredient("Metformin Hydrochloride") == "metformin"
    assert select.normalise_ingredient("SODIUM CHLORIDE") == "sodium chloride"
    assert select.normalise_ingredient("sodium") == "sodium"
    assert select.normalise_ingredient("") == ""


def test_ingredient_key_sorts_and_joins_and_falls_back_to_generic_name() -> None:
    assert select.ingredient_key({"substance_name": ["B DRUG", "A DRUG HCL"]}) == "a drug + b drug"
    assert select.ingredient_key({"generic_name": ["Aspirin"]}) == "aspirin"
    assert select.ingredient_key({}) == ""


def test_first_and_as_list_tolerate_bad_shapes() -> None:
    assert select.first(["  x ", "y"]) == "x"
    assert select.first("x") == ""
    assert select.first([]) == ""
    assert select.as_list([" a ", "", 3]) == ["a", "3"]
    assert select.as_list(None) == []


def test_field_text_strips_heading_prefix_and_breaks_subsections() -> None:
    text = select.field_text(
        ["INDICATIONS AND USAGE 1.1 Type 2 diabetes. 1.2 Another use here"], "indications_and_usage"
    )
    assert text.startswith("1.1 Type 2 diabetes.")
    assert "\n\n1.2 Another use here" in text
    assert select.field_text([], "warnings") == ""
    assert select.field_text(["  "], "warnings") == ""
    assert select.field_text("plain", "no_such_field") == "plain"


def test_cap_text_truncates_on_a_boundary() -> None:
    assert select.cap_text("short", 100) == ("short", False)
    text = "First sentence here. " * 20
    capped, was_cut = select.cap_text(text, 100)
    assert was_cut
    assert len(capped) <= 100
    assert capped.endswith(".")
    hard, cut = select.cap_text("x" * 200, 50)
    assert cut
    assert hard == "x" * 50


def test_build_candidate_filters_product_types_and_third_party_text() -> None:
    assert select.build_candidate({"openfda": {}}) is None
    assert (
        select.build_candidate({"openfda": {"product_type": ["HUMAN OTC DRUG"]}}) is None
    )  # no sections, no set id
    assert select.build_candidate(_label(product="ANIMAL DRUG")) is None
    candidate = select.build_candidate(_label())
    assert candidate is not None
    assert candidate.set_id == "set-1"
    assert candidate.generic_name == "metformin hydrochloride"
    assert [name for name, _ in candidate.sections] == ["indications_and_usage", "warnings"]
    third = select.build_candidate(
        _label(warnings=["Photo is not in the public domain."], indications_and_usage=["Used for pain."])
    )
    assert third is not None
    assert [n for n, _ in third.sections] == ["indications_and_usage"]


def test_build_candidate_renders_table_fields_and_records_truncation() -> None:
    table = "<table><tr><th>Dose</th><th>Use</th></tr><tr><td>500 mg</td><td>start</td></tr></table>"
    candidate = select.build_candidate(
        _label(dosage_and_administration=["Take as directed."], dosage_and_administration_table=[table, 5])
    )
    assert candidate is not None
    dosing = dict(candidate.sections)["dosage_and_administration"]
    assert "Dose | Use" in dosing
    assert "500 mg | start" in dosing
    long_adverse = ". ".join(f"Reaction number {i} was observed" for i in range(600))
    big = select.build_candidate(_label(adverse_reactions=[long_adverse]))
    assert big is not None
    assert big.truncated == ("adverse_reactions",)
    assert len(dict(big.sections)["adverse_reactions"]) <= select.CAPS["adverse_reactions"]


def test_candidate_rank_prefers_prescription_then_richer_then_newer() -> None:
    rx = select.build_candidate(_label("rx"))
    otc = select.build_candidate(_label("otc", product="HUMAN OTC DRUG"))
    assert rx is not None
    assert otc is not None
    assert rx.rank() > otc.rank()
    richer = select.build_candidate(_label("rich", contraindications=["None known."]))
    assert richer is not None
    assert richer.rank() > rx.rank()


def test_ingredient_index_keeps_best_label_per_set_and_counts_merges() -> None:
    index = select.IngredientIndex()
    index.add(_label("old", effective="20200101"))
    index.add(_label("old", effective="20240101"))  # newer version of the same set id replaces it
    index.add(_label("old", effective="20190101"))  # older version ignored
    index.add(_label("other", effective="20230101", contraindications=["Hypersensitivity."]))
    index.add(_label("otc", product="HUMAN OTC DRUG"))
    index.add({"openfda": {}})  # no identity
    index.add(_label("x", product="ANIMAL DRUG"))  # not eligible
    chosen = list(index.chosen())
    assert len(chosen) == 1
    group = chosen[0]
    assert group.best is not None
    assert group.best.set_id == "other"
    assert group.merged == 3
    assert group.brands["GLUCOPHAGE"] >= 3
    assert dict(index.stats) == {
        "records": 7,
        "duplicate_set_id": 2,
        "no_openfda_identity": 1,
        "not_eligible": 1,
    }


def test_ingredient_index_refreshes_best_when_same_set_is_updated() -> None:
    index = select.IngredientIndex()
    index.add(_label("s", effective="20200101"))
    index.add(_label("s", effective="20240101", indications_and_usage=["Updated indication text."]))
    (group,) = list(index.chosen())
    assert (
        group.best is not None
    )
    assert (
        "Updated indication" in dict(group.best.sections)["indications_and_usage"]
    )


# ---- openfda_labels ------------------------------------------------------------------------------
def _record() -> SourceRecord:
    record = get_source("openfda_labels")
    assert record is not None
    return record


def _write_zip(path: Path, records: list[dict[str, object]], member: str = "drug-label-0001.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, json.dumps({"meta": {}, "results": records}))
        archive.writestr("README.txt", "ignored")


def test_partition_urls_accepts_label_prefix_only_and_sorts() -> None:
    prefix = labels.PARTITION_PREFIX
    download = {
        "results": {
            "drug": {
                "label": {
                    "partitions": [
                        {"file": f"{prefix}drug-label-0002-of-0002.json.zip"},
                        {"file": f"{prefix}drug-label-0001-of-0002.json.zip"},
                        {"file": "https://evil.example.org/x.zip"},
                        "junk",
                    ]
                }
            }
        }
    }
    urls = labels.partition_urls(download)
    assert urls == [f"{prefix}drug-label-0001-of-0002.json.zip", f"{prefix}drug-label-0002-of-0002.json.zip"]


@pytest.mark.parametrize(
    "bad", [{}, {"results": {"drug": {}}}, {"results": {"drug": {"label": {"partitions": []}}}}]
)
def test_partition_urls_rejects_malformed_index(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="download.json"):
        labels.partition_urls(bad)


def test_iter_partition_records_streams_json_members_only(tmp_path: Path) -> None:
    archive = tmp_path / "part.zip"
    _write_zip(archive, [_label("a"), _label("b")])
    assert [r["openfda"]["spl_set_id"][0] for r in labels.iter_partition_records(archive)] == ["a", "b"]  # type: ignore[index]


def test_group_to_document_builds_title_synonyms_and_metadata() -> None:
    index = select.IngredientIndex()
    index.add(_label("set-9", brand="GLUCOPHAGE XR"))
    index.add(_label("set-8", brand="Fortamet"))
    (group,) = list(index.chosen())
    doc = labels.group_to_document(group, _record(), STAMP)
    assert doc is not None
    assert doc.title.startswith("Metformin Hydrochloride (Glucophage Xr)")
    assert doc.title.endswith(
        "US drug label"
    )
    assert doc.doc_id.startswith("openfda_labels:set-")
    assert "dailymed.nlm.nih.gov" in str(doc.url)
    assert "Fortamet" in doc.synonyms or "GLUCOPHAGE XR" in doc.synonyms
    assert doc.metadata["jurisdiction"] == "US FDA label"
    assert doc.metadata["merged_labels"] == 2
    assert doc.reviewed_on is not None
    assert doc.sections[0].heading_path[1] == "Indications and usage"
    assert labels.group_to_document(select.IngredientGroup("empty"), _record(), STAMP) is None


def test_title_without_distinct_brand_omits_parentheses() -> None:
    index = select.IngredientIndex()
    index.add(_label("s", generic="aspirin", brand="ASPIRIN"))
    (group,) = list(index.chosen())
    doc = labels.group_to_document(group, _record(), STAMP)
    assert doc is not None
    assert doc.title == "Aspirin - US drug label"


def test_effective_date_parses_or_returns_none() -> None:
    assert labels._effective_date("20250131").isoformat() == "2025-01-31"  # type: ignore[union-attr]
    assert labels._effective_date("garbage") is None


def test_parse_selects_one_label_per_ingredient_across_partitions(paths: DataPaths) -> None:
    raw = paths.raw_dir("openfda_labels") / "download.open.fda.gov" / "drug" / "label"
    _write_zip(
        raw / "drug-label-0001-of-0002.json.zip",
        [_label("m1"), _label("a1", generic="aspirin", brand="BAYER")],
    )
    _write_zip(raw / "drug-label-0002-of-0002.json.zip", [_label("m2", effective="20260101")])
    docs = list(labels.parse(paths, _record()))
    assert [d.metadata["ingredient_key"] for d in docs] == ["aspirin", "metformin"]
    assert all(d.metadata["merged_labels"] >= 1 for d in docs)


def test_parse_requires_downloaded_partitions(paths: DataPaths) -> None:
    with pytest.raises(FileNotFoundError, match="run fetch first"):
        list(labels.parse(paths, _record()))


async def _no_sleep(_: float) -> None:
    return None


def _fetcher(paths: DataPaths, routes: dict[str, httpx.Response]) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return Fetcher(
        _record(),
        paths,
        FetchConfig(default_rps=1000.0, backoff_base_s=0.0, max_retries=1),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )


async def test_fetch_downloads_listed_partitions_robots_exempt(paths: DataPaths) -> None:
    urls = [f"{labels.PARTITION_PREFIX}drug-label-000{n}-of-0002.json.zip" for n in (1, 2)]
    index = {"results": {"drug": {"label": {"partitions": [{"file": u} for u in urls]}}}}
    routes = {
        labels.DOWNLOAD_INDEX: httpx.Response(200, json=index),
        "https://download.open.fda.gov/robots.txt": httpx.Response(403),
        urls[0]: httpx.Response(200, content=b"zip-1"),
        urls[1]: httpx.Response(200, content=b"zip-2"),
    }
    async with _fetcher(paths, routes) as fetcher:
        files = await labels.fetch(fetcher, limit=1)
        assert [f.read_bytes() for f in files] == [b"zip-1"]
        assert len(await labels.fetch(fetcher)) == 2


async def test_fetch_failures_raise_runtime_errors(paths: DataPaths) -> None:
    async with _fetcher(paths, {}) as fetcher:
        with pytest.raises(RuntimeError, match="cannot read"):
            await labels.fetch(fetcher)
    url = f"{labels.PARTITION_PREFIX}drug-label-0001-of-0001.json.zip"
    index = {"results": {"drug": {"label": {"partitions": [{"file": url}]}}}}
    async with _fetcher(
        paths, {labels.DOWNLOAD_INDEX: httpx.Response(200, json=index), url: httpx.Response(404)}
    ) as fetcher:
        with pytest.raises(RuntimeError, match="cannot download"):
            await labels.fetch(fetcher)
