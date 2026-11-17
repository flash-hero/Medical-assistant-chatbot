"""Deterministic per-sentence output checks (app/guardrails/output_checks.py)."""

from __future__ import annotations

import re

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


# ---- review C4 / S4: short emergency numbers, Unicode and single-spaced digits ------------------------------
@pytest.fixture
def ctx_hospital() -> CheckContext:
    return CheckContext(
        canary=CANARY,
        policy_ngrams=frozenset(),
        allowed_numbers=frozenset({"15", "112", "3114", "0522000000"}),
        passages=PASSAGES,
    )


@pytest.mark.parametrize(
    ("raw", "gone"),
    [
        ("If this is an emergency, call 911 now.", "911"),
        ("Call 999.", "999"),
        ("Appelez le 911.", "911"),
        ("Composez le 17 en cas de danger.", "17"),
        ("اتصل بالرقم 911.", "911"),
        ("اتصل بالرقم ٩١١.", "٩١١"),
        ("Call ９１１ now.", "９１１"),
        ("Call 9 1 1 now.", "9 1 1"),
        ("Dial 1-1-2-2 for help.", "1-1-2-2"),
        ("The emergency number is 911.", "911"),
        ("Le numéro d'urgence est le 190.", "190"),
        ("رقم الطوارئ هو 150.", "150"),
        ("For poison control, call 1-800-222-1222.", "1-800-222-1222"),
    ],
)
def test_short_numbers_after_call_verbs_or_near_emergency_are_removed(
    ctx_hospital: CheckContext, raw: str, gone: str
) -> None:
    c = check_sentence(raw, ctx_hospital)
    assert gone not in c.text
    assert not re.search(r"\d", re.sub(r"\[\d+\]", "", c.text)), c.text  # no digit fragment ("1-") left
    assert "markup_or_number_removed" in c.violations


@pytest.mark.parametrize(
    "raw",
    [
        "In an emergency, call 15 or 112.",
        "Appelez le 15 ou le 112 en cas d'urgence.",
        "اتصل بالرقم ١٥ في حالة الطوارئ.",
        "Call 15 now.",
        "Call 1 5 now.",
        "For suicidal thoughts, call 3114.",
        "Call the hospital on 05 22 00 00 00.",
    ],
)
def test_allowed_numbers_are_kept(ctx_hospital: CheckContext, raw: str) -> None:
    c = check_sentence(raw, ctx_hospital)
    assert c.text == raw
    assert "markup_or_number_removed" not in c.violations


@pytest.mark.parametrize(
    "raw",
    [
        "Go to the emergency department if the fever is above 39 °C [2].",
        "Call your doctor if the fever lasts more than 3 days [2].",
        "Fever is 38 °C or higher [2].",
        "The emergency department is open 24 hours [1].",
    ],
)
def test_clinical_numbers_near_emergency_words_are_kept(ctx_hospital: CheckContext, raw: str) -> None:
    c = check_sentence(raw, ctx_hospital)
    assert "markup_or_number_removed" not in c.violations


# ---- review S11 / C16: bare domains, defanged domains ---------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("See evil.xyz for more.", "See for more."),
        ("Visit bit.ly/abc today.", "Visit today."),
        ("Go to site.ru now.", "Go to now."),
        ("Read more at news.example.co.uk/page today.", "Read more at today."),
        ("Read example[.]com today.", "Read today."),
        ("Read example(.)com today.", "Read today."),
        ("Visit evil dot com today.", "Visit today."),
        ("Visit evil [dot] com today.", "Visit today."),
        ("Visit EVIL.COM today.", "Visit today."),
        ("Visit evil.health today.", "Visit today."),
    ],
)
def test_bare_and_defanged_domains_are_removed(raw: str, expected: str) -> None:
    assert re.sub(r"\s{2,}", " ", strip_markup(raw)).replace(" .", ".") == expected


@pytest.mark.parametrize(
    "raw",
    [
        "Take 2.5 mg, e.g. with food [1].",
        "Rest, i.e. avoid sport [1].",
        "The dose is 0.5 g [1].",
        "U.S. guidance differs [1].",
        "It is a fever.Rest helps [1].",
        "Dr. Smith works at St. John's.",
    ],
)
def test_decimals_and_abbreviations_are_not_domains(raw: str) -> None:
    assert strip_markup(raw) == raw
