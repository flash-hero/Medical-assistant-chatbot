"""MediaWiki plain-text extract (`prop=extracts&explaintext=1&exsectionformat=wiki`) -> structured Sections.

The extract marks headings as `== Heading ==` (level 2) to `====== Heading ======` (level 6) and separates
paragraphs with single newlines. Sections that only list references, external links or further reading are
dropped (in English, French and Arabic); everything under a dropped level-2 heading goes with it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from core.schemas.document import Section

_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$")

_DROP_HEADINGS: dict[str, frozenset[str]] = {
    "en": frozenset(
        {
            "references",
            "external links",
            "further reading",
            "see also",
            "notes",
            "citations",
            "bibliography",
            "sources",
            "footnotes",
            "works cited",
            "general references",
            "cited sources",
            "general and cited references",
        }
    ),
    "fr": frozenset(
        {
            "notes et références",
            "références",
            "notes",
            "voir aussi",
            "liens externes",
            "articles connexes",
            "bibliographie",
            "sources",
            "annexes",
            "liens internes",
            "références bibliographiques",
            "lien externe",
        }
    ),
    "ar": frozenset(
        {
            "مراجع",
            "المراجع",
            "وصلات خارجية",
            "روابط خارجية",
            "انظر أيضًا",
            "انظر أيضا",
            "انظر أيضاً",
            "هوامش",
            "ملاحظات",
            "قراءة موسعة",
            "مصادر",
            "المصادر",
            "الهوامش",
            "وصلات خارجيه",
            "ببليوغرافيا",
            "فهرس",
        }
    ),
}

_KIND_KEYWORDS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "en": (
        ("symptoms", ("signs and symptoms", "symptoms", "presentation", "clinical features")),
        ("causes", ("causes", "etiology", "aetiology", "risk factors", "pathophysiology")),
        ("diagnosis", ("diagnosis", "screening", "diagnostic")),
        ("treatment", ("treatment", "management", "therapy", "medications", "medication")),
        ("prevention", ("prevention", "vaccination", "vaccine")),
        ("prognosis", ("prognosis", "outlook", "complications")),
    ),
    "fr": (
        ("symptoms", ("symptômes", "signes et symptômes", "signes cliniques", "présentation clinique")),
        ("causes", ("causes", "étiologie", "facteurs de risque", "physiopathologie")),
        ("diagnosis", ("diagnostic", "dépistage")),
        ("treatment", ("traitement", "traitements", "prise en charge", "thérapie")),
        ("prevention", ("prévention", "vaccination")),
        ("prognosis", ("pronostic", "évolution", "complications")),
    ),
    "ar": (
        ("symptoms", ("الأعراض", "أعراض", "العلامات والأعراض", "الأعراض والعلامات")),
        ("causes", ("الأسباب", "أسباب", "عوامل الخطر", "الآلية المرضية", "علم الأمراض")),
        ("diagnosis", ("التشخيص", "تشخيص", "الفحص")),
        ("treatment", ("العلاج", "علاج", "المعالجة", "العلاجات")),
        ("prevention", ("الوقاية", "وقاية", "التطعيم", "اللقاح")),
        ("prognosis", ("التشخيص المتوقع", "المآل", "المضاعفات", "التوقعات")),
    ),
}


@dataclass(frozen=True)
class _Block:
    path: tuple[str, ...]
    lines: tuple[str, ...]


def _fold(heading: str) -> str:
    return unicodedata.normalize("NFC", " ".join(heading.split())).casefold()


def _kind_for(heading: str, lang: str) -> str | None:
    folded = _fold(heading)
    for kind, keywords in _KIND_KEYWORDS.get(lang, ()):
        if any(folded == word or folded.startswith(word + " ") for word in keywords):
            return kind
    return None


def _split_blocks(extract: str, title: str, lang: str) -> list[tuple[tuple[str, ...], list[str], bool]]:
    """(heading_path, text lines, dropped) per section, in document order; the intro comes first."""
    dropped_words = _DROP_HEADINGS.get(lang, frozenset())
    blocks: list[tuple[tuple[str, ...], list[str], bool]] = [((title,), [], False)]
    stack: list[tuple[int, str]] = []
    top_dropped = False
    for raw in extract.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        match = _HEADING.match(line)
        if match is None:
            if line:
                blocks[-1][1].append(line)
            continue
        level, text = len(match.group(1)), match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
        if level == 2:
            top_dropped = _fold(text) in dropped_words
        blocks.append(((title, *(h for _, h in stack)), [], top_dropped))
    return blocks


def extract_to_sections(extract: str, title: str, lang: str) -> tuple[Section, ...]:
    """Sections with hierarchical heading paths ("Title", "Causes", "Genetics"); empty ones are skipped."""
    sections: list[Section] = []
    for path, lines, dropped in _split_blocks(extract, title, lang):
        text = "\n\n".join(lines).strip()
        if dropped or not text:
            continue
        kind = "summary" if len(path) == 1 else _kind_for(path[1], lang)
        sections.append(Section(section_id=f"s{len(sections)}", heading_path=path, text=text, kind=kind))
    return tuple(sections)
