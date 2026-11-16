"""BDPM (French public medicines database): fetch the five tables from a mock origin, parse recorded rows."""

from __future__ import annotations

import shutil
from pathlib import Path
from datetime import date

import httpx
import pytest
from dp_helpers import FIXTURES

from core.schemas.source import SourceRecord
from data_pipeline.catalog import run_parse
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.fetch.naming import url_to_relpath
from data_pipeline.parsers import bdpm
from data_pipeline.paths import DataPaths
from data_pipeline.registry import get_source

BDPM = FIXTURES / "bdpm"
ABILIFY, ACARBOSE, ANASTROZOLE = "65198099", "68371745", "60002283"


def _record() -> SourceRecord:
    record = get_source("bdpm")
    assert record is not None
    return record


def _install(paths: DataPaths) -> None:
    """Copy the recorded tables where the fetcher would have stored them."""
    for name in bdpm.FILES:
        target = paths.raw_dir("bdpm") / url_to_relpath(bdpm.file_url(name))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BDPM / f"{name}.txt", target)


async def _no_sleep(_: float) -> None:
    return None


def _fetcher(paths: DataPaths, missing: str | None = None) -> Fetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1].removesuffix(".txt")
        if name == missing or name not in bdpm.FILES:
            return httpx.Response(404, text="nope")
        return httpx.Response(200, content=(BDPM / f"{name}.txt").read_bytes())

    return Fetcher(
        _record(),
        paths,
        FetchConfig(default_rps=1000.0, backoff_base_s=0.0, max_retries=0),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )


# ---- helpers -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a<br>• b<br />c", "a\n• b\nc"),
        ("<p>x   y</p>", "x y"),
        ("", ""),
    ],
)
def test_clean_text_turns_breaks_into_lines_and_strips_markup(raw: str, expected: str) -> None:
    assert bdpm.clean_text(raw) == expected


def test_parse_fr_date_accepts_both_formats() -> None:
    assert bdpm.parse_fr_date("04/06/2004") == date(2004, 6, 4)
    assert bdpm.parse_fr_date("20220720") == date(2022, 7, 20)
    assert bdpm.parse_fr_date("") is None
    assert bdpm.parse_fr_date("soon") is None


def test_urls() -> None:
    assert (
        bdpm.file_url("CIS_bdpm")
        == "https://base-donnees-publique.medicaments.gouv.fr/download/file/CIS_bdpm.txt"
    )
    assert bdpm.page_url("123").endswith("/medicament/123/extrait")


def test_read_table_decodes_windows_1252_and_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "t.txt"
    path.write_bytes("a\tcomprimé\r\n\r\nb\tl’avis\r\n".encode("cp1252"))
    assert bdpm.read_table(path) == [["a", "comprimé"], ["b", "l’avis"]]


# ---- tables and documents ------------------------------------------------------------------------
def test_load_tables_groups_rows_by_cis(paths: DataPaths) -> None:
    _install(paths)
    tables = bdpm.load_tables(paths.raw_dir("bdpm"))
    assert {s.cis for s in tables.specialities} == {ABILIFY, ACARBOSE, ANASTROZOLE}
    assert len(tables.smr[ABILIFY]) == 2
    assert tables.prescription[ANASTROZOLE] == ["liste I"]
    assert tables.generics[ABILIFY][0][3] == "0"
    spec = next(s for s in tables.specialities if s.cis == ABILIFY)
    assert spec.routes == ("orale",)
    assert spec.holder.startswith("OTSUKA")
    assert spec.authorised_on == date(2004, 6, 4)
    assert not spec.enhanced_monitoring


def test_malformed_rows_are_ignored(tmp_path: Path) -> None:
    short = ["1", "name"]
    assert bdpm._speciality(short) is None  # noqa: SLF001
    assert bdpm._speciality(["", "x", *[""] * 10]) is None  # noqa: SLF001


def test_parse_keeps_only_authorised_marketed_specialities(paths: DataPaths) -> None:
    _install(paths)
    docs = {d.metadata["cis"]: d for d in bdpm.parse(paths, _record())}
    assert set(docs) == {ABILIFY, ANASTROZOLE}  # ACARBOSE is "Autorisation abrogée"
    doc = docs[ABILIFY]
    text = "\n".join(s.text for s in doc.sections)
    assert doc.doc_id == f"bdpm:{ABILIFY}"
    assert doc.language.value == "fr"
    assert doc.content_type.value == "drug_label"
    assert doc.reuse_mode.value == "quote_only"
    assert doc.trust_tier == 1
    assert str(doc.url) == f"https://base-donnees-publique.medicaments.gouv.fr/medicament/{ABILIFY}/extrait"
    assert doc.published_on == date(2004, 6, 4)
    assert doc.synonyms == ("ARIPIPRAZOLE",)
    assert "- Substance active (comprimé) : ARIPIPRAZOLE : 10 mg pour un comprimé" in text
    assert "Voie(s) d'administration : orale." in text
    assert "liste I" in text
    assert "niveau de SMR : Important" in text
    assert "• le traitement de la schizophrénie chez l’adulte." in text
    assert "<br>" not in text
    assert "Groupe générique n° 1247" in text
    assert "médicament de référence" in text
    assert [s.kind for s in doc.sections] == ["summary", "composition", "prescription", "smr", "generic"]
    assert text.index("20/07/2022") < text.index("20/05/2015")  # newest opinion first


def test_document_without_optional_tables_still_has_a_presentation(paths: DataPaths) -> None:
    _install(paths)
    docs = {d.metadata["cis"]: d for d in bdpm.parse(paths, _record())}
    anastrozole = docs[ANASTROZOLE]
    assert [s.kind for s in anastrozole.sections] == ["summary", "composition", "prescription", "generic"]
    assert "générique" in "\n".join(s.text for s in anastrozole.sections)


def test_unknown_generic_type_and_missing_fields_are_tolerated() -> None:
    text = bdpm._generic_text([["9", "GROUPE X", "1", "7", "1"]])  # noqa: SLF001
    assert text == "Groupe générique n° 9 : GROUPE X."
    spec = bdpm.Speciality(
        "1", "NOM", "forme", (), "Autorisation active", "p", "Commercialisée", None, "", True
    )
    presentation = bdpm._presentation(spec)  # noqa: SLF001
    assert "surveillance renforcée" in presentation
    assert "Voie(s)" not in presentation
    assert "Date d'autorisation" not in presentation


def test_composition_labels_therapeutic_fractions() -> None:
    rows = [["1", "solution", "c", "FRACTION X", "", "", "ST", "2"]]
    text, substances = bdpm._composition(rows)  # noqa: SLF001
    assert text == "- Fraction thérapeutique (solution) : FRACTION X"
    assert substances == []


def test_parse_requires_the_main_file(paths: DataPaths) -> None:
    with pytest.raises(FileNotFoundError, match="run fetch"):
        list(bdpm.parse(paths, _record()))


# ---- fetch and build -----------------------------------------------------------------------------
async def test_fetch_downloads_all_five_tables(paths: DataPaths) -> None:
    async with _fetcher(paths) as fetcher:
        assert await bdpm.fetch(fetcher, paths) == 5
    assert len(list(bdpm.parse(paths, _record()))) == 2


async def test_fetch_fails_loudly_when_a_table_is_missing(paths: DataPaths) -> None:
    async with _fetcher(paths, missing="CIS_CPD_bdpm") as fetcher:
        with pytest.raises(RuntimeError, match="CIS_CPD_bdpm"):
            await bdpm.fetch(fetcher, paths)


async def test_build_writes_a_ready_french_corpus(paths: DataPaths) -> None:
    _install(paths)
    report = run_parse("bdpm", paths)
    assert report.kept == 2
    assert report.quarantined == 0
    assert paths.ready_file("bdpm").exists()
