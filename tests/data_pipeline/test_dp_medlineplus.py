from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from dp_helpers import make_record

from core.schemas.source import ContentType
from data_pipeline.fetch.client import Fetcher
from data_pipeline.parsers import medlineplus_genetics as genetics
from data_pipeline.parsers import medlineplus_topics as topics
from data_pipeline.paths import DataPaths
from data_pipeline.pipeline import build_corpus
from data_pipeline.registry import get_source
from data_pipeline.storage import read_documents_jsonl

SUMMARY = (
    "&lt;p&gt;Asthma is a chronic &lt;a href=\"https://medlineplus.gov/lungs.html\"&gt;lung disease&lt;/a&gt; that "
    "inflames and narrows the airways. It causes wheezing, chest tightness, shortness of breath and coughing, "
    "mostly at night or early in the morning.&lt;/p&gt;&lt;h3&gt;Symptoms&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;Wheezing"
    "&lt;/li&gt;&lt;li&gt;Coughing&lt;/li&gt;&lt;/ul&gt;&lt;p class=\"\"&gt;NIH: National Heart, Lung, and Blood Institute"
    "&lt;/p&gt;"
)
TOPICS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<health-topics total="4" date-generated="11/13/2026 08:58:25">
<health-topic meta-desc="Asthma desc" title="Asthma" url="https://medlineplus.gov/asthma.html" id="1" language="English" date-created="12/22/2015">
<also-called>Bronchial asthma</also-called>
<full-summary>{SUMMARY}</full-summary>
<group url="https://medlineplus.gov/lungdiseases.html" id="9">Lungs and Breathing</group>
<mesh-heading><descriptor id="D001249">Asthma</descriptor></mesh-heading>
<primary-institute url="https://www.nhlbi.nih.gov">National Heart, Lung, and Blood Institute</primary-institute>
<see-reference>Wheeze disease</see-reference>
<related-topic url="https://medlineplus.gov/copd.html" id="2">COPD</related-topic>
<site title="Asthma" url="https://medlineplus.gov/ency/article/000141.htm"><organization>Medical Encyclopedia</organization></site>
</health-topic>
<health-topic title="Asma" url="https://medlineplus.gov/spanish/asthma.html" id="2" language="Spanish"><full-summary>&lt;p&gt;El asma.&lt;/p&gt;</full-summary></health-topic>
<health-topic title="Empty" url="https://medlineplus.gov/empty.html" id="3" language="English"><full-summary></full-summary></health-topic>
<health-topic title="Encyclopedia clone" url="https://medlineplus.gov/ency/article/1.htm" id="4" language="English"><full-summary>&lt;p&gt;Copyrighted text&lt;/p&gt;</full-summary></health-topic>
</health-topics>
"""
INDEX_HTML = (
    '<a href="https://medlineplus.gov/xml/mplus_topics_2026-11-12.xml">old</a>'
    '<a href="https://medlineplus.gov/xml/mplus_topics_2026-11-13.xml">new</a>'
    '<a href="https://medlineplus.gov/xml/mplus_topics_compressed_2026-11-13.zip">zip</a>'
)
GHR_XML = """<?xml version="1.0" encoding="utf-8"?>
<summaries xmlns="https://medlineplus.gov/download/ghr-summaries-20250602.xsd" xmlns:html="http://www.w3.org/1999/xhtml">
<health-condition-summary id="21631"><name>Example syndrome</name>
<ghr-page>https://medlineplus.gov/genetics/condition/example-syndrome</ghr-page>
<text-list><text><text-role>description</text-role><html><html:p>Example syndrome is a condition caused by a change in a gene. It affects growth and development in children and varies a lot between people.</html:p><html:p>Features include <html:i>short stature</html:i> and delayed speech.</html:p></html></text></text-list>
<inheritance-pattern-list><inheritance-pattern><code>ad</code><memo>Autosomal dominant</memo></inheritance-pattern></inheritance-pattern-list>
<related-gene-list><related-gene><gene-symbol>EXG1</gene-symbol></related-gene></related-gene-list>
<synonym-list><synonym>Example disorder</synonym></synonym-list>
<db-key-list><db-key><db>MeSH</db><key>D002872</key></db-key><db-key><db>SNOMED CT</db><key>1</key></db-key><db-key><db>OMIM</db><key>609625</key></db-key></db-key-list>
<reviewed>2019-09</reviewed><published>2020-09-08</published></health-condition-summary>
<gene-summary id="21929"><gene-symbol>EXG1</gene-symbol><name>example gene one</name>
<ghr-page>https://medlineplus.gov/genetics/gene/exg1</ghr-page>
<text-list><text><text-role>function</text-role><html><html:p>The EXG1 gene provides instructions for making a protein that helps cells move molecules between the nucleus and the cytoplasm of the cell.</html:p></html></text></text-list>
<related-health-condition-list><related-health-condition><name>Example syndrome</name></related-health-condition></related-health-condition-list>
<synonym-list><synonym>EX1</synonym></synonym-list>
<reviewed>2025-08</reviewed><published>2025-08-25</published></gene-summary>
<chromosome-summary id="23166"><name>1</name><ghr-page>https://medlineplus.gov/genetics/chromosome/1</ghr-page>
<text-list><text><text-role>description</text-role><html><html:p>Humans normally have 46 chromosomes in each cell, divided into 23 pairs. Two copies of chromosome 1 form one of the pairs.</html:p></html></text></text-list></chromosome-summary>
<mtdna-summary id="23190"><name>mitochondrial DNA</name><ghr-page>https://medlineplus.gov/genetics/chromosome/mitochondrial-dna</ghr-page>
<text-list><text><text-role>description</text-role><html><html:p>Mitochondria are structures within cells that convert the energy from food into a form that cells can use, and they carry their own DNA.</html:p></html></text></text-list></mtdna-summary>
<gene-summary id="1"><gene-symbol>NOTEXT</gene-symbol><name>no text</name><ghr-page>https://medlineplus.gov/genetics/gene/notext</ghr-page></gene-summary>
</summaries>
"""


@pytest.fixture
def mp_record():
    return get_source("medlineplus_topics")


def test_discover_topics_url_picks_newest_dated_xml() -> None:
    assert topics.discover_topics_url(INDEX_HTML).endswith("mplus_topics_2026-11-13.xml")
    with pytest.raises(ValueError, match="no mplus_topics"):
        topics.discover_topics_url("<html></html>")


def test_topics_parse_keeps_english_summary_structure(tmp_path: Path, mp_record) -> None:
    xml = tmp_path / "mplus_topics_2026-11-13.xml"
    xml.write_text(TOPICS_XML, encoding="utf-8")
    docs = list(topics.parse_file(xml, mp_record))
    assert [d.doc_id for d in docs] == ["medlineplus_topics:1"]
    doc = docs[0]
    assert doc.title == "Asthma" and doc.language.value == "en"
    assert doc.content_type is ContentType.CONDITION
    assert doc.synonyms == ("Bronchial asthma", "Wheeze disease")
    assert [s.heading_path for s in doc.sections] == [("Asthma",), ("Asthma", "Symptoms")]
    assert doc.sections[1].text == "- Wheezing\n- Coughing" and doc.sections[1].kind == "symptoms"
    assert "NIH:" not in doc.sections[0].text and doc.metadata["summary_credit"].startswith("NIH:")
    assert doc.metadata["mesh_ids"] == ["D001249"] and doc.metadata["groups"] == ["Lungs and Breathing"]
    assert doc.metadata["related_topics"] == ["COPD"] and doc.published_on.isoformat() == "2015-12-22"
    assert doc.license_id == "public-domain-us-gov" and doc.attribution.startswith("Source: MedlinePlus")
    assert "ency" not in doc.model_dump_json().replace("encyclopedia", "")  # site/ency links never ingested


def test_topics_parse_directory_requires_a_file(paths: DataPaths, mp_record) -> None:
    with pytest.raises(FileNotFoundError):
        list(topics.parse(paths, mp_record))
    raw = paths.raw_dir("medlineplus_topics") / "medlineplus.gov" / "xml"
    raw.mkdir(parents=True)
    (raw / "mplus_topics_2026-11-13.xml").write_text(TOPICS_XML, encoding="utf-8")
    assert len(list(topics.parse(paths, mp_record))) == 1


def test_topics_content_type_by_group() -> None:
    assert topics._content_type(["Diagnostic Tests and Screenings"]) is ContentType.LAB_TEST
    assert topics._content_type(["Food and Nutrition"]) is ContentType.WELLNESS
    assert topics._content_type(["Food and Nutrition", "Disorders and Conditions"]) is ContentType.CONDITION
    assert topics._content_type([]) is ContentType.CONDITION


async def test_topics_fetch_uses_robots_override_only_for_listed_xml(tmp_path: Path, mp_record) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /xml/\n")
        if request.url.path == "/xml.html":
            return httpx.Response(200, text=INDEX_HTML)
        return httpx.Response(200, text=TOPICS_XML)

    from data_pipeline.fetch.client import FetchConfig

    paths = DataPaths(tmp_path).ensure()
    async with Fetcher(mp_record, paths, FetchConfig(default_rps=1000), transport=httpx.MockTransport(handler)) as fetcher:
        path = await topics.fetch(fetcher)
        assert path.name == "mplus_topics_2026-11-13.xml"
        assert fetcher.manifest.latest(f"https://medlineplus.gov/xml/{path.name}").note == "robots_override"
    assert not any("ency" in u for u in seen)


def test_end_to_end_topics_build_writes_marker(tmp_path: Path, mp_record) -> None:
    paths = DataPaths(tmp_path).ensure()
    xml = paths.raw_dir("medlineplus_topics") / "x" / "mplus_topics_2026-11-13.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text(TOPICS_XML, encoding="utf-8")
    report = build_corpus(mp_record, topics.parse(paths, mp_record), paths, **topics.BUILD_OPTIONS)
    assert report.kept == 1
    marker = json.loads(paths.ready_file("medlineplus_topics").read_text(encoding="utf-8"))
    assert marker["documents"] == 1 and marker["source_id"] == "medlineplus_topics"
    assert len(list(read_documents_jsonl(paths.normalized_file("medlineplus_topics")))) == 1


@pytest.fixture
def genetics_record():
    return get_source("medlineplus_genetics")


def test_genetics_parse_all_entry_kinds(tmp_path: Path, genetics_record) -> None:
    xml = tmp_path / "ghr-summaries.xml"
    xml.write_text(GHR_XML, encoding="utf-8")
    docs = {d.metadata["entry_kind"]: d for d in genetics.parse_file(xml, genetics_record)}
    assert set(docs) == {"condition", "gene", "chromosome", "mtdna"}
    cond, gene = docs["condition"], docs["gene"]
    assert cond.title == "Example syndrome" and cond.content_type is ContentType.GENETICS
    assert [s.kind for s in cond.sections] == ["summary", "inheritance", "related_genes"]
    assert "short stature" in cond.sections[0].text and "Autosomal dominant" in cond.sections[1].text
    assert cond.metadata["mesh_ids"] == ["D002872"] and cond.metadata["omim_ids"] == ["609625"]
    assert "SNOMED" not in cond.model_dump_json()
    assert cond.reviewed_on.isoformat() == "2019-09-01" and cond.published_on.isoformat() == "2020-09-08"
    assert gene.title == "EXG1 gene (example gene one)" and gene.sections[0].heading_path[1] == "Normal function"
    assert "example gene one" in gene.synonyms and "EX1" in gene.synonyms
    assert docs["chromosome"].title == "Chromosome 1" and docs["mtdna"].title == "Mitochondrial DNA"


def test_genetics_build_drops_nothing_valid_and_skips_textless(tmp_path: Path, genetics_record) -> None:
    paths = DataPaths(tmp_path).ensure()
    xml = paths.raw_dir("medlineplus_genetics") / "d" / "ghr-summaries.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text(GHR_XML, encoding="utf-8")
    report = build_corpus(genetics_record, genetics.parse(paths, genetics_record), paths, **genetics.BUILD_OPTIONS)
    assert report.parsed == 4 and report.kept == 4
    with pytest.raises(FileNotFoundError):
        list(genetics.parse(DataPaths(tmp_path / "empty").ensure(), genetics_record))


async def test_genetics_fetch_downloads_compendium(tmp_path: Path, genetics_record) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /xml/\n")
        return httpx.Response(200, text=GHR_XML) if request.url.path.endswith("ghr-summaries.xml") else httpx.Response(404)

    from data_pipeline.fetch.client import FetchConfig

    async with Fetcher(
        genetics_record, DataPaths(tmp_path).ensure(), FetchConfig(default_rps=1000), transport=httpx.MockTransport(handler)
    ) as fetcher:
        assert (await genetics.fetch(fetcher)).name == "ghr-summaries.xml"


def test_make_record_helper_is_valid() -> None:
    assert make_record().indexable
