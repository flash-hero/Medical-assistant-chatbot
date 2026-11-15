from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from core.models import ModelRole, all_model_ids, model_for
from core.schemas.chat import Intent
from core.schemas.document import Document, Section
from core.schemas.events import CHAT_EVENT_ADAPTER, AnswerEvent, DoneEvent, to_sse
from core.schemas.source import ReuseMode, SourceRecord


def _source(**over):
    base = {
        "id": "demo_src",
        "name": "Demo",
        "publisher": "Gov",
        "homepage": "https://example.gov/",
        "status": "active",
        "wave": 1,
        "trust_tier": 1,
        "reuse_mode": "paraphrase_ok",
        "languages": ["en"],
        "content_types": ["condition"],
        "license": {
            "id": "public-domain-us-gov",
            "name": "Public domain",
            "evidence_url": "https://example.gov/terms",
            "commercial_use": "yes",
            "verified_on": "2026-11-15",
            "verified_by": "data-agent",
        },
    }
    base.update(over)
    return base


def test_active_source_requires_verified_licence():
    SourceRecord.model_validate(_source())
    bad = _source()
    bad["license"] = {**bad["license"], "verified_on": None}
    with pytest.raises(ValidationError, match="verified_on"):
        SourceRecord.model_validate(bad)


def test_active_source_rejects_noncommercial_and_link_only():
    nc = _source()
    nc["license"] = {**nc["license"], "commercial_use": "no"}
    with pytest.raises(ValidationError, match="commercial_use"):
        SourceRecord.model_validate(nc)
    with pytest.raises(ValidationError, match="link_only"):
        SourceRecord.model_validate(_source(reuse_mode="link_only"))


def test_document_checksum_is_stable_and_models_are_frozen():
    doc = Document(
        doc_id="demo_src:asthma",
        source_id="demo_src",
        url="https://example.gov/asthma",
        title="Asthma",
        language="en",
        content_type="condition",
        trust_tier=1,
        reuse_mode=ReuseMode.PARAPHRASE_OK,
        license_id="public-domain-us-gov",
        attribution="Source: Demo",
        reviewed_on=date(2025, 1, 1),
        retrieved_at=datetime(2026, 11, 15, tzinfo=UTC),
        sections=(Section(section_id="s1", heading_path=("Asthma",), text="Asthma affects airways."),),
    ).with_checksum()
    assert len(doc.checksum) == 64
    assert doc.with_checksum().checksum == doc.checksum
    with pytest.raises(ValidationError):
        doc.title = "x"  # type: ignore[misc]


def test_sse_roundtrip_through_discriminated_union():
    ev = AnswerEvent(text="Hi [1]", intent=Intent.MEDICAL_INFO, mode="streamed", verified=True)
    wire = to_sse(ev)
    assert wire.startswith("event: answer\ndata: ") and wire.endswith("\n\n")
    parsed = CHAT_EVENT_ADAPTER.validate_json(wire.split("data: ", 1)[1].strip())
    assert parsed == ev
    assert isinstance(CHAT_EVENT_ADAPTER.validate_python({"type": "done", "turn_id": "t", "turns_left": 3}), DoneEvent)


def test_model_ids_are_pinned_and_paid_only_models_not_used_on_free_tier():
    ids = all_model_ids("free")
    assert not any(i.endswith("-latest") or "preview" in i or i.startswith("gemini-2.5") for i in ids)
    assert not any(model_for(r, "free").paid_only for r in ModelRole)
    assert model_for(ModelRole.JUDGE, "free").model_id != model_for(ModelRole.ANSWER, "free").model_id
