"""Measure gate rag.resume_repeat_embeds: build, stop mid-way (daily-quota error), resume, count repeats.

Runs the real IndexBuilder on synthetic documents against an in-memory Qdrant with counting fake providers
(FakeLLMProvider vectors), so it needs no network and costs no quota. A repeat is any text sent to the
embedding API in the resumed run that the first run had already embedded.
"""

from __future__ import annotations

import contextlib
import tempfile
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import HttpUrl
from qdrant_client import AsyncQdrantClient

from core.errors import UpstreamRateLimited
from core.models import ModelRole
from core.schemas.document import Document, Section
from core.schemas.source import ContentType, Language, ReuseMode
from evals.fakes.fake_llm import FakeLLMProvider
from rag.build import BuildRequest, IndexBuilder
from rag.embed_cache import EmbeddingCache
from rag.embedding import DocumentEmbedder
from rag.errors import EmbeddingQuotaExhausted
from rag.paths import DataPaths
from rag.registry import load_registry
from rag.sparse import SparseEncoder

_WORDS = (
    "blood sugar insulin kidney heart lung doctor fever cough rash pain vaccine sleep diet nerve skin".split()  # noqa: SIM905
)
_SOURCE = "resume_check_src"


@dataclass(frozen=True)
class ResumeCheck:
    total_chunks: int
    first_run_embedded: int
    resumed_embedded: int
    repeat_calls: int


class CountingLLM(FakeLLMProvider):
    """Records embedded texts; raises a daily-quota error from the `fail_on_call`-th embed call on."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        super().__init__()
        self.fail_on_call = fail_on_call
        self.embedded: list[str] = []

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        n_calls = self.count("embed") + 1
        if self.fail_on_call is not None and n_calls >= self.fail_on_call:
            self.calls.append(("embed", ModelRole.EMBED, 0))
            raise UpstreamRateLimited("daily quota (simulated)", scope="day", retry_after_s=None)
        vectors = await super().embed(texts, dim=dim)
        self.embedded.extend(texts)
        return vectors


def _doc(i: int) -> Document:
    words = [_WORDS[(i * 7 + j) % len(_WORDS)] for j in range(60)]
    text = " ".join(words).capitalize() + "."
    return Document(
        doc_id=f"{_SOURCE}:t{i}",
        source_id=_SOURCE,
        url=HttpUrl(f"https://example.gov/t{i}"),
        title=f"Topic {i}",
        language=Language.EN,
        content_type=ContentType.CONDITION,
        trust_tier=1,
        reuse_mode=ReuseMode.PARAPHRASE_OK,
        license_id="public-domain-us-gov",
        attribution="Source: Example Health Agency",
        retrieved_at=datetime(2026, 11, 15, tzinfo=UTC),
        sections=(Section(section_id="s1", heading_path=(f"Topic {i}",), text=text),),
    ).with_checksum()


def _write_inputs(root: Path, n_docs: int) -> Path:
    ready = root / "normalized" / "_ready"
    ready.mkdir(parents=True, exist_ok=True)
    lines = [_doc(i).model_dump_json() for i in range(n_docs)]
    (root / "normalized" / f"{_SOURCE}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ready / f"{_SOURCE}.json").write_text("{}", encoding="utf-8")
    licence = {
        "id": "public-domain-us-gov",
        "name": "Public domain",
        "evidence_url": "https://example.gov/terms",
        "commercial_use": "yes",
        "verified_on": "2026-11-15",
        "verified_by": "resume_check",
    }
    entry = {
        "id": _SOURCE,
        "name": "Resume check",
        "publisher": "Example Health Agency",
        "homepage": "https://example.gov/",
        "status": "active",
        "wave": 1,
        "trust_tier": 1,
        "reuse_mode": "paraphrase_ok",
        "languages": ["en"],
        "content_types": ["condition"],
        "license": licence,
    }
    registry = root / "registry.yaml"
    registry.write_text(yaml.safe_dump({"sources": [entry]}), encoding="utf-8")
    return registry


async def _run(root: Path, registry: Path, sparse: SparseEncoder, llm: CountingLLM, batch: int) -> None:
    client = AsyncQdrantClient(location=":memory:")
    try:
        with warnings.catch_warnings(), EmbeddingCache(root / "emb.sqlite3") as cache:
            warnings.filterwarnings("ignore", message="Payload indexes have no effect", category=UserWarning)
            builder = IndexBuilder(
                paths=DataPaths(root),
                registry=load_registry(registry),
                client=client,
                # quota_limited: the simulated stop is a Gemini daily-quota 429 (a local build stops on a
                # kill instead; both resume from the same per-batch cache commits)
                embedder=DocumentEmbedder(
                    llm, cache, model_id="resume-check", batch_size=batch, quota_limited=True
                ),
                sparse=sparse,
                secret="resume-check-secret",  # noqa: S106 - throwaway key for a throwaway manifest
                alias="resume_check_alias",
            )
            await builder.build(BuildRequest("resume-check", (_SOURCE,), batch_size=batch))
    finally:
        await client.close()


async def measure_resume(
    sparse_dir: Path, *, n_docs: int = 12, batch: int = 3, fail_on_call: int = 3
) -> ResumeCheck:
    sparse = SparseEncoder(sparse_dir)
    with tempfile.TemporaryDirectory(prefix="rag-resume-") as tmp:
        root = Path(tmp)
        registry = _write_inputs(root, n_docs)
        first = CountingLLM(fail_on_call=fail_on_call)
        with contextlib.suppress(EmbeddingQuotaExhausted):  # expected: the simulated quota stops run 1
            await _run(root, registry, sparse, first, batch)
        second = CountingLLM()
        await _run(root, registry, sparse, second, batch)
    repeats = len(set(first.embedded) & set(second.embedded)) + (
        len(second.embedded) - len(set(second.embedded))
    )
    total = len(set(first.embedded) | set(second.embedded))
    return ResumeCheck(total, len(first.embedded), len(second.embedded), repeats)
