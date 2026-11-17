import hashlib
import itertools
import random

from hypothesis import given, settings
from hypothesis import strategies as st
from rag_fixtures import make_doc

from rag.chunking import (
    ChunkerConfig,
    chunk_document,
    context_header,
    plan_ranges,
    publisher_label,
)
from rag.expansion import merge_overlapping
from rag.segment import segment
from rag.tokens import estimate_tokens

_EN_WORDS = [
    "blood",
    "sugar",
    "insulin",
    "kidney",
    "heart",
    "lungs",
    "doctor",
    "fever",
    "cough",
    "rash",
    "pain",
    "vaccine",
    "sleep",
    "diet",
]
_FR_WORDS = [
    "sang",
    "sucre",
    "insuline",
    "rein",
    "cœur",
    "poumons",
    "médecin",
    "fièvre",
    "toux",
    "douleur",
    "vaccin",
    "sommeil",
]
_AR_WORDS = [
    "الدم",
    "السكر",
    "الأنسولين",
    "الكلى",
    "القلب",
    "الرئتين",
    "الطبيب",
    "الحمى",
    "السعال",
    "الألم",
    "اللقاح",
    "النوم",
]
_WORDS = {"en": _EN_WORDS, "fr": _FR_WORDS, "ar": _AR_WORDS}
_END = {"en": ".", "fr": ".", "ar": "؟"}


def _sentences(rng: random.Random, lang: str, n: int) -> str:
    out = []
    for _ in range(n):
        words = [rng.choice(_WORDS[lang]) for _ in range(rng.randint(5, 30))]
        if lang != "ar":
            words[0] = words[0].capitalize()
        out.append(" ".join(words) + _END[lang])
    return " ".join(out)


def test_small_sibling_sections_merge_into_one_chunk_with_header():
    doc = make_doc("asthma")
    chunks = chunk_document(doc, publisher="DemoPlus")
    assert len(chunks) == 1
    c = chunks[0]
    assert c.section_id == "s1+s2+s3"
    assert c.parent_id == "demo_src:asthma#s1+s2+s3"
    assert c.chunk_id == "demo_src:asthma#s1+s2+s3#0"
    assert c.heading_path == ("Asthma",)
    assert c.context_header == "DemoPlus | Asthma | en | reviewed 2025-05-01"
    assert "Symptoms\nSymptoms of asthma include:\n- wheezing" in c.text
    assert c.checksum == hashlib.sha256(f"{c.context_header}\n{c.text}".encode()).hexdigest()
    assert c.embedding_text().startswith("title: Asthma | text: DemoPlus | Asthma")


def test_drug_label_sections_are_never_merged():
    doc = make_doc("diabetes", content_type="drug_label")
    chunks = chunk_document(doc, publisher="DemoPlus")
    assert [c.section_id for c in chunks] == ["s1", "s2", "s3"]
    assert chunks[1].context_header == "DemoPlus | Diabetes > Symptoms | en | reviewed 2025-05-01"


def test_sections_under_different_roots_do_not_merge():
    doc = make_doc(
        "migraine",
        sections=[
            ("a", ("Migraine", "Summary"), "Short summary."),
            ("b", ("Other", "Detail"), "Short detail."),
        ],
    )
    assert [c.section_id for c in chunk_document(doc, publisher="P")] == ["a", "b"]


def test_tiny_genetics_style_sections_join_the_summary_across_kinds():
    rng = random.Random(11)
    summary = _sentences(rng, "en", 40)  # > max tokens, so the group spans several chunks
    doc = make_doc(
        "measles",
        content_type="genetics",
        sections=[
            ("s0", ("Measles",), summary),
            ("s1", ("Measles", "Inheritance"), "Inheritance pattern: Autosomal recessive."),
            ("s2", ("Measles", "Related genes"), "Related genes: CYP17A1."),
        ],
    )
    from core.schemas.document import Section

    doc = doc.model_copy(
        update={
            "sections": tuple(
                Section(section_id=s.section_id, heading_path=s.heading_path, text=s.text, kind=k)
                for s, k in zip(doc.sections, ["summary", "inheritance", "related_genes"], strict=True)
            )
        }
    )
    chunks = chunk_document(doc, publisher="P")
    assert {c.section_id for c in chunks} == {"s0+s1+s2"}
    assert chunks[0].section_kind == "summary+inheritance+related_genes"
    assert chunks[-1].text.endswith("Related genes\nRelated genes: CYP17A1.")
    assert "Inheritance\nInheritance pattern: Autosomal recessive." in chunks[-1].text


def test_long_section_is_split_with_sentence_aligned_overlap():
    rng = random.Random(7)
    text = _sentences(rng, "en", 120)
    doc = make_doc("diabetes", sections=[("s1", ("Diabetes", "Overview"), text)])
    chunks = chunk_document(doc, publisher="P")
    assert len(chunks) >= 3
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    sentences = {text[u.start : u.end] for u in segment(text, "en")}
    for c in chunks:
        assert c.token_estimate <= 520
        assert c.text in text
    assert all(c.token_estimate >= 300 for c in chunks[:-1])
    for a, b in itertools.pairwise(chunks):
        overlap = next((k for k in range(len(b.text), 0, -1) if a.text.endswith(b.text[:k])), 0)
        assert overlap > 0
        seam = b.text[:overlap]
        assert all(seam[u.start : u.end] in sentences for u in segment(seam, "en"))  # whole sentences
        assert estimate_tokens(seam) <= 60
    assert " ".join(merge_overlapping([c.text for c in chunks]).split()) == " ".join(text.split())


def test_ids_and_checksums_are_deterministic():
    doc = make_doc("measles")
    assert chunk_document(doc, publisher="P") == chunk_document(doc, publisher="P")


def test_header_without_review_date_and_in_arabic():
    doc = make_doc("asthma", language="ar", reviewed_on=None, title="الربو")
    header = chunk_document(doc, publisher="DemoPlus")[0].context_header
    assert header == "DemoPlus | الربو | ar"


def test_header_drops_duplicated_title():
    assert context_header("P", "Asthma", ("asthma", "Causes"), "en", None) == "P | Asthma > Causes | en"


def test_publisher_label_from_attribution():
    assert publisher_label("Source: MedlinePlus, U.S. National Library of Medicine", "fallback") == (
        "MedlinePlus"
    )
    assert publisher_label("", "Fallback Name") == "Fallback Name"
    assert publisher_label("Source : Info Médicament", "x") == "Info Médicament"


def test_list_block_is_never_split_across_chunks():
    rng = random.Random(3)
    listing = "Warning signs include:\n" + "\n".join(f"- sign {i} {rng.choice(_EN_WORDS)}" for i in range(12))
    text = _sentences(rng, "en", 40) + "\n\n" + listing + "\n\n" + _sentences(rng, "en", 40)
    doc = make_doc("asthma", sections=[("s1", ("Asthma", "Signs"), text)])
    chunks = chunk_document(doc, publisher="P")
    assert len(chunks) > 1
    assert sum(listing in c.text for c in chunks) >= 1
    assert all(("- sign 5" in c.text) == ("- sign 6" in c.text) for c in chunks)


# ---- properties -----------------------------------------------------------------------------------
@settings(max_examples=300, deadline=None)
@given(st.lists(st.integers(min_value=1, max_value=700), min_size=1, max_size=80))
def test_plan_ranges_cover_everything_with_bounded_overlap(tokens):
    cfg = ChunkerConfig()
    ranges = plan_ranges(tokens, cfg)
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(tokens)
    for s, e in ranges:
        assert s < e
        size = sum(tokens[s:e])
        # a single giant unit may exceed anything; otherwise max, or the hard ceiling for runt rescue
        assert e - s == 1 or size <= cfg.hard_max_tokens
        if e - s > 1 and size > cfg.max_tokens:
            head, tail = sum(tokens[s : e - 1]), tokens[e - 1]
            assert head < cfg.runt_tokens + cfg.overlap_tokens or tail < cfg.runt_tokens or e == len(tokens)
    for (s1, e1), (s2, e2) in itertools.pairwise(ranges):
        assert s1 < s2 <= e1 < e2  # progress, contiguous coverage, overlap only at the seam
        assert sum(tokens[s2:e1]) <= cfg.overlap_tokens


@settings(max_examples=60, deadline=None)
@given(
    st.integers(min_value=0, max_value=10_000),
    st.sampled_from(["en", "fr", "ar"]),
    st.lists(st.integers(min_value=1, max_value=60), min_size=1, max_size=6),
    st.sampled_from(["condition", "drug_label"]),
)
def test_chunks_lose_nothing_and_duplicate_only_overlap(seed, lang, sizes, ctype):
    rng = random.Random(seed)
    sections = [(f"s{i}", ("Topic", f"H{i}"), _sentences(rng, lang, n)) for i, n in enumerate(sizes)]
    doc = make_doc("asthma", language=lang, content_type=ctype, sections=sections)
    chunks = chunk_document(doc, publisher="P")
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert chunk_document(doc, publisher="P") == chunks
    by_parent: dict[str, list[str]] = {}
    for c in chunks:
        by_parent.setdefault(c.parent_id, []).append(c.text)
        assert c.parent_id == f"{c.doc_id}#{c.section_id}"
        assert c.chunk_id == f"{c.parent_id}#{c.ordinal}"
    merged = {pid: merge_overlapping(texts) for pid, texts in by_parent.items()}
    for sid, _, text in sections:
        owner = next(pid for pid in merged if sid in pid.split("#")[1].split("+"))
        assert " ".join(text.split()) in " ".join(merged[owner].split())
    total_chunk_chars = sum(len(c.text) for c in chunks)
    total_text_chars = sum(len(t) + 12 for _, _, t in sections)
    assert total_chunk_chars <= total_text_chars * 1.25
