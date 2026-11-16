from __future__ import annotations

from pathlib import Path

import pytest

from data_pipeline import drug_synonyms as ds


@pytest.fixture(scope="module")
def entries() -> tuple[ds.DrugEntry, ...]:
    return ds.load_entries()


def test_at_least_200_entries_all_unverified(entries: tuple[ds.DrugEntry, ...]) -> None:
    assert len(entries) >= 200
    assert {e.review_status for e in entries} == {"unverified"}


def test_every_entry_has_french_and_arabic_names(entries: tuple[ds.DrugEntry, ...]) -> None:
    for entry in entries:
        assert entry.fr.strip() and entry.ar, entry.inn
        assert any("؀" <= ch <= "ۿ" for name in entry.ar for ch in name), (
            f"{entry.inn}: Arabic script expected"
        )


def test_inn_are_unique_lowercase(entries: tuple[ds.DrugEntry, ...]) -> None:
    inns = [e.inn for e in entries]
    assert len(inns) == len(set(inns))
    assert all(i == i.lower() or i[0].islower() for i in inns), "INN spelled in lower case"


def test_known_equivalences_expand_across_names() -> None:
    assert "acetaminophen" in ds.expand_term("paracetamol")
    assert "paracetamol" in ds.expand_term("Acetaminophen")
    assert "albuterol" in ds.expand_term("salbutamol")
    assert "Ventolin" in ds.expand_term("albuterol")
    assert "epinephrine" in ds.expand_term("adrenaline")
    assert "adrenaline" in ds.expand_term("Epinephrine")
    assert "باراسيتامول" in ds.expand_term("Doliprane")
    assert "ibuprofène" in ds.expand_term("ibuprofen")


def test_expansion_matches_accents_case_and_arabic_forms() -> None:
    assert "paracetamol" in ds.expand_term("PARACÉTAMOL")
    assert "paracetamol" in ds.expand_term("باراسيتامول")
    assert ds.expand_term("no-such-drug") == ()


def test_frusemide_is_reachable_via_furosemide_entry() -> None:
    # frusemide is the old British spelling: it must still lead to the furosemide entry
    assert "furosemide" in ds.expand_term("furosémide")


def test_all_names_dedupes_on_matching_form() -> None:
    entry = ds.DrugEntry(inn="x-drug", usan="X-Drug", fr="x-drug", ar=("اكس",), brands=("X-DRUG",))
    assert entry.all_names() == ("x-drug", "اكس")


def test_loader_errors(tmp_path: Path) -> None:
    with pytest.raises(ds.DrugSynonymError):
        ds.load_entries(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("entries: 3\n", encoding="utf-8")
    with pytest.raises(ds.DrugSynonymError):
        ds.load_entries(bad)
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("entries:\n  - {inn: a}\n", encoding="utf-8")
    with pytest.raises(ds.DrugSynonymError, match="invalid"):
        ds.load_entries(invalid)
    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "entries:\n  - {inn: aaa, fr: aaa, ar: [ا]}\n  - {inn: AAA, fr: aaa, ar: [ا]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ds.DrugSynonymError, match="duplicate"):
        ds.load_entries(dup)


def test_default_entries_are_cached() -> None:
    assert ds.default_entries() is ds.default_entries()
