"""Fixed texts: safety templates (config/safety/templates.yaml) and responses, labels, form and error messages
(config/templates/responses.yaml). Placeholders are filled ONLY from the verified hospital profile.

Without a profile (review C11):
  - {emergency_number} and {crisis_number} become `call_fallback` (responses.yaml), a phrase written to read
    correctly after each template's call verb ("call ...", "appelez le ...", "اتصل بالرقم ...");
  - a sentence that needs a profile-only contact ({handoff_*}, {main_*}) is left out, so no text points at a
    staff line or switchboard that does not exist;
  - the safety follow-up becomes the neutral `safety_followup_no_contacts` (no "contacts shown above")."""

from __future__ import annotations

import re
import string
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.config_files import CONFIG_ROOT, LOCALES, ConfigFileError, load_yaml, require_locales
from core.schemas.events import Contact
from core.schemas.hospital import HospitalProfile, PhoneContact

SAFETY_TEMPLATES_PATH = CONFIG_ROOT / "safety" / "templates.yaml"
RESPONSES_PATH = CONFIG_ROOT / "templates" / "responses.yaml"
PLACEHOLDERS = frozenset(
    {
        "emergency_number",
        "crisis_number",
        "handoff_label",
        "handoff_number",
        "main_label",
        "main_number",
        "turns_left",
        "request_id",
    }
)
SAFETY_KINDS = ("emergency", "self_harm", "harm_to_others", "abuse_disclosure")
PROFILE_ONLY = frozenset({"handoff_label", "handoff_number", "main_label", "main_number"})
FOLLOWUP_NO_CONTACTS = "safety_followup_no_contacts"
_SENTENCE_END = re.compile(r"(?<=[.!?؟])\s+")
L10nText = Mapping[str, str]


@dataclass(frozen=True)
class SafetyTemplate:
    kind: str
    template_id: str
    contacts: tuple[str, ...]
    title: L10nText
    message: L10nText
    followup: L10nText


@dataclass(frozen=True)
class Texts:
    safety: Mapping[str, SafetyTemplate]
    fallback_number: L10nText
    call_fallback: L10nText
    approval_status: str
    responses: Mapping[str, L10nText]
    notices: Mapping[str, L10nText]
    frontdesk: Mapping[str, L10nText]
    form: Mapping[str, Any]
    errors: Mapping[str, L10nText]

    def response(self, key: str, locale: str, profile: HospitalProfile | None, **extra: object) -> str:
        return render(self.responses[key], locale, self.values(profile, locale, **extra))

    def notice(self, key: str, locale: str, profile: HospitalProfile | None, **extra: object) -> str:
        return render(self.notices[key], locale, self.values(profile, locale, **extra))

    def error(self, code: str, locale: str) -> str:
        table = self.errors.get(code) or self.errors["internal_error"]
        return table.get(locale) or table["en"]

    def label(self, key: str, locale: str) -> str:
        return self.frontdesk[key].get(locale) or self.frontdesk[key]["en"]

    def render_safety(self, template: L10nText, locale: str, profile: HospitalProfile | None) -> str:
        return render(template, locale, self.values(profile, locale))

    def followup(self, kind: str, locale: str, profile: HospitalProfile | None) -> str:
        """Text of the answer that closes a safety turn. Without a profile no contacts are shown, so the
        template's "contacts above" wording is replaced by a neutral one."""
        if profile is None:
            return self.response(FOLLOWUP_NO_CONTACTS, locale, None)
        return self.render_safety(self.safety[kind].followup, locale, profile)

    def values(self, profile: HospitalProfile | None, locale: str, **extra: object) -> dict[str, str]:
        """Placeholder values. Profile-only keys are absent without a profile (their sentences are dropped)."""
        fallback = self.call_fallback.get(locale) or self.call_fallback["en"]
        vals = dict.fromkeys(("emergency_number", "crisis_number"), fallback)
        if profile is not None:
            vals["emergency_number"] = profile.emergency.number
            vals["crisis_number"] = (
                profile.crisis_lines[0].number if profile.crisis_lines else profile.emergency.number
            )
            vals["handoff_number"] = profile.handoff.number
            vals["handoff_label"] = profile.handoff.label.get(locale)
            vals["main_number"] = profile.main_phone.number
            vals["main_label"] = profile.main_phone.label.get(locale)
        vals.update({k: str(v) for k, v in extra.items()})
        return vals


def render(template: L10nText, locale: str, values: Mapping[str, str]) -> str:
    """Fill the placeholders; sentences that need a missing profile-only value are left out."""
    text = template.get(locale) or template["en"]
    missing = PROFILE_ONLY - set(values)
    if missing:
        kept = [s for s in _SENTENCE_END.split(text) if not _fields(s) & missing]
        text = " ".join(kept)
    return text.format_map(_Defaults(values))


def _fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


class _Defaults(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def contacts_for(
    selectors: tuple[str, ...], profile: HospitalProfile | None, locale: str
) -> tuple[Contact, ...]:
    """Resolve template contact selectors against the profile (no profile -> no contacts)."""
    if profile is None:
        return ()
    found: list[PhoneContact] = []
    for sel in selectors:
        found.extend(_select(sel, profile))
    out: list[Contact] = []
    seen: set[str] = set()
    for c in found:
        if c.number in seen:
            continue
        seen.add(c.number)
        out.append(
            Contact(label=c.label.get(locale), number=c.number, hours=c.hours.get(locale) if c.hours else "")
        )
    return tuple(out)


def _select(selector: str, profile: HospitalProfile) -> list[PhoneContact]:
    if selector == "emergency":
        return [profile.emergency]
    if selector == "crisis_lines":
        return list(profile.crisis_lines)
    if selector.startswith("crisis_line:"):
        digits = selector.split(":", 1)[1]
        return [c for c in profile.crisis_lines if "".join(ch for ch in c.number if ch.isdigit()) == digits]
    if selector == "handoff":
        return [profile.handoff]
    if selector == "poison_control":
        return [profile.poison_control] if profile.poison_control else []
    return []


# ---- loading ------------------------------------------------------------------------------------
def _check_placeholders(table: L10nText, where: str) -> L10nText:
    for loc, text in table.items():
        unknown = _fields(text) - PLACEHOLDERS
        if unknown:
            raise ConfigFileError(f"{where}.{loc}: unknown placeholders {sorted(unknown)}")
    return MappingProxyType(dict(table))


def _l10n_table(section: Any, where: str) -> Mapping[str, L10nText]:
    if not isinstance(section, Mapping):
        raise ConfigFileError(f"{where} must be a mapping")
    return MappingProxyType(
        {
            str(k): _check_placeholders(require_locales(v, f"{where}.{k}"), f"{where}.{k}")
            for k, v in section.items()
        }
    )


def _safety(raw: Mapping[str, Any]) -> Mapping[str, SafetyTemplate]:
    section = raw.get("safety")
    if not isinstance(section, Mapping) or set(section) != set(SAFETY_KINDS):
        raise ConfigFileError(f"safety templates must define exactly {SAFETY_KINDS}")
    out: dict[str, SafetyTemplate] = {}
    for kind, t in section.items():
        if not isinstance(t, Mapping) or not str(t.get("template_id", "")):
            raise ConfigFileError(f"safety.{kind}: template_id is required")
        contacts = tuple(str(c) for c in t.get("contacts") or ())
        out[kind] = SafetyTemplate(
            kind=kind,
            template_id=str(t["template_id"]),
            contacts=contacts,
            title=_check_placeholders(require_locales(t.get("title"), f"{kind}.title"), f"{kind}.title"),
            message=_check_placeholders(
                require_locales(t.get("message"), f"{kind}.message"), f"{kind}.message"
            ),
            followup=_check_placeholders(
                require_locales(t.get("followup"), f"{kind}.followup"), f"{kind}.followup"
            ),
        )
    return MappingProxyType(out)


def load_texts(safety_path: Path = SAFETY_TEMPLATES_PATH, responses_path: Path = RESPONSES_PATH) -> Texts:
    safety_raw = load_yaml(safety_path)
    resp_raw = load_yaml(responses_path)
    approval = safety_raw.get("approval") or {}
    form = resp_raw.get("form")
    if not isinstance(form, Mapping) or not isinstance(form.get("fields"), Mapping):
        raise ConfigFileError("responses.form.fields is required")
    for name, labels in form["fields"].items():
        require_locales(labels, f"form.fields.{name}")
    responses = _l10n_table(resp_raw.get("responses"), "responses")
    if FOLLOWUP_NO_CONTACTS not in responses:
        raise ConfigFileError(f"responses.{FOLLOWUP_NO_CONTACTS} is required")
    return Texts(
        safety=_safety(safety_raw),
        fallback_number=require_locales(safety_raw.get("fallback_number"), "fallback_number"),
        call_fallback=require_locales(resp_raw.get("call_fallback"), "call_fallback"),
        approval_status=str(approval.get("status", "draft")) if isinstance(approval, Mapping) else "draft",
        responses=responses,
        notices=_l10n_table(resp_raw.get("notices"), "notices"),
        frontdesk=_l10n_table(resp_raw.get("frontdesk"), "frontdesk"),
        form=MappingProxyType(dict(form)),
        errors=_l10n_table(resp_raw.get("errors"), "errors"),
    )


def form_label(texts: Texts, path: tuple[str, ...], locale: str) -> str:
    node: Any = texts.form
    for key in path:
        node = node[key]
    return str(node.get(locale) or node["en"])


__all__ = ["LOCALES", "SafetyTemplate", "Texts", "contacts_for", "form_label", "load_texts", "render"]
