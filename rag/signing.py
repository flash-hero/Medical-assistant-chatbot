"""Corpus-manifest signature, scheme "ausculta-manifest-v1" (review S8/P6).

What is signed: HMAC-SHA256 over the canonical JSON of
  - every manifest field except `signature` (corpus_version, collection, embed_model, embed_dim, created_at,
    sources, documents, chunks), and
  - the corpus digest: sha256 of the sorted per-chunk record hashes, where a record hash is sha256 of the
    canonical JSON of every SIGNED_FIELDS value of the chunk payload stored in Qdrant (all the fields a
    RetrievedPassage serves: text, url, title, reuse_mode, trust_tier, attribution, language, ... and the
    checksum), so editing any served field in Qdrant breaks the signature.
Verification (rag.verify) also recomputes each chunk's checksum, sha256(context_header + "\\n" + text), from
the stored text instead of trusting the stored checksum. Dense/sparse vectors are not signed (they only
change ranking, never what is shown or cited).

Key: HKDF-SHA256 (RFC 5869) of AUSCULTA_SESSION_SECRET with info "ausculta-manifest-v1", a key used for
nothing else (session tokens derive their own key from the same secret).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterable, Mapping
from typing import Any

from core.errors import InvalidInput
from core.schemas.document import CorpusManifest

SIGNATURE_SCHEME = "ausculta-manifest-v1"
MANIFEST_KEY_INFO = SIGNATURE_SCHEME.encode("ascii")
_HASH_LEN = 32
# Fixed for scheme v1 (a new Chunk field must not silently change what old manifests cover).
SIGNED_FIELDS: tuple[str, ...] = (
    "attribution",
    "checksum",
    "chunk_id",
    "content_type",
    "context_header",
    "doc_id",
    "heading_path",
    "language",
    "ordinal",
    "parent_id",
    "reuse_mode",
    "reviewed_on",
    "source_id",
    "text",
    "title",
    "trust_tier",
    "url",
)


def hkdf_sha256(ikm: bytes, *, info: bytes, salt: bytes = b"", length: int = _HASH_LEN) -> bytes:
    """RFC 5869 HKDF with SHA-256 (extract then expand)."""
    if not 0 < length <= 255 * _HASH_LEN:
        raise ValueError("invalid HKDF output length")
    prk = hmac.new(salt or b"\x00" * _HASH_LEN, ikm, hashlib.sha256).digest()
    okm, block = b"", b""
    for counter in range(1, -(-length // _HASH_LEN) + 1):
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
    return okm[:length]


def manifest_key(secret: str) -> bytes:
    if not secret:
        raise InvalidInput("AUSCULTA_SESSION_SECRET is required to sign or verify the corpus manifest")
    return hkdf_sha256(secret.encode("utf-8"), info=MANIFEST_KEY_INFO)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def record_hash(payload: Mapping[str, Any]) -> str:
    """Hash of the served fields of one stored chunk payload (absent fields count as null)."""
    return hashlib.sha256(canonical_json({k: payload.get(k) for k in SIGNED_FIELDS})).hexdigest()


def text_checksum(payload: Mapping[str, Any]) -> str:
    """Chunk.checksum recomputed from the stored text: sha256(context_header + "\\n" + text)."""
    header, text = str(payload.get("context_header", "")), str(payload.get("text", ""))
    return hashlib.sha256(f"{header}\n{text}".encode()).hexdigest()


def corpus_digest(record_hashes: Iterable[str]) -> str:
    """Order-independent digest of a collection's chunks (a multiset: duplicates count)."""
    return hashlib.sha256("\n".join(sorted(record_hashes)).encode("ascii")).hexdigest()


def manifest_message(manifest: CorpusManifest, digest: str) -> bytes:
    fields = manifest.model_dump(mode="json", exclude={"signature"})
    return canonical_json({"scheme": SIGNATURE_SCHEME, "manifest": fields, "corpus_digest": digest})


def sign_manifest(manifest: CorpusManifest, digest: str, secret: str) -> str:
    return hmac.new(manifest_key(secret), manifest_message(manifest, digest), hashlib.sha256).hexdigest()


def signature_matches(manifest: CorpusManifest, digest: str, secret: str) -> bool:
    return bool(manifest.signature) and hmac.compare_digest(
        manifest.signature, sign_manifest(manifest, digest, secret)
    )
