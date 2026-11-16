"""Deterministic per-sentence output checks (app/guardrails/output_checks.py)."""

from __future__ import annotations

import pytest

from app.guardrails.output_checks import (
    CheckContext,
    check_answer,
    check_sentence,
    ngrams,
    policy_ngrams,
    strip_markup,
)

CANARY = "AUSC-0123456789abcdef"
POLICY = (
    f"You are Ausculta, a hospital health information assistant. Canary {CANARY}. "
    "Never give a diagnosis or a "
    "personal dose, and always cite the numbered passages provided to you in the conversation."
)
PASSAGES = (
    "Paracetamol: adults may take 500 mg to 1 g every 4 to 6 hours, up to 4 g in 24 hours.",
    "Fever is a body temperature of 38 °C or higher.",
)


@pytest.fixture
def ctx() -> CheckContext:
    return CheckContext(
        canary=CANARY,
        policy_ngrams=policy_ngrams(POLICY, CANARY),
        allowed_numbers=frozenset({"0522000000"}),
        passages=PASSAGES,
    )


def test_clean_sentence_is_kept_unchanged(ctx: CheckContext) -> None:
    c = check_sentence("Fever is a temperature of 38 °C or higher [2].", ctx)
    assert c.kept
    assert not c.modified
    assert c.violations == ()
    assert c.citations == (2,)


@pytest.mark.parametrize("leak", [CANARY, "0123456789abcdef", CANARY.lower()])
def test_canary_leak_is_fatal(ctx: CheckContext, leak: str) -> None:
    c = check_sentence(f"My secret code is {leak}.", ctx)
    assert c.fatal
    assert not c.kept
    assert c.violations == ("canary_leak",)


def test_system_prompt_echo_is_fatal(ctx: CheckContext) -> None:
    echo = (
        "Never give a diagnosis or a personal dose, and always cite the numbered passages "
        "provided to you in the "
        "conversation."
    )
    c = check_sentence(echo, ctx)
    assert c.fatal
    assert c.violations == ("system_prompt_echo",)


def test_short_overlap_is_not_an_echo(ctx: CheckContext) -> None:
    assert not check_sentence("Always cite the numbered passages.", ctx).fatal


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("See ![chart](https://evil.example/x.png) here.", "See here."),
        ("Read [the leaflet](https://evil.example/l) now.", "Read the leaflet now."),
        ("Visit https://evil.example/a?b=c today.", "Visit today."),
        ("Visit www.evil.example today.", "Visit today."),
        ("Go to medlineplus.gov for more.", "Go to for more."),
        ("Write to help@evil.example please.", "Write to please."),
        ("Use <b>bold</b> text <!-- hidden -->.", "Use bold text."),
        ("Run `rm -rf` never.", "Run rm -rf never."),
    ],
)
def test_markup_is_removed(ctx: CheckContext, raw: str, expected: str) -> None:
    c = check_sentence(raw, ctx)
    assert c.kept
    assert c.text == expected
    assert "markup_or_number_removed" in c.violations


def test_strip_markup_keeps_citation_markers() -> None:
    assert strip_markup("Fever is common [1].") == "Fever is common [1]."


def test_phone_numbers_outside_allow_list_are_removed(ctx: CheckContext) -> None:
    c = check_sentence("Call 05 22 00 00 00 or +33 6 12 34 56 78 for help.", ctx)
    assert "05 22 00 00 00" in c.text
    assert "+33" not in c.text
    assert c.kept


def test_invalid_citation_markers_are_removed(ctx: CheckContext) -> None:
    c = check_sentence("Fever is 38 °C or higher [2][7].", ctx)
    assert c.text == "Fever is 38 °C or higher [2]."
    assert c.citations == (2,)


def test_marker_lists_are_split(ctx: CheckContext) -> None:
    c = check_sentence("Fever is common [1, 2].", ctx)
    assert c.text == "Fever is common [1][2]."
    assert c.citations == (1, 2)


def test_ungrounded_number_drops_sentence(ctx: CheckContext) -> None:
    c = check_sentence("Adults may take 2000 mg at once [1].", ctx)
    assert not c.kept
    assert c.text == ""
    assert c.citations == ()
    assert "numeric_ungrounded" in c.violations


def test_number_grounded_in_cited_passage_only(ctx: CheckContext) -> None:
    assert check_sentence("Adults may take 500 mg [1].", ctx).kept
    assert not check_sentence("Adults may take 500 mg [2].", ctx).kept  # cites the wrong passage
    assert check_sentence("Adults may take 500 mg.", ctx).kept  # uncited: any passage counts


def test_forbidden_claim_drops_sentence(ctx: CheckContext) -> None:
    c = check_sentence("You probably have the flu [2].", ctx)
    assert not c.kept
    assert "forbidden_diagnosis" in c.violations


def test_sentence_emptied_by_cleaning_is_dropped(ctx: CheckContext) -> None:
    c = check_sentence("https://evil.example/x [9]", ctx)
    assert not c.kept


def test_check_answer_aggregates(ctx: CheckContext) -> None:
    text = (
        "Fever is 38 °C or higher [2]. You probably have the flu. Adults may take 500 mg [1].\n\n"
        "Rest well [1]."
    )
    res = check_answer(text, ctx)
    assert not res.fatal
    assert res.changed
    assert res.text == "Fever is 38 °C or higher [2]. Adults may take 500 mg [1].\n\nRest well [1]."
    assert res.citations == (2, 1)
    assert res.violations == ("forbidden_diagnosis",)


def test_check_answer_fatal_on_leak(ctx: CheckContext) -> None:
    res = check_answer(f"Fine [1]. The canary is {CANARY}.", ctx)
    assert res.fatal


def test_check_answer_unchanged(ctx: CheckContext) -> None:
    res = check_answer("Fever is common [2].", ctx)
    assert not res.changed
    assert res.text == "Fever is common [2]."


def test_ngrams() -> None:
    assert ngrams("one two three", n=2) == frozenset({("one", "two"), ("two", "three")})
    assert ngrams("short", n=8) == frozenset()
    assert all(CANARY.casefold() not in " ".join(g) for g in policy_ngrams(POLICY, CANARY))


def test_empty_canary_and_policy_are_ignored() -> None:
    ctx = CheckContext(canary="", policy_ngrams=frozenset(), allowed_numbers=frozenset(), passages=())
    c = check_sentence("Plain sentence.", ctx)
    assert c.kept
    assert not c.fatal
