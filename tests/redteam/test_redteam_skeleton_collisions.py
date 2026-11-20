"""P5-D9 (fixed): Arabizi skeleton matching read French 'quel ... code' as 'kla' (swallowed) + 'acide' (acid),
so ordinary front-desk questions got the emergency template. The colliding French words are no longer compared
on the skeleton; real Arabizi poisoning messages must still be caught."""

from __future__ import annotations

import pytest

from app.pipeline.factory import load_engine_config
from core.config import REPO_ROOT
from core.schemas.chat import RiskKind

LEXICON = load_engine_config(REPO_ROOT / "config" / "hospital" / "demo.yaml").lexicon


def _kinds(message: str) -> set[RiskKind]:
    return {s.kind for s in LEXICON.assess(message).signals}


@pytest.mark.parametrize(
    "message",
    [
        "Quel est le code wifi de l'hôpital ?",
        "Quel est le code postal de l'hôpital ?",
        "quel code ?",
        "Quelle est la porte, et quels codes faut-il ?",
    ],
)
def test_french_code_questions_are_not_emergencies(message: str) -> None:
    assert RiskKind.EMERGENCY not in _kinds(message)


@pytest.mark.parametrize(
    "message",
    ["wldi kla acide", "bnti klat l acide", "kla l'acide", "klat javel", "weldi chreb javel"],
)
def test_arabizi_poisoning_is_still_an_emergency(message: str) -> None:
    assert RiskKind.EMERGENCY in _kinds(message)
