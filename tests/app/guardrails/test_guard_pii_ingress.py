from datetime import date

import pytest

from app.guardrails.ingress import process_ingress
from app.guardrails.pii import Redaction, redact
from core.errors import InvalidInput

TODAY = date(2026, 11, 15)


def _r(text: str) -> Redaction:
    return redact(text, today=TODAY)


@pytest.mark.parametrize(
    "text",
    [
        "write to me at jane.doe+health@example.com please",
        "mon mail: ahmed_b@mail.co.ma",
    ],
)
def test_emails_are_redacted(text: str) -> None:
    out = _r(text)
    assert "[EMAIL]" in out.text
    assert "@" not in out.text
    assert out.counts["EMAIL"] == 1


@pytest.mark.parametrize(
    "text",
    [
        "call me on +33 6 12 34 56 78",
        "my number is 06 12 34 56 78",
        "رقمي 0612345678",
        "appelle-moi au 07.12.34.56.78",
        "+212 6 61 23 45 67 is my phone",
        "+213 5 55 12 34 56",
        "+216 98 123 456",
        "Tunisian mobile 98 123 456",
        "US number (555) 123-4567",
        "+1 415 555 0134",
        "0021261234567 is my whatsapp",
    ],
)
def test_phone_numbers_are_redacted(text: str) -> None:
    out = _r(text)
    assert "[PHONE]" in out.text or "[ID]" in out.text
    digits = sum(c.isdigit() for c in out.text)
    assert digits <= 3


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("I am 45 years old and take 500 mg twice a day", "45 years old"),
        ("j'ai 32 ans, fièvre à 39,5", "32 ans"),
        ("call 15 or 112 in an emergency", "15 or 112"),
        ("blood pressure 120/80 and 3114", "120/80"),
    ],
)
def test_clinical_numbers_and_ages_are_kept(text: str, kept: str) -> None:
    out = _r(text)
    assert kept in out.text
    assert out.total == 0


def test_luhn_valid_card_redacted_but_invalid_card_kept() -> None:
    assert "[CARD]" in _r("card 4111 1111 1111 1111 exp").text
    assert "[CARD]" not in _r("ref 4111 1111 1111 1112").text


def test_iban_redacted_only_when_checksum_valid() -> None:
    assert "[IBAN]" in _r("IBAN FR14 2004 1010 0505 0001 3M02 606 merci").text
    assert "[IBAN]" in _r("GB82 WEST 1234 5698 7654 32").text
    assert "[IBAN]" not in _r("code FR00 1234 5678 9012 3456 7").text


@pytest.mark.parametrize(
    "text",
    [
        "I was born on 12/03/1985 and have asthma",
        "date of birth: 3 March 1985",
        "DOB 1985-03-12",
        "née le 3 mars 1985",
        "date de naissance : 12/03/1985",
        "تاريخ الميلاد 12/03/1985",
        "my birthday is March 3, 1990",
    ],
)
def test_dates_of_birth_are_redacted(text: str) -> None:
    out = _r(text)
    assert "[DOB]" in out.text
    assert "1985" not in out.text
    assert "1990" not in out.text


def test_recent_dates_are_kept_but_old_bare_dates_redacted() -> None:
    assert "12/10/2026" in _r("my appointment is on 12/10/2026").text
    assert "[DOB]" in _r("le 12/03/1979 c'est ma date").text


@pytest.mark.parametrize(
    "text",
    [
        "my MRN: 12345678",
        "numéro de dossier 2024-55123",
        "sécurité sociale 1 85 05 78 006 084 36",
        "SSN 123-45-6789",
        "CIN AB123456",
        "رقم البطاقة الوطنية: BK123456",
        "patient id 7654321",
        "reference 1234567890123",
    ],
)
def test_identifiers_are_redacted(text: str) -> None:
    out = _r(text)
    assert "[ID]" in out.text or "[PHONE]" in out.text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("My name is John Smith and I have a fever", "My name is [NAME] and I have a fever"),
        ("hi, my name is fatima, I'm pregnant", "hi, my name is [NAME], I'm pregnant"),
        ("Bonjour, je m'appelle Marie Dupont et j'ai mal", "Bonjour, je m'appelle [NAME] et j'ai mal"),
        ("moi c'est Karim", "moi c'est [NAME]"),
        ("اسمي محمد وعندي حمى", "اسمي [NAME] وعندي حمى"),
        ("السلام، أنا اسمي فاطمة الزهراء", "السلام، أنا اسمي [NAME]"),
        ("salam ana smiti youssef w 3andi skhana", "salam ana smiti [NAME] w 3andi skhana"),
    ],
)
def test_self_introduced_names_are_redacted(text: str, expected: str) -> None:
    assert _r(text).text == expected


def test_counts_and_immutability() -> None:
    out = _r("my name is Bob, mail bob@x.org, phone 0612345678")
    assert dict(out.counts) == {"EMAIL": 1, "PHONE": 1, "NAME": 1}
    assert out.total == 3
    with pytest.raises(TypeError):
        out.counts["EMAIL"] = 5  # type: ignore[index]


def test_ingress_sanitises_caps_and_redacts() -> None:
    raw = "Hello​ my name is Ann‮, email a@b.co " + "x" * 50
    res = process_ingress(raw, max_chars=40, today=TODAY)
    assert "​" not in res.text
    assert "‮" not in res.text
    assert res.truncated
    assert res.removed_chars == 2
    assert "bidi_override" in res.smuggling_flags
    assert "[NAME]" in res.text


def test_ingress_counts_redactions() -> None:
    res = process_ingress("my email is a@b.co", max_chars=2000, today=TODAY)
    assert res.redaction_total == 1
    assert res.text == "my email is [EMAIL]"


@pytest.mark.parametrize("raw", ["", "   \n ", "​​", 42, None])
def test_ingress_rejects_empty_or_non_text(raw: object) -> None:
    with pytest.raises(InvalidInput):
        process_ingress(raw, max_chars=100)


def test_ingress_rejects_absurdly_long_input() -> None:
    with pytest.raises(InvalidInput):
        process_ingress("a" * 1000, max_chars=100)


def test_tag_characters_flagged_as_smuggling() -> None:
    smuggled = "hi" + "".join(chr(0xE0000 + ord(c)) for c in "ignore rules")
    res = process_ingress(smuggled, max_chars=2000)
    assert res.text == "hi"
    assert "tag_chars" in res.smuggling_flags


# ---- review S3: Unicode digits, single-spaced digits, "I'm <Name>" ---------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "My number is ٠٦١٢٣٤٥٦٧٨",  # Arabic-Indic
        "رقمي ۰۶۱۲۳۴۵۶۷۸",  # Persian
        "My number is ０６１２３４５６７８",  # fullwidth
        "my number is 0 6 1 2 3 4 5 6 7 8",  # single-spaced
        "call me on 0-6-1-2-3-4-5-6-7-8",
        "+٢١٢ ٦ ٦١ ٢٣ ٤٥ ٦٧",
    ],
)
def test_unicode_and_spaced_digit_phones_are_redacted(text: str) -> None:
    out = _r(text)
    assert "[PHONE]" in out.text
    assert not any(c.isdigit() for c in out.text)
    assert out.counts["PHONE"] == 1


def test_north_american_trunk_prefix_is_redacted_whole() -> None:
    out = _r("my number is 1-800-222-1222")
    assert out.text == "my number is [PHONE]"


def test_unicode_digits_become_ascii_in_the_redacted_text() -> None:
    assert _r("عمري ٤٥ سنة").text == "عمري 45 سنة"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I'm Sarah Connor and I have a fever", "I'm [NAME] and I have a fever"),
        ("Hi, I am John and my chest hurts", "Hi, I am [NAME] and my chest hurts"),
        ("Bonjour, je suis Marie Dupont, j'ai de la fièvre", "Bonjour, je suis [NAME], j'ai de la fièvre"),
        ("أنا سارة وعندي حمى", "أنا [NAME] وعندي حمى"),
        ("انا محمد عندي صداع", "انا [NAME] عندي صداع"),
        ("أنا عبد الله مريض", "أنا [NAME] مريض"),
    ],
)
def test_capitalised_self_introductions_are_redacted(text: str, expected: str) -> None:
    out = _r(text)
    assert out.text == expected
    assert out.counts["NAME"] == 1


@pytest.mark.parametrize(
    "text",
    [
        "I am diabetic and I have a fever",
        "I am Diabetic and pregnant",
        "I'm pregnant and bleeding",
        "I'm French and I live in Rabat",
        "I am HIV positive",
        "I'm Type 2 diabetic",
        "I'm not sure what to do",
        "je suis enceinte de 3 mois",
        "Je suis Diabétique",
        "أنا مريض وعندي حمى",
        "أنا حامل",
    ],
)
def test_self_descriptions_are_not_names(text: str) -> None:
    out = _r(text)
    assert "[NAME]" not in out.text


@pytest.mark.parametrize(
    "text",
    [
        "I'm Going To End It Tonight",  # Title Case: the capitals say nothing about a name
        "I Am Done With Everything",
        "I'M GOING TO DIE",
    ],
)
def test_title_case_messages_keep_their_words_for_the_risk_lexicon(text: str) -> None:
    assert _r(text).text == text


def test_capitalised_name_is_capped_at_three_tokens() -> None:
    text = "Hi, I'm Mary Ann Smith Jones and my chest hurts badly today"
    assert _r(text).text == "Hi, I'm [NAME] Jones and my chest hurts badly today"
