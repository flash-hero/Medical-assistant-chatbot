"""Open P5 defects with a repro, as strict xfails: each turns into a failure (XPASS) once fixed, so the
marker is removed together with the fix. Not fixed here: lexicon changes need the guardrails owner and a
clinician. (P5-D8, the Redis-outage emergency path, is in tests/chaos/test_chaos_redis.py.)"""

from __future__ import annotations

import pytest

from app.pipeline.factory import load_engine_config
from core.config import REPO_ROOT
from core.schemas.chat import RiskKind

LEXICON = load_engine_config(REPO_ROOT / "config" / "hospital" / "demo.yaml").lexicon


@pytest.mark.xfail(
    strict=True,
    reason="P5-D9: the Arabizi co-occurrence skeletons read French 'quel ... code' as 'kla' (swallowed) + "
    "'acide' (acid), both skeletons 'kl' + 'cd': ordinary front-desk questions get the emergency template",
)
@pytest.mark.parametrize(
    "message",
    ["Quel est le code wifi de l'hôpital ?", "Quel est le code postal de l'hôpital ?", "quel code ?"],
)
def test_french_code_questions_are_not_emergencies(message: str) -> None:
    kinds = {s.kind for s in LEXICON.assess(message).signals}
    assert RiskKind.EMERGENCY not in kinds
