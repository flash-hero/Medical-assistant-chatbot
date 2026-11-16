"""SSE wire parsing and the ordering guarantees of core/schemas/events.py, as a reusable checker.

  events = parse_sse(body)                 # list of validated ChatEvent models (keep-alive comments skipped)
  problems = order_violations(events)      # [] when every guarantee holds

Used by the engine/API contract tests and by the safety/red-team evals (safety.template_first).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from core.schemas.events import CHAT_EVENT_ADAPTER, ChatEvent


@dataclass(frozen=True)
class SSEFrame:
    event: str
    data: str


class SSEFormatError(ValueError):
    """The body is not well-formed SSE for this protocol."""


def split_frames(body: str) -> tuple[list[SSEFrame], int]:
    """Split an SSE body into frames; returns (frames, number of comment-only frames such as keep-alives)."""
    frames: list[SSEFrame] = []
    comments = 0
    for block in body.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        if all(line.startswith(":") for line in lines):
            comments += 1
            continue
        fields = dict(line.split(": ", 1) for line in lines if not line.startswith(":") and ": " in line)
        if set(fields) != {"event", "data"}:
            raise SSEFormatError(f"frame must have exactly 'event' and 'data' fields: {block[:80]!r}")
        frames.append(SSEFrame(event=fields["event"], data=fields["data"]))
    return frames, comments


def parse_sse(body: str) -> list[ChatEvent]:
    """Parse and validate every frame; the `event:` name must equal the payload's `type`."""
    out: list[ChatEvent] = []
    for frame in split_frames(body)[0]:
        payload = json.loads(frame.data)
        event = CHAT_EVENT_ADAPTER.validate_python(payload)
        if event.type != frame.event:
            raise SSEFormatError(f"event name {frame.event!r} != payload type {event.type!r}")
        out.append(event)
    return out


def _streamed_text_matches(events: Sequence[ChatEvent]) -> list[str]:
    problems: list[str] = []
    streamed = "".join(e.text for e in events if e.type == "delta")  # type: ignore[union-attr]
    answers = [e for e in events if e.type == "answer"]
    if streamed and not answers:
        problems.append("delta events without a final answer")
    for ans in answers:
        if streamed and not ans.replaces_stream and ans.text != streamed:  # type: ignore[union-attr]
            problems.append("answer text differs from the streamed deltas but replaces_stream is false")
        if ans.mode == "verified" and streamed:  # type: ignore[union-attr]
            problems.append("verified answer was streamed")
    return problems


def order_violations(events: Sequence[ChatEvent]) -> list[str]:
    """Check the five ordering guarantees; returns human-readable problems (empty when valid)."""
    types = [e.type for e in events]
    problems: list[str] = []
    if not types or types[0] != "meta" or types.count("meta") != 1:
        problems.append("meta must be first, exactly once")
    if not types or types[-1] != "done" or types.count("done") != 1:
        problems.append("done must be last, exactly once")
    if "safety" in types:
        last_safety = max(i for i, t in enumerate(types) if t == "safety")
        content = [i for i, t in enumerate(types) if t in ("delta", "answer")]
        if content and min(content) < last_safety:
            problems.append("safety event after delta/answer")
    if "verifying" in [getattr(e, "stage", "") for e in events] and "delta" in types:
        problems.append("delta events in a verify-then-release answer")
    if types.count("error") > 1:
        problems.append("more than one error event")
    if "error" in types and types.index("error") != len(types) - 2:
        problems.append("error must be followed directly by done")
    if types.count("answer") > 1:
        problems.append("more than one answer event")
    return problems + _streamed_text_matches(events)
