"""What one P4 turn and one P4 item produced, in a JSON-serialisable form (the resumable cache stores it).

The SSE body is kept as parsed event payloads with the time each event reached the client, measured from
the start of the POST /chat request; the passages the retriever returned (when recorded) are kept with their
full text so the metrics can re-check numbers and run the judge offline.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from core.schemas.events import CHAT_EVENT_ADAPTER, ChatEvent
from evals.fakes.asgi_driver import DriveResult
from evals.fakes.sse_contract import SSEFormatError, split_frames
from evals.p4.items import EvalItem


def timed_payloads(result: DriveResult) -> list[tuple[float, dict[str, Any]]]:
    """(seconds since the request started, event payload) for every complete SSE frame, keep-alives skipped.
    A frame is timed by the chunk that completed it."""
    out: list[tuple[float, dict[str, Any]]] = []
    buffer = ""
    for chunk, at in zip(result.chunks, result.chunk_times, strict=True):
        buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
        if "\n\n" not in buffer:
            continue
        complete, _, buffer = buffer.rpartition("\n\n")
        frames, _ = split_frames(complete + "\n\n")
        for frame in frames:
            payload = json.loads(frame.data)
            if payload.get("type") != frame.event:
                raise SSEFormatError(f"event name {frame.event!r} != payload type {payload.get('type')!r}")
            out.append((round(at - result.started_at, 4), payload))
    return out


@dataclass(frozen=True)
class TurnResult:
    message: str
    http_status: int
    payloads: tuple[dict[str, Any], ...] = ()
    times_s: tuple[float, ...] = ()
    elapsed_s: float = 0.0
    halted: bool = False  # the client disconnected on purpose once the guard had decided (safety suite)
    precheck_kinds: tuple[str, ...] = ()  # deterministic (lexicon / injection) kinds for this message
    calls: tuple[Mapping[str, str], ...] = ()
    retries: int = 0
    passages: tuple[Mapping[str, Any], ...] = ()  # last retrieval of the turn (full text), when recorded
    retrieval_confident: bool | None = None
    error: str = ""

    def events(self) -> list[ChatEvent]:
        return [CHAT_EVENT_ADAPTER.validate_python(p) for p in self.payloads]

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [p for p in self.payloads if p.get("type") == kind]

    def time_of_first(self, kind: str) -> float | None:
        return next(
            (t for p, t in zip(self.payloads, self.times_s, strict=True) if p.get("type") == kind), None
        )

    @property
    def answer(self) -> dict[str, Any] | None:
        answers = self.of_type("answer")
        return answers[-1] if answers else None

    @property
    def mode(self) -> str:
        ans = self.answer
        return str(ans.get("mode")) if ans else "none"

    @property
    def safety_kinds(self) -> frozenset[str]:
        return frozenset(str(p.get("kind")) for p in self.of_type("safety"))

    @property
    def streamed_text(self) -> str:
        return "".join(str(p.get("text", "")) for p in self.of_type("delta"))

    @property
    def complete(self) -> bool:
        return bool(self.payloads) and self.payloads[-1].get("type") == "done"

    def generation_roles(self) -> list[str]:
        return [c["role"] for c in self.calls if c.get("kind") == "generate" and c.get("outcome") != "halted"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "http_status": self.http_status,
            "payloads": list(self.payloads),
            "times_s": list(self.times_s),
            "elapsed_s": self.elapsed_s,
            "halted": self.halted,
            "precheck_kinds": list(self.precheck_kinds),
            "calls": [dict(c) for c in self.calls],
            "retries": self.retries,
            "passages": [dict(p) for p in self.passages],
            "retrieval_confident": self.retrieval_confident,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> TurnResult:
        confident = raw.get("retrieval_confident")
        return cls(
            message=str(raw.get("message", "")),
            http_status=int(raw.get("http_status", 0)),
            payloads=tuple(dict(p) for p in raw.get("payloads", [])),
            times_s=tuple(float(t) for t in raw.get("times_s", [])),
            elapsed_s=float(raw.get("elapsed_s", 0.0)),
            halted=bool(raw.get("halted", False)),
            precheck_kinds=tuple(str(k) for k in raw.get("precheck_kinds", [])),
            calls=tuple(dict(c) for c in raw.get("calls", [])),
            retries=int(raw.get("retries", 0)),
            passages=tuple(dict(p) for p in raw.get("passages", [])),
            retrieval_confident=None if confident is None else bool(confident),
            error=str(raw.get("error", "")),
        )


@dataclass(frozen=True)
class ItemResult:
    item: EvalItem
    turns: tuple[TurnResult, ...]
    finished_at: str
    release: Mapping[str, Any] = field(default_factory=dict)

    @property
    def last(self) -> TurnResult:
        return self.turns[-1]

    @property
    def detected_kinds(self) -> frozenset[str]:
        """Safety kinds the pipeline raised as SafetyEvents in any turn of the item."""
        return frozenset().union(*(t.safety_kinds for t in self.turns))

    @property
    def lexicon_kinds(self) -> frozenset[str]:
        return frozenset().union(*(frozenset(t.precheck_kinds) for t in self.turns))

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item.to_dict(),
            "turns": [t.to_dict() for t in self.turns],
            "finished_at": self.finished_at,
            "release": dict(self.release),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ItemResult:
        return cls(
            item=EvalItem.from_dict(raw["item"]),
            turns=tuple(TurnResult.from_dict(t) for t in raw["turns"]),
            finished_at=str(raw.get("finished_at", "")),
            release=dict(raw.get("release") or {}),
        )


def passage_dicts(passages: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    """RetrievedPassage models -> the fields the metrics need (full text kept)."""
    return tuple(
        {
            "chunk_id": p.chunk_id,
            "doc_id": p.doc_id,
            "source_id": p.source_id,
            "title": p.title,
            "content_type": p.content_type.value,
            "language": p.language.value,
            "text": p.text,
        }
        for p in passages
    )


def first_index(seq: Sequence[str], wanted: Iterable[str]) -> int | None:
    targets = set(wanted)
    return next((i for i, s in enumerate(seq) if s in targets), None)
