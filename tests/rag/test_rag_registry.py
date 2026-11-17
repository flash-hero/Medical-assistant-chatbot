from rag_fixtures import make_doc, source_entry

from rag.registry import DomainRule, load_registry


def test_unquoted_yes_no_stay_strings_like_the_data_track_reads_them(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text(
        "version: 1\nsources:\n"
        "  - id: demo_src\n    name: Demo\n    publisher: Gov\n    homepage: https://example.gov/\n"
        "    status: active\n    wave: 1\n    trust_tier: 1\n    reuse_mode: paraphrase_ok\n"
        "    languages: [en]\n    content_types: [condition]\n    domains: [example.gov]\n"
        "    license: {id: pd, name: PD, evidence_url: 'https://example.gov/t', commercial_use: yes,\n"
        "              verified_on: 2026-11-15, verified_by: me}\n"
        "  - {id: x_ency, name: Ency, publisher: P, homepage: 'https://example.gov/ency.html',\n"
        "     status: excluded, wave: 0, trust_tier: 2, reuse_mode: link_only, languages: [en],\n"
        "     content_types: [condition],\n"
        "     domains: [example.gov/ency/], license: {id: p, name: p, commercial_use: no}}\n",
        encoding="utf-8",
    )
    reg = load_registry(path)
    assert not reg.invalid
    assert reg.require_indexable("demo_src").license.commercial_use.value == "yes"
    assert reg.records["x_ency"].license.commercial_use.value == "no"
    ok = make_doc("asthma", url="https://example.gov/asthma.html")
    ency = make_doc("ency1", url="https://www.example.gov/ency/article/0001.htm")
    assert reg.refusal_reason(ok, "demo_src") is None
    assert reg.refusal_reason(ency, "demo_src") == "excluded_domain"


def test_domain_rule_parsing_and_matching():
    rule = DomainRule.parse("https://www.MedlinePlus.gov/ency/")
    assert rule == DomainRule("medlineplus.gov", "/ency/")
    assert rule.matches("https://medlineplus.gov/ency/article/1.htm")
    assert not rule.matches("https://medlineplus.gov/asthma.html")
    assert DomainRule.parse("bad.example.com").matches("https://sub.bad.example.com/x")


def test_invalid_records_are_reported_and_never_indexable(tmp_path):
    import pytest
    import yaml

    from rag.errors import SourceNotIndexable

    broken = source_entry("broken_src")
    broken["license"] = {**broken["license"], "verified_on": None}
    path = tmp_path / "r.yaml"
    path.write_text(yaml.safe_dump({"sources": [broken]}), encoding="utf-8")
    reg = load_registry(path)
    assert "broken_src" in reg.invalid
    with pytest.raises(SourceNotIndexable, match="invalid registry record"):
        reg.require_indexable("broken_src")
    (tmp_path / "empty.yaml").write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(SourceNotIndexable, match="no 'sources'"):
        load_registry(tmp_path / "empty.yaml")
