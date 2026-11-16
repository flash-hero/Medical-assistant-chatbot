from hypothesis import given, settings
from hypothesis import strategies as st

from rag.segment import Unit, segment
from rag.tokens import estimate_tokens


def _texts(text: str, units: tuple[Unit, ...]) -> list[str]:
    return [text[u.start : u.end] for u in units]


def test_english_sentences_respect_abbreviations_and_decimals():
    text = "Diabetes is a disease. It affects blood sugar. See Dr. Smith e.g. today. Take 2.5 mg. Then rest."
    assert _texts(text, segment(text, "en")) == [
        "Diabetes is a disease.",
        "It affects blood sugar.",
        "See Dr. Smith e.g. today.",
        "Take 2.5 mg.",
        "Then rest.",
    ]


def test_initials_and_us_abbreviation_do_not_split():
    text = "The U.S. Food and Drug Administration approved it. J. Doe agreed."
    assert _texts(text, segment(text, "en")) == [
        "The U.S. Food and Drug Administration approved it.",
        "J. Doe agreed.",
    ]


def test_french_spacing_before_question_mark_and_abbreviations():
    text = "Qu'est-ce que le diabète ? C'est une maladie. M. Dupont est là. Voir p. ex. la page 3."
    assert _texts(text, segment(text, "fr")) == [
        "Qu'est-ce que le diabète ?",
        "C'est une maladie.",
        "M. Dupont est là.",
        "Voir p. ex. la page 3.",
    ]


def test_arabic_question_mark_and_full_stop():
    text = "ما هو السكري؟ إنه مرض مزمن. يؤثر على مستوى السكر في الدم"
    assert _texts(text, segment(text, "ar")) == [
        "ما هو السكري؟",
        "إنه مرض مزمن.",
        "يؤثر على مستوى السكر في الدم",
    ]


def test_long_arabic_sentence_splits_on_arabic_comma_and_semicolon():
    clause = "يشعر المريض بالعطش الشديد والتعب المستمر وكثرة التبول خلال النهار والليل"
    text = "، ".join([clause] * 12) + "؛ " + "، ".join([clause] * 12) + "."
    units = segment(text, "ar", max_unit_tokens=120)
    assert len(units) > 2
    assert all(estimate_tokens(text[u.start : u.end], "ar") <= 120 for u in units)
    assert all(text[u.start : u.end].endswith(("،", "؛", ".")) for u in units[:-1])


def test_list_with_lead_in_is_one_unit_and_table_is_intact():
    text = (
        "Symptoms include:\n- thirst\n- hunger\n  that lasts\n- fatigue\n\n"
        "See a doctor.\n\n| Test | Range |\n| A1C | < 5.7% |"
    )
    units = segment(text, "en")
    assert _texts(text, units) == [
        "Symptoms include:\n- thirst\n- hunger\n  that lasts\n- fatigue",
        "See a doctor.",
        "| Test | Range |\n| A1C | < 5.7% |",
    ]
    assert [u.kind for u in units] == ["list", "sentence", "table"]


def test_single_pipe_rows_from_the_data_track_are_a_table():
    text = (
        "Barrier methods\nMale condom | A thin sheath. It helps.\nFemale condom | A flexible pouch. Use once."
    )
    units = segment(text, "en")
    assert [u.kind for u in units] == ["sentence", "table"]
    assert text[units[1].start : units[1].end].startswith("Male condom | A thin sheath. It helps.\nFemale")


def test_oversized_list_splits_only_at_item_boundaries():
    items = [f"- item number {i} has a reasonably long description of a symptom" for i in range(40)]
    text = "\n".join(items)
    units = segment(text, "en", max_unit_tokens=60)
    assert len(units) > 1
    for u in units:
        piece = text[u.start : u.end]
        assert piece.startswith("- item number")
        assert estimate_tokens(piece) <= 60


def test_word_level_fallback_for_unbreakable_text():
    text = " ".join(["word"] * 400)
    units = segment(text, "en", max_unit_tokens=50)
    assert all(estimate_tokens(text[u.start : u.end]) <= 50 for u in units)


_ALPHABET = st.sampled_from(
    [*list("abc XYZ.,;:?!-|\n"), "é", "؟", "،", "؛", "ب", "ة", "  ", "\n\n", "- ", "Dr. ", "e.g. "]
)


@settings(max_examples=300, deadline=None)
@given(st.lists(_ALPHABET, min_size=1, max_size=300).map("".join), st.sampled_from(["en", "fr", "ar"]))
def test_units_partition_text_without_loss(text, lang):
    units = segment(text, lang, max_unit_tokens=40)
    pos = 0
    for u in units:
        assert u.start >= pos
        assert text[pos : u.start].strip() == ""  # only whitespace between units
        piece = text[u.start : u.end]
        assert piece == piece.strip()
        assert piece
        pos = u.end
    assert text[pos:].strip() == ""
