"""SSE response that always watches for client disconnects.

Starlette only listens for `http.disconnect` on ASGI spec < 2.4 and otherwise notices a gone client on the
next failed send, which can be many seconds away while an answer is generated off-screen. This response
always runs the disconnect listener next to the body, so a disconnect cancels the turn immediately;
`on_close` (the turn's idempotent cleanup) then runs shielded on every exit path, even when the body
iterator never started.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

SSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
}


class SSEResponse(StreamingResponse):
    media_type = "text/event-stream"

    def __init__(
        self,
        body: AsyncIterator[str],
        *,
        on_close: Callable[[], Awaitable[None]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(body, status_code=200, headers={**SSE_HEADERS, **(headers or {})})
        self._body = body
        self._on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            async with anyio.create_task_group() as tg:

                async def stream() -> None:
                    with contextlib.suppress(OSError):  # the client went away while we were sending
                        await self.stream_response(send)
                    tg.cancel_scope.cancel()

                tg.start_soon(stream)
                await self.listen_for_disconnect(receive)
                tg.cancel_scope.cancel()
        finally:
            with anyio.CancelScope(shield=True):
                aclose = getattr(self._body, "aclose", None)
                if aclose is not None:
                    await aclose()
                if self._on_close is not None:
                    await self._on_close()
