"""Hospital profile loading, public view and deterministic front-desk answers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from app.hospital.frontdesk import answer_front_desk, hospital_keywords, render_department
from app.hospital.profile import ProfileState, load_profile
from app.hospital.public import public_hospital
from core.config import REPO_ROOT

DEMO = REPO_ROOT / "config" / "hospital" / "demo.yaml"


@pytest.fixture(scope="module")
def profile():
    state = load_profile(DEMO)
    assert state.loaded
    assert state.error is None
    return state.profile


# ---- profile -------------------------------------------------------------------------------------
def test_demo_profile_validity_window(profile) -> None:
    state = ProfileState(profile=profile)
    assert state.active(date(2026, 12, 1)) is profile
    assert state.active(date(2030, 1, 1)) is None  # expired -> receptionist mode off
    assert state.active(date(2020, 1, 1)) is None
    assert ProfileState(profile=None).active(date(2026, 12, 1)) is None
    assert ProfileState(profile=None).loaded is False


def test_missing_and_invalid_profiles_disable_reception(tmp_path: Path) -> None:
    missing = load_profile(tmp_path / "nope.yaml")
    assert missing.profile is None
    assert "cannot read" in (missing.error or "")
    raw = yaml.safe_load(DEMO.read_text(encoding="utf-8"))
    raw["emergency"]["number"] = "call me maybe"
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    invalid = load_profile(bad)
    assert invalid.profile is None
    assert "invalid hospital profile" in (invalid.error or "")
    broken = tmp_path / "broken.yaml"
    broken.write_text("id: [unclosed", encoding="utf-8")
    assert load_profile(broken).profile is None


def test_profile_numbers_are_allow_listed(profile) -> None:
    allowed = profile.allowed_numbers()
    assert "15" in allowed
    assert "3114" in allowed


# ---- public view ---------------------------------------------------------------------------------
@pytest.mark.parametrize("locale", ["en", "fr", "ar"])
def test_public_hospital_is_resolved_to_one_locale(profile, locale) -> None:
    pub = public_hospital(profile, locale)
    assert set(pub) == {
        "id",
        "name",
        "is_demo",
        "address",
        "main_phone",
        "emergency",
        "crisis_lines",
        "handoff",
        "visiting_hours",
        "departments",
    }
    assert pub["name"] == profile.name.get(locale)
    assert pub["emergency"]["number"] == profile.emergency.number
    assert all(isinstance(d["name"], str) for d in pub["departments"])
    assert {d["id"] for d in pub["departments"]} == {d.id for d in profile.departments}


def test_public_hospital_handles_missing_optional_fields(profile) -> None:
    bare = profile.model_copy(
        update={
            "visiting_hours": None,
            "departments": tuple(
                d.model_copy(update={"location": None, "hours": None}) for d in profile.departments
            ),
        }
    )
    pub = public_hospital(bare, "en")
    assert pub["visiting_hours"] == ""
    assert pub["departments"][0]["location"] == ""


# ---- front desk ----------------------------------------------------------------------------------
def test_department_question_renders_profile_fields(profile, engine_config) -> None:
    ans = answer_front_desk("Where is the cardiology department?", profile, engine_config.texts, "en")
    assert ans is not None
    assert ans.matched[0] == "department:cardiology"
    cardio = next(d for d in profile.departments if d.id == "cardiology")
    assert cardio.name.en in ans.text
    assert "Appointment requests: yes" in ans.text


def test_misspelled_department_is_matched_fuzzily(profile, engine_config) -> None:
    ans = answer_front_desk("horaires de la cardiolgie ?", profile, engine_config.texts, "fr")
    assert ans is not None
    assert "department:cardiology" in ans.matched


def test_faq_and_topic_answers(profile, engine_config) -> None:
    texts = engine_config.texts
    parking = answer_front_desk("Is there a car park?", profile, texts, "en")
    assert parking is not None
    assert parking.matched[0] == "faq:parking"
    visits = answer_front_desk("What are the visiting hours?", profile, texts, "en")
    assert visits is not None
    assert "topic:visiting_hours" in visits.matched
    assert profile.visiting_hours.en in visits.text
    contacts = answer_front_desk("What is the phone number of the switchboard?", profile, texts, "en")
    assert contacts is not None
    assert profile.main_phone.number in contacts.text
    emergency = answer_front_desk("what is the emergency number", profile, texts, "en")
    assert emergency is not None
    assert profile.emergency.number in emergency.text


def test_arabic_front_desk_question(profile, engine_config) -> None:
    ans = answer_front_desk("ما هي أوقات الزيارة؟", profile, engine_config.texts, "ar")
    assert ans is not None
    assert profile.visiting_hours.get("ar") in ans.text


def test_at_most_two_sections_and_no_match(profile, engine_config) -> None:
    texts = engine_config.texts
    many = answer_front_desk("cardiology pediatrics dermatology radiology parking", profile, texts, "en")
    assert many is not None
    assert len(many.matched) == 2
    assert answer_front_desk("qwerty zxcv", profile, texts, "en") is None


def test_topics_absent_from_profile_are_skipped(profile, engine_config) -> None:
    bare = profile.model_copy(update={"insurance": None, "faqs": ()})
    assert answer_front_desk("insurance", bare, engine_config.texts, "en") is None


def test_render_department_without_optional_fields(profile, engine_config) -> None:
    lab = next(d for d in profile.departments if not d.accepts_appointments)
    bare = lab.model_copy(update={"description": None, "location": None, "hours": None, "phone": None})
    text = render_department(bare, engine_config.texts, "en")
    assert text.startswith(f"**{lab.name.en}**")
    assert "not needed or not available" in text


def test_hospital_keywords(profile) -> None:
    kws = hospital_keywords(profile)
    assert "cardiology" in kws
    assert "heart" not in kws  # medical words stay out of the front-desk heuristic
    assert hospital_keywords(None) == ()
