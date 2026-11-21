"""Block until PostgreSQL, Redis and Qdrant accept connections (supervisord starts them in parallel)."""

from __future__ import annotations

import os
import socket
import sys
import time
import urllib.request

DEADLINE_S = 180
TCP = {"postgres": ("127.0.0.1", 5432), "redis": ("127.0.0.1", 6379)}
QDRANT_READY = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333") + "/readyz"


def _tcp_ok(addr: tuple[str, int]) -> bool:
    try:
        with socket.create_connection(addr, timeout=1):
            return True
    except OSError:
        return False


def _qdrant_ok() -> bool:
    try:
        with urllib.request.urlopen(QDRANT_READY, timeout=2) as resp:  # noqa: S310 (fixed localhost URL)
            return bool(resp.status == 200)
    except OSError:
        return False


def main() -> int:
    deadline = time.monotonic() + DEADLINE_S
    pending = {*TCP, "qdrant"}
    while pending and time.monotonic() < deadline:
        pending = {name for name in pending if not (_qdrant_ok() if name == "qdrant" else _tcp_ok(TCP[name]))}
        if pending:
            time.sleep(1)
    if pending:
        print(f"wait_deps: not ready after {DEADLINE_S}s: {sorted(pending)}", file=sys.stderr)
        return 1
    print("wait_deps: postgres, redis and qdrant are ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
