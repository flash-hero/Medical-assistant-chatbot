"""Synthetic test helpers for the RAG track (no network, no real corpus)."""

from __future__ import annotations

import socket
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from core.schemas.document import Document, Section

FIXED_TIME = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

TOPICS: dict[str, dict[str, str]] = {
    "asthma": {
        "summary": "Asthma is a chronic disease of the airways in the lungs. The airways become inflamed "
        "and narrow, which makes breathing hard. Common triggers include pollen, smoke and cold air.",
        "symptoms": "Symptoms of asthma include:\n- wheezing\n- coughing at night\n- chest tightness\n"
        "- shortness of breath",
        "care": "Call your doctor if an inhaler does not relieve wheezing. Seek emergency care when lips "
        "turn blue or speaking is difficult.",
    },
    "diabetes": {
        "summary": "Diabetes is a disease in which blood glucose levels are too high. Insulin is a hormone "
        "made by the pancreas that helps glucose enter cells. Type 2 diabetes is the most common form.",
        "symptoms": "Symptoms of diabetes include increased thirst, frequent urination, blurred vision and "
        "slow healing sores. Some people have no symptoms for years.",
        "care": "An A1C test measures average blood glucose over three months. Talk to your doctor about "
        "screening if you are overweight.",
    },
    "migraine": {
        "summary": "A migraine is a headache with throbbing pain, usually on one side of the head. Attacks "
        "can last from four hours to three days.",
        "symptoms": "Many people see an aura before the headache, such as flashing lights or zigzag lines. "
        "Nausea and sensitivity to light are common.",
        "care": "Keeping a headache diary helps identify triggers such as missed meals, stress or "
        "poor sleep.",
    },
    "measles": {
        "summary": "Measles is a highly contagious viral infection that spreads through the air when an "
        "infected person coughs or sneezes.",
        "symptoms": "Measles starts with fever, runny nose, cough and red eyes, followed by a rash that "
        "begins on the face.",
        "care": "Two doses of the MMR vaccine protect against measles. Children usually get the first dose "
        "at 12 to 15 months of age.",
    },
}


def make_doc(
    native_id: str = "asthma",
    *,
    source_id: str = "demo_src",
    language: str = "en",
    content_type: str = "condition",
    sections: list[tuple[str, tuple[str, ...], str]] | None = None,
    reviewed_on: date | None = date(2025, 5, 1),
    title: str | None = None,
    reuse_mode: str = "paraphrase_ok",
    url: str | None = None,
) -> Document:
    topic = TOPICS.get(native_id, TOPICS["asthma"])
    name = title or native_id.replace("_", " ").title()
    secs = sections or [
        ("s1", (name, "Summary"), topic["summary"]),
        ("s2", (name, "Symptoms"), topic["symptoms"]),
        ("s3", (name, "When to see a doctor"), topic["care"]),
    ]
    return Document(
        doc_id=f"{source_id}:{native_id}",
        source_id=source_id,
        url=url or f"https://example.gov/{native_id}",
        title=name,
        language=language,
        content_type=content_type,
        trust_tier=1,
        reuse_mode=reuse_mode,
        license_id="public-domain-us-gov",
        attribution="Source: DemoPlus, Example Health Agency",
        reviewed_on=reviewed_on,
        retrieved_at=FIXED_TIME,
        sections=tuple(
            Section(section_id=sid, heading_path=hp, text=text, kind=None) for sid, hp, text in secs
        ),
    ).with_checksum()


def corpus_docs() -> list[Document]:
    return [make_doc(name) for name in TOPICS]


def source_entry(source_id: str, status: str = "active", **over: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": source_id,
        "name": "DemoPlus Topics",
        "publisher": "Example Health Agency",
        "homepage": "https://example.gov/",
        "status": status,
        "wave": 1,
        "trust_tier": 1,
        "reuse_mode": "paraphrase_ok",
        "languages": ["en", "fr", "ar"],
        "content_types": ["condition", "drug_label"],
        "license": {
            "id": "public-domain-us-gov",
            "name": "Public domain",
            "evidence_url": "https://example.gov/terms",
            "commercial_use": "yes",
            "attribution": "Source: DemoPlus, Example Health Agency",
            "verified_on": "2026-11-15",
            "verified_by": "test",
        },
        "domains": ["example.gov"],
    }
    entry.update(over)
    return entry


def write_registry(path: Path, entries: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"version": 1, "sources": entries}, allow_unicode=True), encoding="utf-8")
    return path


def qdrant_server_up(url: str = "http://127.0.0.1:6333") -> bool:
    host, port = url.removeprefix("http://").split(":")
    try:
        with socket.create_connection((host, int(port)), timeout=0.5):
            return True
    except OSError:
        return False


class SpyLLM:
    """FakeLLMProvider wrapper that records every embedded text and can fail on a chosen call.

    `fail_on_call` is 1-based over embed calls; `failure` is raised instead of embedding on that call
    (use a BaseException such as KeyboardInterrupt to simulate the process being killed mid-build)."""

    def __init__(self, *, fail_on_call: int | None = None, failure: BaseException | None = None) -> None:
        from evals.fakes.fake_llm import FakeLLMProvider

        self.inner = FakeLLMProvider()
        self.embedded: list[str] = []
        self.embed_calls = 0
        self.fail_on_call = fail_on_call
        self.failure = failure

    async def embed(self, texts, *, dim):
        self.embed_calls += 1
        if self.fail_on_call is not None and self.embed_calls >= self.fail_on_call and self.failure:
            raise self.failure
        vectors = await self.inner.embed(texts, dim=dim)
        self.embedded.extend(texts)
        return vectors

    async def generate(self, request):
        return await self.inner.generate(request)

    def stream(self, request):
        return self.inner.stream(request)

    async def decide(self, role, input_text, questions):
        return await self.inner.decide(role, input_text, questions)


def write_normalized(
    root: Path, source_id: str, docs: list[Document], extra_lines: tuple[str, ...] = ()
) -> Path:
    """Write a data-track style JSONL file plus its _ready marker under a temporary data root."""
    normalized = root / "normalized"
    (normalized / "_ready").mkdir(parents=True, exist_ok=True)
    lines = [d.model_dump_json() for d in docs] + list(extra_lines)
    path = normalized / f"{source_id}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (normalized / "_ready" / f"{source_id}.json").write_text(
        f'{{"documents": {len(docs)}}}', encoding="utf-8"
    )
    return path


QDRANT_LOCAL_WARNINGS = (
    "ignore:Payload indexes have no effect:UserWarning",
    "ignore:Local mode performs exact:UserWarning",
)
TEST_SECRET = "test-secret-0123456789abcdef"

_STONE_WORDS = [
    "kidney",
    "stones",
    "form",
    "when",
    "minerals",
    "such",
    "as",
    "calcium",
    "oxalate",
    "crystallise",
    "in",
    "concentrated",
    "urine",
    "and",
    "grow",
    "until",
    "they",
    "block",
    "the",
    "urinary",
    "tract",
    "causing",
    "severe",
    "flank",
    "pain",
    "nausea",
    "and",
    "blood",
    "in",
    "the",
    "urine",
]


def long_text(n_sentences: int, seed: int = 1) -> str:
    """Deterministic multi-chunk prose (each sentence distinct, ~20 words)."""
    import random

    rng = random.Random(seed)
    out = []
    for i in range(n_sentences):
        words = [rng.choice(_STONE_WORDS) for _ in range(18)]
        out.append(f"Sentence {i} " + " ".join(words) + ".")
    return " ".join(out)


def retrieval_docs() -> list[Document]:
    """Topic docs + a drug label (many sections) + a long single-section doc (several chunks)."""
    drug_sections = [
        (f"s{i}", ("Metformin", heading), f"Metformin {heading.lower()} information: {text}")
        for i, (heading, text) in enumerate(
            [
                (
                    "Uses",
                    "metformin lowers blood glucose in type 2 diabetes together with diet and exercise.",
                ),
                (
                    "Warnings",
                    "metformin can rarely cause lactic acidosis, a serious build up of lactic acid.",
                ),
                ("Side effects", "metformin often causes diarrhea nausea and stomach upset at the start."),
                ("Storage", "keep metformin tablets at room temperature away from moisture and heat."),
            ]
        )
    ]
    return [
        *corpus_docs(),
        make_doc("metformin", content_type="drug_label", sections=drug_sections, title="Metformin"),
        make_doc("kidney_stones", sections=[("s1", ("Kidney Stones", "Overview"), long_text(90))]),
    ]


async def build_index(tmp_path: Path, registry_path: Path, client, docs, version: str = "t1") -> str:
    """Index `docs` (source demo_src) into local-mode Qdrant with fake embeddings; returns the collection."""
    from core.config import Settings
    from rag.build import BuildRequest, IndexBuilder
    from rag.embed_cache import EmbeddingCache
    from rag.embedding import DocumentEmbedder
    from rag.paths import DataPaths
    from rag.registry import load_registry
    from rag.sparse import SparseEncoder

    root = tmp_path / "data"
    write_normalized(root, "demo_src", list(docs))
    sparse = SparseEncoder(DataPaths.from_settings(Settings()).fastembed_dir)
    with EmbeddingCache(tmp_path / "emb.sqlite3") as cache:
        builder = IndexBuilder(
            paths=DataPaths(root),
            registry=load_registry(registry_path),
            client=client,
            embedder=DocumentEmbedder(SpyLLM(), cache, model_id="test-embed"),
            sparse=sparse,
            secret=TEST_SECRET,
            alias="test_alias",
        )
        report = await builder.build(BuildRequest(version, ("demo_src",)))
    return report.collection
