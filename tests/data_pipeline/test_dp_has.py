"""HAS publications: glyph clean-up, XML -> sections, member filtering, zip parse and fetch (mock origin)."""

from __future__ import annotations

import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from dp_helpers import make_record

from core.schemas.source import SourceRecord
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.fetch.naming import url_to_relpath
from data_pipeline.parsers import has_publications as has
from data_pipeline.paths import DataPaths
from data_pipeline.registry import get_source

BULLET = ""
LONG = "La personne doit consulter son médecin traitant pour adapter le suivi à sa situation. " * 8
MEMBER = "GuidePatient/p_3000000/2024-05-02_guide_diabete_2024-05-02_10-00-00_text.xml"


def _xml(body: str) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><Document>{body}</Document>'.encode()


def _plain_pages(*texts: str) -> bytes:
    return _xml("".join(f"<Page>{t}</Page>" for t in texts))


def _record() -> SourceRecord:
    record = get_source("has_publications")
    assert record is not None
    return record


def test_clean_glyphs_maps_bullets_and_arrows() -> None:
    assert has.clean_glyphs(f"{BULLET} un  deux  5  x") == "• un → deux ≤ 5 - x"


def test_clean_glyphs_drops_unknown_private_use_and_cid_markers() -> None:
    assert has.clean_glyphs("ab(cid:12)c\U000f0001d") == "abcd"


def test_text_blocks_turns_symbol_bullets_into_list_items() -> None:
    blocks = has.text_blocks(f"Signes :\n{BULLET} fièvre\n{BULLET} toux\n\nFin.")
    assert blocks == ["Signes :", "- fièvre", "- toux", "Fin."]


def test_dehyphenate_joins_split_words_but_keeps_real_hyphens() -> None:
    assert has.dehyphenate("dispo-\nnibles") == "disponibles"
    assert has.dehyphenate("peut-\nêtre") == "peut-être"


def test_build_sections_follows_titles() -> None:
    root = has.etree.fromstring(
        _xml("<Page><Title>Intro</Title><P>Premier.</P><Title>Suivi</Title><P>Second.</P></Page>")
    )
    sections = has.build_sections(root, "Guide")
    assert [s.heading_path[-1] for s in sections] == ["Intro", "Suivi"]
    assert sections[1].text == "Second."


def test_build_sections_without_titles_groups_pages() -> None:
    root = has.etree.fromstring(_plain_pages("Page un.", "Page deux."))
    sections = has.build_sections(root, "Guide")
    assert len(sections) == 1
    assert sections[0].heading_path == ("Guide", "Pages 1-2")


def test_build_sections_splits_long_runs_of_pages() -> None:
    root = has.etree.fromstring(_plain_pages(*["x" * 2500] * 4))
    assert len(has.build_sections(root, "Guide")) == 2


def test_names_and_ids_from_member_path() -> None:
    assert has.slug_title(MEMBER) == "Guide diabete"
    assert has.slug_title("x/_text.xml") == "Publication HAS"
    assert has.slug_date(MEMBER) == date(2024, 5, 2)
    assert has.slug_date("x/not-a-date.xml") is None
    assert has.slug_date("x/2024-13-45_a.xml") is None
    assert has.publication_id(MEMBER) == "p_3000000"
    assert has.publication_id("GuidePatient/a.xml") == ""
    assert has.member_category(MEMBER) == "GuidePatient"


def test_is_wanted_keeps_patient_and_professional_text_files_only() -> None:
    assert has.is_wanted(MEMBER)
    assert not has.is_wanted("AvisMedicaments/p_1/a_text.xml")
    assert not has.is_wanted("GuidePatient/p_1/a_tagged.xml")


def test_member_to_document_builds_french_patient_document() -> None:
    doc = has.member_to_document(
        MEMBER, _plain_pages(LONG), make_record("has_publications"), datetime(2026, 11, 16, tzinfo=UTC)
    )
    assert doc is not None
    assert str(doc.url) == "https://www.has-sante.fr/jcms/p_3000000/fr"
    assert doc.language == "fr"
    assert doc.audience == "patient"
    assert doc.published_on == date(2024, 5, 2)
    assert doc.metadata["title_is_file_slug"] is True


@pytest.mark.parametrize(
    ("member", "data"),
    [
        ("GuidePatient/a_text.xml", _plain_pages(LONG)),  # no publication folder id
        (MEMBER, b"<Document><Page>broken"),  # malformed XML
        (MEMBER, _xml("")),  # no text
        (MEMBER, _plain_pages("x" * (has.MAX_CHARS + 1))),  # too long
    ],
)
def test_member_to_document_skips_unusable_members(member: str, data: bytes) -> None:
    assert has.member_to_document(member, data, make_record("has_publications"), datetime.now(UTC)) is None


async def _no_sleep(_: float) -> None:
    return None


def _fetcher(paths: DataPaths, handler: object) -> Fetcher:
    return Fetcher(
        _record(),
        paths,
        FetchConfig(default_rps=1000.0, backoff_base_s=0.0, max_retries=0),
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        sleep=_no_sleep,
    )


def _write_zip(paths: DataPaths, members: dict[str, bytes]) -> Path:
    target = paths.raw_dir("has_publications") / url_to_relpath(has.ZIP_URL)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return target


def test_parse_reads_wanted_members_in_order(paths: DataPaths) -> None:
    _write_zip(
        paths,
        {
            MEMBER: _plain_pages(LONG),
            "AvisMedicaments/p_9/a_text.xml": _plain_pages(LONG),
            "RecommandationVaccinale/c_77/2023-01-01_vaccin_text.xml": _plain_pages(LONG),
        },
    )
    docs = list(has.parse(paths, _record()))
    assert [d.metadata["category"] for d in docs] == ["GuidePatient", "RecommandationVaccinale"]
    assert docs[1].content_type == "vaccine"


def test_parse_without_zip_names_the_missing_file(paths: DataPaths) -> None:
    with pytest.raises(FileNotFoundError, match=has.ZIP_NAME):
        list(has.parse(paths, _record()))


@pytest.mark.asyncio
async def test_fetch_downloads_the_zip(paths: DataPaths) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK-bytes", headers={"content-type": "application/zip"})

    assert await has.fetch(_fetcher(paths, handler)) == 1
    assert (paths.raw_dir("has_publications") / url_to_relpath(has.ZIP_URL)).read_bytes() == b"PK-bytes"


@pytest.mark.asyncio
async def test_fetch_raises_when_origin_refuses(paths: DataPaths) -> None:
    with pytest.raises(RuntimeError, match="cannot download"):
        await has.fetch(_fetcher(paths, lambda _r: httpx.Response(404, text="nope")))
