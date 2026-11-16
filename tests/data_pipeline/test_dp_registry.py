from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from core.schemas.source import SourceRecord, SourceStatus
from data_pipeline import registry as reg


def _record(**overrides: object) -> SourceRecord:
    base: dict[str, object] = {
        "id": "src_a",
        "name": "Source A",
        "publisher": "Pub",
        "homepage": "https://a.example.org/",
        "status": "active",
        "wave": 1,
        "trust_tier": 1,
        "reuse_mode": "paraphrase_ok",
        "languages": ["en"],
        "content_types": ["condition"],
        "domains": ["a.example.org"],
        "license": {
            "id": "pd",
            "name": "Public domain",
            "evidence_url": "https://a.example.org/terms",
            "commercial_use": "yes",
            "attribution": "Source: A",
            "verified_on": "2026-11-15",
            "verified_by": "data-agent",
        },
    }
    base.update(overrides)
    return SourceRecord.model_validate(base)


def _excluded(source_id: str, domains: list[str]) -> SourceRecord:
    return _record(
        id=source_id,
        status="excluded",
        reuse_mode="link_only",
        domains=domains,
        license={"id": "prop", "name": "All rights reserved", "commercial_use": "no"},
    )


@pytest.fixture(scope="module")
def bundled() -> tuple[SourceRecord, ...]:
    return reg.load_registry()


def test_bundled_registry_has_no_violations(bundled: tuple[SourceRecord, ...]) -> None:
    assert reg.check_records(bundled) == []


def test_every_active_source_has_verified_licence(bundled: tuple[SourceRecord, ...]) -> None:
    active = [r for r in bundled if r.status is SourceStatus.ACTIVE]
    assert active, "registry must contain at least one active source"
    for record in active:
        lic = record.license
        assert lic.evidence_url is not None, record.id
        assert lic.verified_on is not None and lic.verified_on <= date.today(), record.id
        assert lic.verified_by, record.id
        assert lic.attribution.strip(), record.id
        assert lic.conditions, f"{record.id}: record the conditions that were read"


def test_no_duplicate_ids(bundled: tuple[SourceRecord, ...]) -> None:
    ids = [r.id for r in bundled]
    assert len(ids) == len(set(ids))


def test_duplicate_ids_are_reported() -> None:
    problems = reg.check_records([_record(), _record()])
    assert any("duplicate" in p for p in problems)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.mayoclinic.org/diseases-conditions/diabetes",
        "https://MAYOCLINIC.org/x",
        "https://my.clevelandclinic.org/health/diseases/7104-diabetes",
        "https://www.msdmanuals.com/home",
        "https://medlineplus.gov/ency/article/003640.htm",
        "https://medlineplus.gov/ENCY/article/003640.htm",
        "https://medlineplus.gov/spanish/ency/article/003640.htm",
        "https://medlineplus.gov/druginfo/meds/a682878.html",
        "https://www.drugs.com/aspirin.html",
        "https://www.nice.org.uk/guidance/ng28",
    ],
)
def test_excluded_urls_are_refused(url: str, bundled: tuple[SourceRecord, ...]) -> None:
    assert reg.is_excluded_url(url, bundled)


@pytest.mark.parametrize(
    "url",
    [
        "https://medlineplus.gov/diabetestype2.html",
        "https://medlineplus.gov/lab-tests/a1c-test/",
        "https://www.niddk.nih.gov/health-information/diabetes",
        "https://medlineplus.gov/encyclopedia-like-but-not.html",
        "https://example.com/mayoclinic.org",
    ],
)
def test_usable_urls_are_not_excluded(url: str, bundled: tuple[SourceRecord, ...]) -> None:
    assert not reg.is_excluded_url(url, bundled)


def test_excluded_source_for_url_names_the_source(bundled: tuple[SourceRecord, ...]) -> None:
    assert reg.excluded_source_for_url("https://www.webmd.com/x", bundled) == "x_webmd"
    assert reg.excluded_source_for_url("https://medlineplus.gov/ency/a.htm", bundled) == "x_medlineplus_adam"


def test_is_indexable_follows_status(bundled: tuple[SourceRecord, ...]) -> None:
    assert reg.is_indexable("medlineplus_topics", bundled)
    assert not reg.is_indexable("x_webmd", bundled)
    assert not reg.is_indexable("who_fact_sheets", bundled)
    assert not reg.is_indexable("does_not_exist", bundled)


def test_assert_indexable_raises_for_hold_and_unknown() -> None:
    hold = _record(id="src_h", status="hold")
    with pytest.raises(reg.SourceNotIndexableError):
        reg.assert_indexable("src_h", [hold])
    with pytest.raises(reg.SourceNotIndexableError):
        reg.assert_indexable("nope", [hold])
    assert reg.assert_indexable("src_a", [_record()]).id == "src_a"


def test_active_domain_colliding_with_excluded_host_is_reported() -> None:
    problems = reg.check_records([_record(domains=["mayoclinic.org"]), _excluded("x_mayo", ["mayoclinic.org"])])
    assert any("excluded by x_mayo" in p for p in problems)


def test_path_scoped_exclusion_does_not_block_the_host() -> None:
    records = [_record(domains=["medlineplus.gov"]), _excluded("x_adam", ["medlineplus.gov/ency/"])]
    assert reg.check_records(records) == []
    assert reg.is_excluded_url("https://medlineplus.gov/ency/x", records)
    assert not reg.is_excluded_url("https://medlineplus.gov/x", records)


def test_active_with_empty_attribution_is_reported() -> None:
    lic = {
        "id": "pd",
        "name": "n",
        "evidence_url": "https://a.example.org/t",
        "commercial_use": "yes",
        "attribution": " ",
        "verified_on": "2026-11-15",
        "verified_by": "data-agent",
    }
    problems = reg.check_records([_record(license=lic)])
    assert any("attribution" in p for p in problems)


def test_future_verification_date_is_reported() -> None:
    lic = {
        "id": "pd",
        "name": "n",
        "evidence_url": "https://a.example.org/t",
        "commercial_use": "yes",
        "attribution": "x",
        "verified_on": "2030-01-01",
        "verified_by": "data-agent",
    }
    problems = reg.check_records([_record(license=lic)], today=date(2026, 11, 15))
    assert any("future" in p for p in problems)


def test_active_without_evidence_cannot_even_be_built() -> None:
    with pytest.raises(ValueError, match="ACTIVE"):
        _record(license={"id": "pd", "name": "n", "commercial_use": "yes", "attribution": "x"})


def test_excluded_with_wrong_reuse_mode_is_reported() -> None:
    bad = _record(id="x_bad", status="excluded", reuse_mode="paraphrase_ok", domains=["bad.example"])
    assert any("link_only" in p for p in reg.check_records([bad]))


def test_url_belongs_to_source() -> None:
    record = _record(domains=["a.example.org"])
    assert reg.url_belongs_to_source("https://www.a.example.org/x", record)
    assert reg.url_belongs_to_source("https://sub.a.example.org/x", record)
    assert not reg.url_belongs_to_source("https://evil-a.example.org.attacker.com/x", record)


def test_load_registry_rejects_bad_files(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(reg.RegistryError):
        reg.load_registry(missing)
    bad = tmp_path / "bad.yaml"
    bad.write_text("sources: 3\n", encoding="utf-8")
    with pytest.raises(reg.RegistryError):
        reg.load_registry(bad)
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("sources:\n  - {id: 'x'}\n", encoding="utf-8")
    with pytest.raises(reg.RegistryError, match="invalid source"):
        reg.load_registry(invalid)


def test_yaml_yes_no_booleans_are_coerced(tmp_path: Path) -> None:
    path = tmp_path / "r.yaml"
    path.write_text(
        "sources:\n"
        "  - {id: x_one, name: n, publisher: p, homepage: 'https://x.example/', status: excluded, wave: 0,\n"
        "     trust_tier: 1, reuse_mode: link_only, languages: [en], content_types: [condition],\n"
        "     domains: [x.example], license: {id: prop, name: n, commercial_use: no}}\n",
        encoding="utf-8",
    )
    (record,) = reg.load_registry(path)
    assert record.license.commercial_use.value == "no"


def test_cli_check_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert reg.main(["--check"]) == 0
    assert "0 violations" in capsys.readouterr().out
    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "sources:\n"
        "  - {id: x_one, name: n, publisher: p, homepage: 'https://x.example/', status: excluded, wave: 0,\n"
        "     trust_tier: 1, reuse_mode: link_only, languages: [en], content_types: [condition],\n"
        "     domains: [x.example], license: {id: prop, name: n, commercial_use: no}}\n"
        "  - {id: x_one, name: n, publisher: p, homepage: 'https://x.example/', status: excluded, wave: 0,\n"
        "     trust_tier: 1, reuse_mode: link_only, languages: [en], content_types: [condition],\n"
        "     domains: [x.example], license: {id: prop, name: n, commercial_use: no}}\n",
        encoding="utf-8",
    )
    assert reg.main(["--check", "--path", str(dup)]) == 1
    assert reg.main(["--check", "--path", str(tmp_path / "missing.yaml")]) == 1
