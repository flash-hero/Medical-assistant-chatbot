"""HTML fragment -> structured plain-text Sections (headings, paragraphs, "- " lists, tables).

Pure functions over lxml elements; nothing here fetches or writes. Link markup is dropped but anchor text is
kept; images, scripts, styles and form controls are ignored.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from lxml import html as lxml_html
from lxml.html import HtmlElement

from core.schemas.document import Section

HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "iframe",
        "form",
        "button",
        "select",
        "input",
        "textarea",
        "img",
        "figure",
    }
)
PARAGRAPH_TAGS = frozenset({"p", "blockquote", "pre", "dt", "dd", "figcaption", "summary", "caption"})
BLOCK_TAGS = (
    frozenset(
        {
            "div",
            "section",
            "article",
            "main",
            "ul",
            "ol",
            "table",
            "dl",
            "details",
            "hr",
            "aside",
            "header",
            "footer",
        }
    )
    | PARAGRAPH_TAGS
    | frozenset(HEADINGS)
)
_WS = re.compile(r"[ \t\r\n   ]+")
_KIND_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"when to (see|call|seek|get)|seek (medical )?(care|help)|call (your|a) (doctor|health)|emergency",
            re.I,
        ),
        "when_to_seek_care",
    ),
    (re.compile(r"\bsymptoms?\b|signs?\b", re.I), "symptoms"),
    (re.compile(r"\bcauses?\b|risk factors?", re.I), "causes"),
    (re.compile(r"\bdiagnos|\btests?\b|screening", re.I), "diagnosis"),
    (re.compile(r"\btreatments?\b|\btherapy\b|management", re.I), "treatment"),
    (re.compile(r"\bprevent", re.I), "prevention"),
)


def collapse_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def kind_from_heading(heading: str | None) -> str | None:
    """Map a heading to a coarse section kind used by retrieval filters (None when unknown)."""
    if not heading:
        return None
    for pattern, kind in _KIND_RULES:
        if pattern.search(heading):
            return kind
    return None


def inline_text(el: HtmlElement) -> str:
    """Text of an element with inline markup flattened; <br> becomes a space."""
    parts: list[str] = []

    def walk(node: HtmlElement) -> None:
        if not isinstance(node.tag, str) or node.tag in SKIP_TAGS:
            return
        if node.tag == "br":
            parts.append(" ")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(el)
    return collapse_ws("".join(parts))


def _own_text_without_lists(li: HtmlElement) -> str:
    parts: list[str] = [li.text or ""]
    for child in li:
        if isinstance(child.tag, str) and child.tag not in {"ul", "ol"}:
            parts.append(inline_text(child) if child.tag not in SKIP_TAGS else "")
        parts.append(child.tail or "")
    return collapse_ws(" ".join(parts))


def _list_lines(el: HtmlElement, depth: int = 0) -> Iterator[str]:
    for li in el.findall("li"):
        text = _own_text_without_lists(li)
        if text:
            yield f"{'  ' * depth}- {text}"
        for nested in li:
            if isinstance(nested.tag, str) and nested.tag in {"ul", "ol"}:
                yield from _list_lines(nested, depth + 1)


def _table_lines(table: HtmlElement) -> Iterator[str]:
    for row in table.iter("tr"):
        cells = [inline_text(c) for c in row if isinstance(c.tag, str) and c.tag in {"td", "th"}]
        if any(cells):
            yield " | ".join(cells)


@dataclass(frozen=True)
class Event:
    kind: str  # "heading" | "block"
    text: str
    level: int = 0


def iter_events(el: HtmlElement) -> Iterator[Event]:
    tag = el.tag
    if not isinstance(tag, str) or tag in SKIP_TAGS:
        return
    if tag in HEADINGS:
        text = inline_text(el)
        if text:
            yield Event("heading", text, HEADINGS[tag])
        return
    if tag in {"ul", "ol"}:
        lines = "\n".join(_list_lines(el))
        if lines:
            yield Event("block", lines)
        return
    if tag == "table":
        lines = "\n".join(_table_lines(el))
        if lines:
            yield Event("block", lines)
        return
    if tag in PARAGRAPH_TAGS:
        text = inline_text(el)
        if text:
            yield Event("block", text)
        return
    yield from _container_events(el)


def _container_events(el: HtmlElement) -> Iterator[Event]:
    pending: list[str] = [el.text or ""]

    def flush() -> Iterator[Event]:
        text = collapse_ws(" ".join(pending))
        pending.clear()
        if text:
            yield Event("block", text)

    for child in el:
        if isinstance(child.tag, str) and child.tag in BLOCK_TAGS:
            yield from flush()
            yield from iter_events(child)
        elif isinstance(child.tag, str) and child.tag not in SKIP_TAGS:
            pending.append(inline_text(child))
        pending.append(child.tail or "")
    yield from flush()


def parse_fragment(markup: str) -> HtmlElement:
    return lxml_html.fragment_fromstring(markup, create_parent="div")


def html_to_sections(
    root: HtmlElement, title: str, *, intro_kind: str | None = "summary"
) -> tuple[Section, ...]:
    """Split content into Sections. Heading hierarchy becomes heading_path (title first)."""
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    blocks: list[str] = []

    def flush() -> None:
        if not blocks:
            return
        path = (title, *(text for _, text in stack))
        kind = kind_from_heading(path[-1]) if stack else intro_kind
        sections.append(
            Section(section_id=f"s{len(sections)}", heading_path=path, text="\n\n".join(blocks), kind=kind)
        )
        blocks.clear()

    for event in iter_events(root):
        if event.kind == "heading":
            flush()
            while stack and stack[-1][0] >= event.level:
                stack.pop()
            stack.append((event.level, event.text))
        else:
            blocks.append(event.text)
    flush()
    return tuple(sections)
