"""Running one chat turn as an SSE stream: idempotency, single flight per session, keep-alives, cancellation.

TurnRegistry (in-process):
  - one running turn per session (a second concurrent turn gets 409 turn_in_progress)
  - a completed turn's SSE frames are kept for a short time, keyed by (session_id, client_turn_id), so a
    client retry with the same client_turn_id replays the answer instead of running (and paying for) the
    turn again. The frames live only in process memory, never in the database.

TurnStream: the engine runs in its own task and feeds a queue; the HTTP side reads the queue and sends a
keep-alive comment when it has been idle for `keepalive_s`. close() is idempotent and runs on every exit
path (normal end, client disconnect, server cancellation): it cancels the engine task (which closes the
upstream model stream through aclosing), waits at most `cancel_grace_s` for it, releases the admission slot
exactly once and persists the turn record.
"""

from __future__ import annotations

import asyncio
import time
import weakref
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass

import anyio
import structlog

from app.api.errors import TurnInProgress
from app.pipeline.engine import TurnEngine, TurnRequest
from app.pipeline.record import TurnRecord, TurnStatus, TurnTrace
from core.schemas.events import ChatEvent, DoneEvent, ErrorEvent, to_sse

log = structlog.get_logger(__name__)
KEEPALIVE_FRAME = ": keep-alive\n\n"
REPLAY_TTL_S = 10 * 60
REPLAY_MAX = 2000
RECANCEL_INTERVAL_S = 0.01
_END = object()


@dataclass(frozen=True)
class _Completed:
    frames: tuple[str, ...]
    turn_id: str
    at: float


class TurnRegistry:
    def __init__(
        self,
        *,
        ttl_s: float = REPLAY_TTL_S,
        max_entries: int = REPLAY_MAX,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._running: dict[str, str] = {}
        self._done: OrderedDict[tuple[str, str], _Completed] = OrderedDict()
        self._turn_owner: OrderedDict[str, str] = OrderedDict()
        self._ttl = ttl_s
        self._max = max_entries
        self._clock = clock

    @property
    def running(self) -> int:
        return len(self._running)

    def _expire(self) -> None:
        now = self._clock()
        while self._done:
            item = next(iter(self._done.values()))
            if now - item.at <= self._ttl and len(self._done) <= self._max:
                break
            self._done.popitem(last=False)
        while len(self._turn_owner) > self._max * 4:
            self._turn_owner.popitem(last=False)

    def replay(self, session_id: str, client_turn_id: str) -> tuple[str, ...] | None:
        self._expire()
        done = self._done.get((session_id, client_turn_id))
        return done.frames if done else None

    def begin(self, session_id: str, client_turn_id: str) -> None:
        """Claim the session for one turn; raises TurnInProgress while another turn of it is running."""
        if session_id in self._running:
            raise TurnInProgress("a turn of this session is still running")
        self._running[session_id] = client_turn_id

    def abandon(self, session_id: str, client_turn_id: str) -> None:
        """Release the session claim of a turn that never started (admission or spend check failed)."""
        if self._running.get(session_id) == client_turn_id:
            del self._running[session_id]

    def finish(
        self, session_id: str, client_turn_id: str, turn_id: str, frames: tuple[str, ...] | None
    ) -> None:
        self.abandon(session_id, client_turn_id)
        self._turn_owner[turn_id] = session_id
        if frames is not None:
            self._done[(session_id, client_turn_id)] = _Completed(frames, turn_id, self._clock())
        self._expire()

    def owns(self, turn_id: str, session_id: str) -> bool:
        return self._turn_owner.get(turn_id) == session_id


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


def _release_abandoned(
    slot: SlotGuard | None, registry: TurnRegistry, session_id: str, client_turn_id: str
) -> None:
    """Finalizer for a TurnStream whose response was never started (e.g. the request task was cancelled
    between admission and the first byte): nothing may stay held."""
    if slot is not None and not slot.released:
        log.warning("turn_stream_abandoned", session_slot_released=True)
        slot.release()
    registry.abandon(session_id, client_turn_id)


class TurnStream:
    def __init__(
        self,
        *,
        engine: TurnEngine,
        request: TurnRequest,
        trace: TurnTrace,
        registry: TurnRegistry,
        persist: Persist,
        slot: SlotGuard | None,
        keepalive_s: float,
        cancel_grace_s: float,
    ) -> None:
        self._engine = engine
        self._req = request
        self._trace = trace
        self._registry = registry
        self._persist = persist
        self._slot = slot
        self._keepalive_s = keepalive_s
        self._grace = cancel_grace_s
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._frames: list[str] = []
        self._done_sent = False
        self._completed = False
        self._closed = False
        self._finalizer = weakref.finalize(
            self, _release_abandoned, slot, registry, request.session.session_id, request.client_turn_id
        )

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
                    self._done_sent = self._done_sent or event.type == "done"
                    self._queue.put_nowait(event)
        except Exception as exc:
            log.error("turn_stream_failed", turn_id=self._req.turn_id, error=type(exc).__name__)
            self._trace.update(error_code="internal_error")
            for event in self._closing_events():
                self._queue.put_nowait(event)
        finally:
            self._queue.put_nowait(_END)

    def _closing_events(self) -> list[ChatEvent]:
        if self._done_sent:
            return []
        self._done_sent = True
        texts = self._engine.texts
        return [
            ErrorEvent(code="internal_error", message=texts.error("internal_error", self._req.locale)),
            DoneEvent(turn_id=self._req.turn_id, turns_left=0),
        ]

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
        self._registry.finish(
            self._req.session.session_id, self._req.client_turn_id, self._req.turn_id, frames
        )
        try:
            await self._persist(record)
        except Exception as exc:
            log.error("turn_persist_failed", turn_id=self._req.turn_id, error=type(exc).__name__)


async def replay_frames(frames: tuple[str, ...]) -> AsyncIterator[str]:
    for frame in frames:
        yield frame
