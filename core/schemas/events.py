"""Server-Sent Events protocol for POST /api/v1/chat.

Wire format: each event is `event: <type>\\ndata: <json>\\n\\n`, json = the model below (includes "type").
Ordering guarantees (tested in tests/contracts):
  1. `meta` is always first, `done` is always last (exactly once each), unless the connection drops.
  2. A `safety` event, when present, comes before any `delta` / `answer`.
  3. `delta` events only occur for streamed (low-risk) answers; their concatenation equals the text that
     the following `answer` event confirms, unless `answer.replaces_stream` is true (the UI must then
     discard the streamed text and render `answer.text`).
  4. Verify-then-release answers emit `status(verifying)` and then a single `answer`, no `delta`.
  5. `error` may appear at most once and is followed by `done`.
Text fields are plain text with a restricted Markdown subset (paragraphs, "- " lists, **bold**) and
[n] citation markers. No HTML, no links, no images: the UI renders links only from `citations`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from core.schemas.chat import Citation, Intent, Locale


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReleaseInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_version: str
    corpus_version: str
    prompt_hash: str
    models: dict[str, str]


class MetaEvent(_Event):
    type: Literal["meta"] = "meta"
    turn_id: str
    session_id: str
    locale: Locale
    demo_mode: bool
    release: ReleaseInfo


class StatusEvent(_Event):
    type: Literal["status"] = "status"
    stage: Literal["checking", "searching", "writing", "verifying"]


class Contact(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    number: str  # dialable string, from the verified hospital profile only
    hours: str = ""


class SafetyEvent(_Event):
    type: Literal["safety"] = "safety"
    kind: Literal["emergency", "self_harm", "harm_to_others", "abuse_disclosure"]
    template_id: str  # clinician-approved template key, e.g. "emergency.v1"
    title: str
    message: str
    contacts: tuple[Contact, ...] = ()
    sticky: bool = True  # UI keeps the banner visible for the rest of the session
    language: Locale | None = None  # language of title/message (may differ from the UI locale)


class DeltaEvent(_Event):
    type: Literal["delta"] = "delta"
    text: str  # one or more complete sentences that passed inline checks


class AnswerEvent(_Event):
    type: Literal["answer"] = "answer"
    text: str
    citations: tuple[Citation, ...] = ()
    intent: Intent
    mode: Literal["streamed", "verified", "template", "abstain", "refusal"]
    verified: bool  # true when post-generation checks passed (groundedness, numbers, citations)
    replaces_stream: bool = False
    source_language_note: bool = False  # true when cited sources are in a different language
    show_seek_care: bool = False  # UI renders the "when to seek care" panel
    language: Locale | None = None  # language the text is written in (may differ from the UI locale)


class NoticeEvent(_Event):
    type: Literal["notice"] = "notice"
    code: Literal["degraded", "source_language", "demo_mode", "session_limit_near", "handoff_available"]
    message: str


class FormField(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    kind: Literal["text", "tel", "email", "date", "select", "textarea"]
    required: bool = False
    options: tuple[str, ...] = ()
    max_length: int = 200


class FormEvent(_Event):
    type: Literal["form"] = "form"
    form_id: Literal["appointment_request"]
    title: str
    description: str
    fields: tuple[FormField, ...]
    submit_url: str = "/api/v1/appointments"


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    code: str  # stable code from core.errors
    message: str  # localised, user-safe
    retry_after_s: float | None = None


class DoneEvent(_Event):
    type: Literal["done"] = "done"
    turn_id: str
    turns_left: int


ChatEvent = Annotated[
    MetaEvent
    | StatusEvent
    | SafetyEvent
    | DeltaEvent
    | AnswerEvent
    | NoticeEvent
    | FormEvent
    | ErrorEvent
    | DoneEvent,
    Field(discriminator="type"),
]
CHAT_EVENT_ADAPTER: TypeAdapter[ChatEvent] = TypeAdapter(ChatEvent)


def to_sse(event: _Event) -> str:
    """Serialise one event to the SSE wire format."""
    payload = event.model_dump_json(exclude_none=False)
    return f"event: {event.type}\ndata: {payload}\n\n"  # type: ignore[attr-defined]
