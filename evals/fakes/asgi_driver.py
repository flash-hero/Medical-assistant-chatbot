"""Minimal in-process ASGI HTTP driver with controllable client disconnects (no sockets).

httpx.ASGITransport buffers the whole response and never disconnects early, so cancellation tests use this:

  result = await drive(app, "POST", "/api/v1/chat", json_body, headers, disconnect_after_chunks=2)

`disconnect_after_chunks=N` delivers `http.disconnect` once N non-empty body chunks were sent;
`disconnect_when=pred` delivers it once `pred(result)` is true after a chunk; `disconnect_after_s` delivers it
after a delay; with none of them, the request completes normally. Pass your own `result` to watch progress
(chunks, chunk times, disconnect time) from another task while the request runs.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

ASGIApp = Any


@dataclass
class DriveResult:
    status: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    chunks: list[bytes] = field(default_factory=list)
    chunk_times: list[float] = field(default_factory=list)  # time.perf_counter() when each chunk arrived
    started_at: float = 0.0
    elapsed_s: float = 0.0
    disconnected_at: float | None = None
    finished_at: float | None = None

    @property
    def body(self) -> str:
        return b"".join(self.chunks).decode("utf-8")

    def first_chunk_at(self, needle: str) -> float | None:
        """perf_counter time of the first chunk containing `needle` (e.g. "event: safety")."""
        for chunk, at in zip(self.chunks, self.chunk_times, strict=True):
            if needle in chunk.decode("utf-8", errors="replace"):
                return at
        return None


def _scope(
    method: str, path: str, headers: Mapping[str, str], body: bytes, client: tuple[str, int]
) -> dict[str, Any]:
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    raw.append((b"content-length", str(len(body)).encode()))
    raw.append((b"host", b"testserver"))
    target, _, query = path.partition("?")
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": target,
        "raw_path": target.encode(),
        "query_string": query.encode("latin-1"),
        "root_path": "",
        "headers": raw,
        "client": client,
        "server": ("testserver", 80),
    }


async def drive(
    app: ASGIApp,
    method: str,
    path: str,
    payload: object | None = None,
    headers: Mapping[str, str] | None = None,
    *,
    disconnect_after_chunks: int | None = None,
    disconnect_after_s: float | None = None,
    disconnect_when: Callable[[DriveResult], bool] | None = None,
    client: tuple[str, int] = ("198.51.100.9", 40000),
    result: DriveResult | None = None,
) -> DriveResult:
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    hdrs = {"content-type": "application/json", **(headers or {})}
    result = result if result is not None else DriveResult()
    gone = asyncio.Event()
    body_sent = False
    result.started_at = t0 = time.perf_counter()

    def disconnect() -> None:
        if not gone.is_set():
            result.disconnected_at = time.perf_counter()
            gone.set()

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    def should_disconnect() -> bool:
        if disconnect_after_chunks is not None and len(result.chunks) >= disconnect_after_chunks:
            return True
        return disconnect_when is not None and disconnect_when(result)

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            result.status = message["status"]
            result.headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            if gone.is_set():
                raise OSError("client disconnected")
            chunk = message.get("body", b"")
            if chunk:
                result.chunks.append(chunk)
                result.chunk_times.append(time.perf_counter())
            if should_disconnect():
                disconnect()
            if not message.get("more_body", False):
                result.finished_at = time.perf_counter()
                disconnect()  # response complete: later receive() calls see a disconnect, like real servers

    timer = None
    if disconnect_after_s is not None:
        timer = asyncio.get_running_loop().call_later(disconnect_after_s, disconnect)
    try:
        await app(_scope(method, path, hdrs, body, client), receive, send)
    finally:
        if timer is not None:
            timer.cancel()
        result.elapsed_s = time.perf_counter() - t0
    return result
