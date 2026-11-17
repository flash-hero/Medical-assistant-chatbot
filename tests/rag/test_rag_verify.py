"""Signed manifests (review S8/P6): HKDF key, what the signature covers, and verification against the
payloads actually stored in Qdrant (local mode, no server)."""

import hashlib
import hmac
import json
import shutil

import pytest
from qdrant_client import AsyncQdrantClient, models
from rag_fixtures import QDRANT_LOCAL_WARNINGS, TEST_SECRET, build_index, corpus_docs

from core.config import Settings
from core.errors import InvalidInput
from rag.chunking import chunk_document
from rag.embedding import embed_model_id
from rag.errors import CorpusUnverified, IndexMismatch
from rag.index import switch_alias
from rag.manifest import chunks_digest, make_manifest, read_manifest, write_manifest
from rag.paths import DataPaths
from rag.signing import (
    MANIFEST_KEY_INFO,
    SIGNED_FIELDS,
    hkdf_sha256,
    manifest_key,
    record_hash,
    sign_manifest,
    signature_matches,
    text_checksum,
)
from rag.verify import verify_collection, verify_live_corpus

pytestmark = [pytest.mark.filterwarnings(w) for w in QDRANT_LOCAL_WARNINGS]
ALIAS = "verify_alias"
FAKE_MODEL = embed_model_id("fake")


# ---- key derivation and signature scope --------------------------------------------------------------
def test_hkdf_matches_rfc5869_test_vectors():
    ikm = bytes([0x0B] * 22)
    case1 = hkdf_sha256(ikm, salt=bytes(range(13)), info=bytes(range(0xF0, 0xFA)), length=42)
    assert case1.hex() == (
        "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"
    )
    case3 = hkdf_sha256(ikm, info=b"", length=42)
    assert case3.hex() == (
        "8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d9d201395faa4b61a96c8"
    )
    with pytest.raises(ValueError):
        hkdf_sha256(ikm, info=b"", length=0)


def test_manifest_key_is_hkdf_with_its_own_label():
    hkdf = pytest.importorskip("cryptography.hazmat.primitives.kdf.hkdf")
    from cryptography.hazmat.primitives import hashes

    expected = hkdf.HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=MANIFEST_KEY_INFO).derive(
        TEST_SECRET.encode()
    )
    assert MANIFEST_KEY_INFO == b"ausculta-manifest-v1"
    assert manifest_key(TEST_SECRET) == expected
    assert manifest_key(TEST_SECRET) != TEST_SECRET.encode()
    assert (
        manifest_key(TEST_SECRET) != hashlib.sha256(b"ausculta-session-token" + TEST_SECRET.encode()).digest()
    )
    with pytest.raises(InvalidInput):
        manifest_key("")


def _manifest(chunks, **over):
    from datetime import UTC, datetime

    args = {
        "corpus_version": "v1",
        "collection": "ausculta_corpus_v1",
        "chunks": chunks,
        "embed_model": FAKE_MODEL,
        "embed_dim": 768,
        "secret": TEST_SECRET,
        "created_at": datetime(2026, 11, 16, tzinfo=UTC),
    }
    return make_manifest(**{**args, **over})


def test_signature_covers_every_served_field_and_the_manifest_metadata():
    chunks = [c for d in corpus_docs() for c in chunk_document(d, publisher="P")]
    manifest = _manifest(chunks)
    digest = chunks_digest(chunks)
    assert signature_matches(manifest, digest, TEST_SECRET)
    assert not signature_matches(manifest, digest, "other-secret-0123456789")
    old_scheme = hmac.new(
        TEST_SECRET.encode(), "\n".join(sorted(c.checksum for c in chunks)).encode(), hashlib.sha256
    ).hexdigest()
    assert not signature_matches(manifest.model_copy(update={"signature": old_scheme}), digest, TEST_SECRET)
    assert not signature_matches(manifest.model_copy(update={"signature": ""}), digest, TEST_SECRET)
    for field, value in {
        "corpus_version": "v2",
        "collection": "ausculta_corpus_v2",
        "embed_model": "other@fmt1",
        "embed_dim": 1024,
        "documents": 99,
        "sources": {"demo_src": 1},
    }.items():
        assert not signature_matches(manifest.model_copy(update={field: value}), digest, TEST_SECRET), field
    payload = chunks[0].model_dump(mode="json")
    served = ("text", "url", "title", "reuse_mode", "trust_tier", "attribution", "language", "checksum")
    assert set(served) <= set(SIGNED_FIELDS)
    for field in SIGNED_FIELDS:
        assert record_hash({**payload, field: "tampered"}) != record_hash(payload), field
    assert record_hash({**payload, "token_estimate": 1}) == record_hash(payload)  # not served: not signed
    assert text_checksum(payload) == chunks[0].checksum
    assert sign_manifest(manifest, digest, TEST_SECRET) == manifest.signature


# ---- verification against Qdrant --------------------------------------------------------------------
@pytest.fixture
async def live(tmp_path, registry_path, monkeypatch):
    client = AsyncQdrantClient(location=":memory:")
    collection = await build_index(tmp_path, registry_path, client, corpus_docs())
    await switch_alias(client, ALIAS, collection)
    settings = Settings(
        AUSCULTA_DATA_ROOT=str(tmp_path / "data"),
        AUSCULTA_EMBED_BACKEND="fake",
        AUSCULTA_SESSION_SECRET=TEST_SECRET,
        QDRANT_ALIAS=ALIAS,
    )
    yield client, collection, settings
    await client.close()


async def _first_point(client, collection):
    records, _ = await client.scroll(collection, limit=1, with_payload=True)
    return records[0]


async def test_live_corpus_verifies_and_reports_what_was_checked(live):
    client, collection, settings = live
    verified = await verify_live_corpus(settings, client=client)
    assert verified.collection == collection
    assert verified.corpus_version == "t1"
    assert verified.embed_model == FAKE_MODEL
    assert verified.chunks == 4
    assert isinstance(CorpusUnverified("x"), IndexMismatch)  # promote/CLI error handling unchanged
    assert CorpusUnverified.code == "corpus_unverified"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("url", "https://evil.example.com/asthma"),
        ("title", "Asthma cure"),
        ("reuse_mode", "verbatim_ok"),
        ("trust_tier", 3),
        ("attribution", "Source: someone else"),
        ("language", "fr"),
        ("content_type", "drug_label"),
    ],
)
async def test_editing_a_served_field_in_qdrant_fails_verification(live, field, value):
    client, collection, settings = live
    point = await _first_point(client, collection)
    await client.set_payload(collection, payload={field: value}, points=[point.id])
    with pytest.raises(CorpusUnverified, match="do not match the signed manifest"):
        await verify_live_corpus(settings, client=client)


async def test_edited_text_is_caught_by_the_recomputed_checksum_even_with_a_matching_checksum(live):
    client, collection, settings = live
    point = await _first_point(client, collection)
    text = "Asthma is cured by drinking bleach."
    await client.set_payload(collection, payload={"text": text}, points=[point.id])
    with pytest.raises(CorpusUnverified, match="1 stored chunk"):
        await verify_live_corpus(settings, client=client)
    forged = text_checksum({**point.payload, "text": text})  # attacker also rewrites the checksum
    await client.set_payload(collection, payload={"checksum": forged}, points=[point.id])
    with pytest.raises(CorpusUnverified, match="do not match the signed manifest"):
        await verify_live_corpus(settings, client=client)


async def test_missing_or_extra_points_fail_verification(live):
    client, collection, settings = live
    point = await _first_point(client, collection)
    await client.delete(collection, points_selector=models.PointIdsList(points=[point.id]), wait=True)
    with pytest.raises(CorpusUnverified, match="do not match the signed manifest"):
        await verify_live_corpus(settings, client=client)
    copy = models.PointStruct(
        id="00000000-0000-0000-0000-000000000001",
        vector={"dense": [0.0] * 767 + [1.0]},
        payload=point.payload,
    )
    await client.upsert(collection, [copy], wait=True)  # count is right again, but under a foreign id
    with pytest.raises(CorpusUnverified, match="foreign id"):
        await verify_live_corpus(settings, client=client)


async def test_collection_built_with_another_embedding_model_is_refused(live):
    client, _collection, settings = live
    local = settings.model_copy(update={"embed_backend": "local"})
    with pytest.raises(CorpusUnverified, match="embeds queries with google/embeddinggemma-300m"):
        await verify_live_corpus(local, client=client)


async def test_manifest_problems_and_missing_inputs_fail_verification(live):
    client, collection, settings = live
    paths = DataPaths.from_settings(settings)
    with pytest.raises(CorpusUnverified, match="SESSION_SECRET"):
        await verify_live_corpus(settings.model_copy(update={"session_secret": None}), client=client)
    with pytest.raises(CorpusUnverified, match="does not point at any collection"):
        await verify_live_corpus(settings.model_copy(update={"qdrant_alias": "nope"}), client=client)
    with pytest.raises(CorpusUnverified, match="does not exist"):
        await verify_collection(client, paths, "ausculta_corpus_nope", TEST_SECRET)
    manifest = read_manifest(paths, collection)
    write_manifest(paths, manifest.model_copy(update={"collection": "ausculta_corpus_other"}))
    shutil.copy(paths.manifest_file("ausculta_corpus_other"), paths.manifest_file(collection))
    with pytest.raises(CorpusUnverified, match="describes"):
        await verify_live_corpus(settings, client=client)
    paths.manifest_file(collection).unlink()
    with pytest.raises(CorpusUnverified, match="no manifest"):
        await verify_live_corpus(settings, client=client)
    data = manifest.model_dump(mode="json")
    paths.manifest_file(collection).write_text(json.dumps({**data, "chunks": 3}), encoding="utf-8")
    with pytest.raises(CorpusUnverified, match="do not match the signed manifest"):
        await verify_live_corpus(settings, client=client)


@pytest.mark.filterwarnings("ignore:Failed to obtain server version:UserWarning")
async def test_unreachable_qdrant_is_reported_as_unverified(tmp_path):
    settings = Settings(
        AUSCULTA_DATA_ROOT=str(tmp_path),
        AUSCULTA_SESSION_SECRET=TEST_SECRET,
        AUSCULTA_EMBED_BACKEND="fake",
        QDRANT_URL="http://127.0.0.1:9",
    )
    with pytest.raises(CorpusUnverified, match="vector store unavailable"):
        await verify_live_corpus(settings)
