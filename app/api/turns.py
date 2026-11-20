"""Running one chat turn as an SSE stream: keep-alives, cancellation, and exactly-once cleanup.

Who may run a turn (single flight per session, per-IP concurrency, idempotent replay) is decided by the turn
gate (app/api/gate.py); the TurnStream holds the gate claim and the admission slot for the turn's lifetime.

TurnStream: the engine runs in its own task and feeds a queue; the HTTP side reads the queue and sends a
keep-alive comment when it has been idle for `keepalive_s`. close() is idempotent and runs on every exit
path (normal end, client disconnect, server cancellation): it cancels the engine task (which closes the
upstream model stream through aclosing), waits at most `cancel_grace_s` for it, releases the admission slot
exactly once, hands the claim back to the gate (with the frames of a completed turn, for replay) and persists
the turn record. If the engine itself crashes after streaming text, a replacing "busy" answer is sent before
the error, so unverified deltas never stay on screen (review C15).
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing

import anyio
import structlog

from app.api.gate import TurnClaim, TurnGate
from app.pipeline.engine import TurnEngine, TurnRequest
from app.pipeline.record import TurnRecord, TurnStatus, TurnTrace
from core.schemas.events import ChatEvent, DoneEvent, ErrorEvent, to_sse

log = structlog.get_logger(__name__)
KEEPALIVE_FRAME = ": keep-alive\n\n"
RECANCEL_INTERVAL_S = 0.01
_END = object()

Persist = Callable[[TurnRecord], Awaitable[None]]


class SlotGuard:
    """Releases an admission slot exactly once, whoever gets there first (close() or the finalizer)."""

    def __init__(self, release: Callable[[], None]) -> None:
        self._release = release
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._release()


def _release_abandoned(slot: SlotGuard | None, gate: TurnGate, claim: TurnClaim) -> None:
    """Finalizer for a TurnStream whose response was never started (e.g. the request task was cancelled
    between admission and the first byte): nothing may stay held."""
    if slot is not None and not slot.released:
        log.warning("turn_stream_abandoned", session_slot_released=True)
        slot.release()
    gate.release_nowait(claim)


class TurnStream:
    def __init__(
        self,
        *,
        engine: TurnEngine,
        request: TurnRequest,
        trace: TurnTrace,
        gate: TurnGate,
        claim: TurnClaim,
        persist: Persist,
        slot: SlotGuard | None,
        keepalive_s: float,
        cancel_grace_s: float,
    ) -> None:
        self._engine = engine
        self._req = request
        self._trace = trace
        self._gate = gate
        self._claim = claim
        self._persist = persist
        self._slot = slot
        self._keepalive_s = keepalive_s
        self._grace = cancel_grace_s
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._frames: list[str] = []
        self._done_sent = False
        self._streamed = False
        self._answered = False
        self._completed = False
        self._closed = False
        self._finalizer = weakref.finalize(self, _release_abandoned, slot, gate, claim)

    @property
    def closed(self) -> bool:
        return self._closed

    async def frames(self) -> AsyncIterator[str]:
        """The SSE frames of the turn. On normal completion the caller runs close() (SSEResponse's on_close,
        after the HTTP terminator, so persistence never delays the end of the response); on cancellation or
        error close() runs here at once."""
        self._task = asyncio.create_task(self._produce(), name=f"turn-{self._req.turn_id}")
        try:
            while True:
                try:
                    async with asyncio.timeout(self._keepalive_s):  # not wait_for: see _stop_task
                        item = await self._queue.get()
                except TimeoutError:
                    yield KEEPALIVE_FRAME
                    continue
                if item is _END:
                    break
                frame = to_sse(item)  # type: ignore[arg-type]
                self._frames.append(frame)
                yield frame
            self._completed = self._done_sent
        except BaseException:
            await self.close()
            raise

    async def _produce(self) -> None:
        try:
            async with aclosing(self._engine.run(self._req, self._trace)) as events:
                async for event in events:
                    self._note(event)
                    self._queue.put_nowait(event)
        except Exception as exc:
            log.error("turn_stream_failed", turn_id=self._req.turn_id, error=type(exc).__name__)
            self._trace.update(error_code="internal_error")
            for event in self._closing_events():
                self._queue.put_nowait(event)
        finally:
            self._queue.put_nowait(_END)

    def _note(self, event: ChatEvent) -> None:
        self._done_sent = self._done_sent or event.type == "done"
        self._streamed = self._streamed or event.type == "delta"
        self._answered = self._answered or event.type == "answer"

    def _closing_events(self) -> list[ChatEvent]:
        if self._done_sent:
            return []
        self._done_sent = True
        events: list[ChatEvent] = []
        if self._streamed and not self._answered:
            events.append(self._engine.busy_answer(self._req, self._trace, replaces=True))
        texts = self._engine.texts
        events += [
            ErrorEvent(code="internal_error", message=texts.error("internal_error", self._req.locale)),
            DoneEvent(turn_id=self._req.turn_id, turns_left=0),
        ]
        return events

    async def close(self) -> None:
        """Idempotent cleanup; shielded so that a cancelled caller still finishes it."""
        if self._closed:
            return
        self._closed = True
        with anyio.CancelScope(shield=True):
            try:
                await self._stop_task()
            finally:
                if self._slot is not None:
                    self._slot.release()
                self._finalizer.detach()
                await self._finish()

    async def _stop_task(self) -> None:
        """Cancel the engine task and wait for it, at most `cancel_grace_s`.

        Level-triggered: the cancellation is re-sent every RECANCEL_INTERVAL_S until the task exits, because a
        single task.cancel() can be swallowed (Python 3.11 asyncio.wait_for drops an outer cancellation when
        its inner awaitable completes in the same loop iteration), which would let the turn run on and keep
        the upstream model stream open."""
        task = self._task
        if task is None or task.done():
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._grace
        while not task.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                log.error("turn_cancel_timeout", turn_id=self._req.turn_id, grace_s=self._grace)
                return
            task.cancel()
            await asyncio.wait({task}, timeout=min(remaining, RECANCEL_INTERVAL_S))

    async def _finish(self) -> None:
        status: TurnStatus = "completed" if self._completed else "cancelled"
        record = self._trace.finish(status if not self._trace.record.error_code else "error")
        frames = tuple(self._frames) if self._completed else None
        try:
            await self._gate.finish(self._claim, self._req.turn_id, frames)
        except Exception as exc:  # the gate's TTLs free what could not be released
            log.error("turn_gate_finish_failed", turn_id=self._req.turn_id, error=type(exc).__name__)
        try:
            await self._persist(record)
        except Exception as exc:
            log.error("turn_persist_failed", turn_id=self._req.turn_id, error=type(exc).__name__)


async def replay_frames(frames: tuple[str, ...]) -> AsyncIterator[str]:
    for frame in frames:
        yield frame
