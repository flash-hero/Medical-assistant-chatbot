"""Co-occurrence ("combination") entries of the risk lexicon: parsing and token matching."""

from __future__ import annotations

import pytest

from app.config_files import ConfigFileError
from app.guardrails.lexicon_combos import (
    MAX_SPAN,
    Combination,
    TokenIndex,
    WordPattern,
    find,
    parse_combinations,
    token_forms,
)
from app.guardrails.lexicon_text import normalize
from core.schemas.chat import RiskKind


def _combo(groups: list[list[str]], lang: str = "en") -> Combination:
    raw = {lang: [groups]}
    (combo,) = parse_combinations(raw, RiskKind.EMERGENCY, "test.yaml")
    return combo


def _find(groups: list[list[str]], text: str, lang: str = "en") -> tuple[int, ...] | None:
    tokens = normalize(text).split()
    return find(_combo(groups, lang), TokenIndex(tuple(tokens)))


@pytest.mark.parametrize(
    ("word", "token", "expected"),
    [
        ("chest", "chest", True),
        ("chest", "chests", False),
        ("breath*", "breathing", True),
        ("breath*", "breath", True),
        ("breath*", "abreath", False),
        ("*ache", "headache", True),
        ("*ache", "aches", False),
        ("*bleed*", "nosebleeds", True),
    ],
)
def test_word_pattern_wildcards(word: str, token: str, expected: bool) -> None:
    assert WordPattern.parse(word, "en").matches(token) is expected


def test_word_pattern_rejects_bare_wildcard() -> None:
    with pytest.raises(ConfigFileError, match="empty"):
        WordPattern.parse("*", "en")


def test_groups_match_in_any_order_with_filler_words() -> None:
    groups = [["chest"], ["pain", "pressure", "heavy"]]
    assert _find(groups, "heavy pressure in the middle of my chest") is not None
    assert _find(groups, "my chest feels heavy") is not None
    assert _find(groups, "my knee feels heavy") is None


def test_every_group_must_match() -> None:
    assert _find([["stiff"], ["neck"], ["fever"]], "stiff neck and a fever") is not None
    assert _find([["stiff"], ["neck"], ["fever"]], "stiff neck after sleeping badly") is None


def test_multi_word_alternative_matches_consecutive_tokens() -> None:
    groups = [["passed out", "fainted"], ["floor"]]
    assert _find(groups, "she passed out on the floor") is not None
    assert _find(groups, "she passed the salt and went out to the floor") is None


def test_matched_indices_cover_every_word_of_the_tightest_match() -> None:
    hit = _find([["chest"], ["pain"]], "pain in my knee, then chest pain")
    assert hit is not None
    tokens = normalize("pain in my knee, then chest pain").split()
    assert [tokens[i] for i in hit] == ["chest", "pain"]


def test_longest_overlapping_alternative_wins() -> None:
    tokens = normalize("ما قادرش نتنفس").split()
    hit = find(_combo([["ما قادرش", "قادرش"], ["*تنفس"]], "ar"), TokenIndex(tuple(tokens)))
    assert hit == (0, 1, 2)


def test_span_limit() -> None:
    filler = " ".join(["word"] * (MAX_SPAN + 2))
    assert _find([["chest"], ["pain"]], f"chest {filler} pain") is None


def test_one_token_cannot_satisfy_two_groups() -> None:
    assert _find([["breath*"], ["breathing"]], "breathing") is None


def test_arabic_words_accept_proclitics_and_article() -> None:
    groups = [["صدري", "صدر"], ["ألم", "وجع"]]
    assert _find(groups, "عندي وجع كبير فصدري", "ar") is not None
    assert _find(groups, "والألم في الصدر", "ar") is not None
    assert _find(groups, "مصدر الوجع", "ar") is None  # "مصدر" (source) is not "صدر" with a proclitic


def test_negation_particle_glued_to_a_conjunction() -> None:
    assert "ما" in token_forms("وما")
    assert "لا" in token_forms("ولا")
    assert token_forms("وم") == ("وم",)  # other two-letter stems are never split off
    groups = [["طاح"], ["ما بقاش كيجاوب"]]
    assert _find(groups, "بابا طاح وما بقاش كيجاوب", "ar") is not None


def test_arabic_suffix_wildcard_matches_verb_prefixes() -> None:
    groups = [["*نزف"], ["بزاف", "برشا", "بشدة"]]
    assert _find(groups, "مراتي كتنزف بزاف", "ar") is not None
    assert _find(groups, "أختي تنزف برشا", "ar") is not None


def test_arabizi_words_compare_on_the_consonant_skeleton() -> None:
    groups = [["sdri", "sder"], ["wja3", "kayderni"]]
    assert _find(groups, "3ndi wja3 kbir f sadri", "arabizi") is not None
    assert _find(groups, "sedri kaydrni", "arabizi") is not None


def test_arabizi_prefix_wildcard_on_skeleton() -> None:
    assert _find([["ntnfs*"], ["ma9adrach", "mn9drch"]], "ma9adrach netnefes", "arabizi") is not None


def test_parse_rejects_malformed_entries() -> None:
    with pytest.raises(ConfigFileError, match="mapping"):
        parse_combinations(["x"], RiskKind.EMERGENCY, "f.yaml")
    with pytest.raises(ConfigFileError, match="at least two groups"):
        parse_combinations({"en": [[["chest"]]]}, RiskKind.EMERGENCY, "f.yaml")
    with pytest.raises(ConfigFileError, match="list of words"):
        parse_combinations({"en": [[["chest"], "pain"]]}, RiskKind.EMERGENCY, "f.yaml")
    with pytest.raises(ConfigFileError, match="unknown language"):
        parse_combinations({"de": [[["brust"], ["schmerz"]]]}, RiskKind.EMERGENCY, "f.yaml")


def test_parse_skips_absent_languages_and_none() -> None:
    assert parse_combinations(None, RiskKind.EMERGENCY, "f.yaml") == ()
    assert parse_combinations({"en": None}, RiskKind.EMERGENCY, "f.yaml") == ()


def test_token_index_positions_are_memoised() -> None:
    index = TokenIndex(("chest", "pain", "chest"))
    pattern = WordPattern.parse("chest", "en")
    assert index.positions(pattern) == (0, 2)
    assert index.positions(pattern) is index.positions(pattern)
