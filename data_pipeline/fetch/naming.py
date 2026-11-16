"""Map a URL to a stable, Windows-safe relative file path under raw/{source_id}/."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import unquote, urlsplit

_SAFE = re.compile(r"[^A-Za-z0-9._\-]+")
_MAX_SEGMENT = 80
_MAX_TOTAL = 150


def _segment(text: str) -> str:
    cleaned = _SAFE.sub("_", unquote(text)).strip("._") or "x"
    if len(cleaned) > _MAX_SEGMENT:
        digest = hashlib.sha1(cleaned.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
        cleaned = f"{cleaned[:_MAX_SEGMENT - 11]}_{digest}"
    return cleaned


def url_to_relpath(url: str) -> str:
    """host/segment/.../name  (forward slashes). Queries are folded into the name as a short hash."""
    parts = urlsplit(url)
    host = _segment(parts.hostname or "unknown")
    segments = [_segment(s) for s in parts.path.split("/") if s]
    name = segments.pop() if segments else "index"
    if parts.path.endswith("/") or not segments and not parts.path.strip("/"):
        segments.append(name)
        name = "index"
    if parts.query:
        digest = hashlib.sha1(parts.query.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
        stem, dot, ext = name.rpartition(".")
        name = f"{stem}.{digest}.{ext}" if dot and len(ext) <= 5 else f"{name}.{digest}"
    if "." not in name and name != "index":
        name += ".page"  # a page "a/b" and its child "a/b/c" must not need both a file and a directory "b"
    relpath = "/".join([host, *segments, name])
    if len(relpath) > _MAX_TOTAL:
        digest = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        ext = name.rpartition(".")[2] if "." in name and len(name.rpartition(".")[2]) <= 5 else "bin"
        relpath = f"{host}/long/{digest}.{ext}"
    return relpath
