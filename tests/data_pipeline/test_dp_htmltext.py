from __future__ import annotations

from datetime import UTC, datetime

from dp_helpers import make_record

from core.schemas.document import Section
from core.schemas.source import ContentType, Language
from data_pipeline.parsers.common import build_document, make_native_id, parse_us_date, unique_strings
from data_pipeline.parsers.htmltext import (
    collapse_ws,
    html_to_sections,
    inline_text,
    kind_from_heading,
    parse_fragment,
)


def _sections(markup: str, title: str = "T"):
    return html_to_sections(parse_fragment(markup), title)


def test_paragraphs_lists_and_headings_become_sections() -> None:
    sections = _sections(
        "<p>Intro <a href='x'>link</a> text.</p><ul><li>One</li><li>Two<ul><li>Nested</li></ul></li></ul>"
        "<h3>Symptoms</h3><p>Fever.</p><h3>When to call your doctor</h3><p>Now.</p>"
    )
    assert [s.heading_path for s in sections] == [
        ("T",),
        ("T", "Symptoms"),
        ("T", "When to call your doctor"),
    ]
    assert sections[0].text == "Intro link text.\n\n- One\n- Two\n  - Nested"
    assert [s.kind for s in sections] == ["summary", "symptoms", "when_to_seek_care"]
    assert [s.section_id for s in sections] == ["s0", "s1", "s2"]


def test_heading_levels_nest_and_pop() -> None:
    sections = _sections("<h2>A</h2><p>a</p><h3>A1</h3><p>a1</p><h2>B</h2><p>b</p><h4>B1</h4><p>b1</p>")
    assert [s.heading_path for s in sections] == [("T", "A"), ("T", "A", "A1"), ("T", "B"), ("T", "B", "B1")]


def test_tables_render_as_pipe_rows_and_scripts_are_ignored() -> None:
    sections = _sections(
        "<table><tr><th>Test</th><th>Result</th></tr><tr><td>A1C</td><td>5.7%</td></tr></table>"
        "<script>alert(1)</script><style>p{}</style><p>After</p>"
    )
    assert sections[0].text == "Test | Result\nA1C | 5.7%\n\nAfter"
    assert "alert" not in sections[0].text


def test_div_wrappers_and_bare_text_are_kept() -> None:
    sections = _sections("<div>Loose text <b>bold</b><div><p>Inner</p></div>tail</div>")
    assert sections[0].text == "Loose text bold\n\nInner\n\ntail"


def test_empty_markup_gives_no_sections_and_br_is_space() -> None:
    assert _sections("<p>   </p><div></div>") == ()
    assert inline_text(parse_fragment("<p>a<br>b</p>")[0]) == "a b"


def test_kind_from_heading_and_collapse() -> None:
    assert kind_from_heading("Symptoms of flu") == "symptoms"
    assert kind_from_heading("What causes it?") == "causes"
    assert kind_from_heading("Preventing infection") == "prevention"
    assert kind_from_heading("Treatments") == "treatment"
    assert kind_from_heading("How tests work") == "diagnosis"
    assert kind_from_heading("Overview") is None
    assert kind_from_heading(None) is None
    assert collapse_ws(" a   b\n c ") == "a b c"


def test_common_helpers() -> None:
    assert make_native_id(" a b/c ") == "a-b/c"
    assert unique_strings(["Aspirin", "aspirin", " Bayer ", "", "Title"], exclude=["title"]) == (
        "Aspirin",
        "Bayer",
    )
    assert parse_us_date("12/22/2015").isoformat() == "2015-12-22"
    assert parse_us_date("2020-09-08T00:00:00").isoformat() == "2020-09-08"
    assert parse_us_date("20250124").isoformat() == "2025-01-24"
    assert parse_us_date("nonsense") is None
    assert parse_us_date(None) is None
    try:
        make_native_id("   ")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("empty native id must be rejected")


def test_build_document_copies_registry_fields() -> None:
    record = make_record()
    doc = build_document(
        record,
        native_id="x 1",
        url="https://a.example.org/x",
        title="  Title  here ",
        language=Language.EN,
        content_type=ContentType.CONDITION,
        sections=[Section(section_id="s0", text="Body text.")],
        retrieved_at=datetime(2026, 11, 15, tzinfo=UTC),
        synonyms=["Title here", "Alt"],
        metadata={"empty": "", "none": None, "ok": ["a"]},
    )
    assert doc.doc_id == "src_a:x-1"
    assert doc.title == "Title here"
    assert doc.license_id == "pd"
    assert doc.attribution == "Source: A"
    assert doc.checksum
    assert doc.synonyms == ("Alt",)
    assert doc.metadata == {"ok": ["a"]}
