"""HAS publication texts (data.gouv.fr dataset 'Textes des publications de la HAS') -> Documents.

The dataset is one zip of semi-structured XML, one `*_text.xml` per PDF (plain text by page) and, for PDF/UA
files, a `*_tagged.xml` twin. Only the `_text.xml` files are read: they exist for every PDF. Two layouts
occur:
page text as a bare string, or nested `<P>`/`<Title>` elements; both are handled.

Scope: patient guides, vaccination recommendations, professional recommendations and the ALD physician guides.
Medicine opinions (about 26,000 files), product and service opinions, studies, methodology and programme
evaluations are not ingested: they serve reimbursement decisions, not patient information. Very long
documents (evidence reviews, above MAX_CHARS) are skipped.

Titles are not in the XML: the title is the file-name slug, humanised. The citation URL is the HAS publication
page `https://www.has-sante.fr/jcms/<id>/fr`, derived from the folder id.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import structlog
from lxml import etree

from core.schemas.document import Document, Section
from core.schemas.source import ContentType, Language, SourceRecord
from data_pipeline.fetch.client import FetchConfig, Fetcher
from data_pipeline.parsers.common import build_document
from data_pipeline.paths import DataPaths

SOURCE_ID = "has_publications"
ZIP_NAME = "TextesPublicationsHAS_XML.zip"
ZIP_URL = f"https://minio.data.has-sante.fr/has-text-extract/{ZIP_NAME}"
FETCH_CONFIG = FetchConfig(default_rps=0.5, timeout_s=300.0)
BUILD_OPTIONS = {"min_chars": 400, "strip_repeated_lines": True}
MAX_CHARS = 120_000
SECTION_TARGET_CHARS = 4_000
CATEGORIES: dict[str, tuple[str, ContentType]] = {
    "GuidePatient": ("patient", ContentType.GUIDELINE),
    "RecommandationVaccinale": ("professional", ContentType.VACCINE),
    "RecommandationsProfessionnelles": ("professional", ContentType.GUIDELINE),
    "GuideMedecinALD": ("professional", ContentType.GUIDELINE),
}
_KEEP_HYPHEN_BEFORE = frozenset(
    [
        "être",
        "il",
        "elle",
        "on",
        "ce",
        "t",
        "je",
        "tu",
        "nous",
        "vous",
        "ils",
        "elles",
        "ci",
        "là",
        "à",
        "ceci",
        "cela",
        "celui",
        "celle",
        "y",
        "en",
        "pas",
    ]
)
_BULLET = re.compile(r"^\s*[•▪●◦·–—-]\s+")
_SLUG_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
_SLUG_TAIL = re.compile(r"(_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(_\d+)?)?_text$")
_FOLDER_ID = re.compile(r"^[pcr]_\d+$")
# PDF text extraction leaves Symbol/Wingdings glyphs in the Unicode private-use area (U+F020-U+F0FF): list
# bullets, arrows, check boxes. They are mapped to plain characters; any other private-use code point and the
# "(cid:N)" markers of unresolved glyphs are removed (kept in the text they would quarantine the document).
_BULLET_GLYPHS = ""
_GLYPH_MAP = {
    **{ord(c): "•" for c in _BULLET_GLYPHS},
    **{ord(c): "→" for c in ""},
    ord(""): "≤",
    ord(""): "≥",
    ord(""): "-",
    ord(""): " ",
}
_PRIVATE_USE = re.compile("[-󰀀-􏿿]")
_CID = re.compile(r"\(cid:\d+\)")
_LINE_HYPHEN = re.compile(r"(\w)-[ \t]*\n[ \t]*(\w[^\n]*)")
log = structlog.get_logger(__name__)


async def fetch(fetcher: Fetcher, _paths: DataPaths | None = None, *, limit: int | None = None) -> int:
    """Download the zip (robots-exempt: minio.data.has-sante.fr serves no robots.txt and the file is the
    dataset's documented download). `limit` is ignored; the file is only meaningful whole."""
    result = await fetcher.fetch(ZIP_URL, robots_exempt=True, refresh=True)
    if result.path is None:
        raise RuntimeError(f"cannot download {ZIP_URL}: HTTP {result.status}")
    return 1


# ---- text extraction ------------------------------------------------------------------------------
def clean_glyphs(text: str) -> str:
    """Map PDF symbol-font glyphs to bullets/arrows, drop the rest of the private-use area and cid markers."""
    return _PRIVATE_USE.sub("", _CID.sub("", text.translate(_GLYPH_MAP)))


def _join_hyphenated(match: re.Match[str]) -> str:
    following = match.group(2)
    word = re.match(r"\w+", following)
    keep = word is not None and word.group(0).lower() in _KEEP_HYPHEN_BEFORE
    return f"{match.group(1)}-{following}" if keep else f"{match.group(1)}{following}"


def dehyphenate(text: str) -> str:
    """Join words split by a line-break hyphen, keeping real hyphens before "être", "il", "ce"..."""
    return _LINE_HYPHEN.sub(_join_hyphenated, text)


def _flush(block: list[str], out: list[str]) -> None:
    text = " ".join(" ".join(block).split())
    if text:
        out.append(f"- {_BULLET.sub('', text)}" if _BULLET.match(block[0]) else text)
    block.clear()


def text_blocks(raw: str) -> list[str]:
    """Paragraphs of a page of plain text; a bullet line opens a new "- " item."""
    out: list[str] = []
    block: list[str] = []
    for line in dehyphenate(clean_glyphs(raw).replace("\xad", "").replace("\xa0", " ")).split("\n"):
        if not line.strip():
            _flush(block, out)
            continue
        if _BULLET.match(line):
            _flush(block, out)
        block.append(line)
    _flush(block, out)
    return out


def page_blocks(page: etree._Element) -> list[tuple[bool, str]]:
    """(is_heading, text) blocks of one <Page>, in order."""
    if not page.xpath(".//P|.//Title"):
        return [(False, text) for text in text_blocks("".join(page.itertext()))]
    found = [
        (el.tag == "Title", " ".join(clean_glyphs("".join(el.itertext())).split()))
        for el in page.iter("P", "Title")
        if not el.xpath(".//P|.//Title")
    ]
    return [(heading, text) for heading, text in found if text]


def build_sections(root: etree._Element, title: str) -> tuple[Section, ...]:
    """Sections follow <Title> headings when present, otherwise runs of pages of about 4,000 characters."""
    sections: list[Section] = []
    buffer: list[str] = []
    heading = ""
    span = [0, 0]

    def flush() -> None:
        text = "\n\n".join(buffer).strip()
        buffer.clear()
        if text:
            label = heading or f"Pages {span[0]}-{span[1]}"
            sections.append(Section(section_id=f"s{len(sections)}", heading_path=(title, label), text=text))

    for number, page in enumerate(root.iter("Page"), start=1):
        for is_heading, text in page_blocks(page):
            if is_heading:
                flush()
                heading, span[0] = text, number
            else:
                span[0] = span[0] or number
                buffer.append(text)
        span[1] = number
        if not heading and sum(len(b) for b in buffer) >= SECTION_TARGET_CHARS:
            flush()
            span[0] = number + 1
    flush()
    return tuple(sections)


# ---- names ------------------------------------------------------------------------------------------
def slug_title(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = _SLUG_TAIL.sub("", _SLUG_DATE.sub("", stem))
    words = " ".join(stem.replace("_", " ").split())
    return words[:1].upper() + words[1:] if words else "Publication HAS"


def slug_date(filename: str) -> date | None:
    match = _SLUG_DATE.match(filename.rsplit("/", 1)[-1])
    try:
        return date.fromisoformat(match.group(1)) if match else None
    except ValueError:
        return None


def publication_id(member: str) -> str:
    """Last jcms-style folder id on the path (p_123 / c_123 / r_123); '' when there is none."""
    folders = [part for part in member.split("/")[:-1] if _FOLDER_ID.match(part)]
    return folders[-1] if folders else ""


def member_category(member: str) -> str:
    return member.split("/", 1)[0]


def is_wanted(member: str) -> bool:
    return member_category(member) in CATEGORIES and member.endswith("_text.xml")


# ---- documents --------------------------------------------------------------------------------------
def member_to_document(
    member: str, data: bytes, record: SourceRecord, retrieved_at: datetime
) -> Document | None:
    pub = publication_id(member)
    if not pub:
        return None
    try:
        root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        log.warning("has_xml_invalid", member=member, error=str(exc))
        return None
    title = slug_title(member)
    sections = build_sections(root, title)
    if not sections or sum(len(s.text) for s in sections) > MAX_CHARS:
        return None
    audience, content_type = CATEGORIES[member_category(member)]
    digest = hashlib.sha1(member.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return build_document(
        record,
        native_id=f"{pub}-{digest}",
        url=f"https://www.has-sante.fr/jcms/{pub}/fr",
        title=title,
        language=Language.FR,
        content_type=content_type,
        sections=sections,
        retrieved_at=retrieved_at,
        published_on=slug_date(member),
        audience=audience,
        metadata={
            "category": member_category(member),
            "publication_id": pub,
            "source_file": member,
            "title_is_file_slug": True,
        },
    )


def find_zip(paths: DataPaths, record: SourceRecord) -> Path:
    found = sorted(paths.raw_dir(record.id).rglob(ZIP_NAME))
    if not found:
        raise FileNotFoundError(f"{ZIP_NAME} not found under {paths.raw_dir(record.id)}; run fetch first")
    return found[-1]


def parse(paths: DataPaths, record: SourceRecord) -> Iterator[Document]:
    archive = find_zip(paths, record)
    stamp = datetime.fromtimestamp(archive.stat().st_mtime, tz=UTC)
    with zipfile.ZipFile(archive) as bundle:
        for info in sorted(bundle.infolist(), key=lambda i: i.filename):
            if not is_wanted(info.filename):
                continue
            doc = member_to_document(info.filename, bundle.read(info), record, stamp)
            if doc is not None:
                yield doc
