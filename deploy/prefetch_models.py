"""Download the model assets into AUSCULTA_DATA_ROOT at image build time, so the API starts offline.

Fetches the local embedding model (EmbeddingGemma, ~1.2 GB) into {data_root}/models and the BM25 analysers for
en/fr/ar into {data_root}/embed-cache/fastembed. Docker copies these into the new /data volume on first use.
Run: python deploy/prefetch_models.py
"""

from __future__ import annotations

import asyncio

from app.llm.factory import build_embedding_provider
from core.config import get_settings
from core.models import embedding_spec
from rag.paths import DataPaths
from rag.sparse import SparseEncoder


async def main() -> None:
    settings = get_settings()
    spec = embedding_spec(settings.embed_backend)
    provider = build_embedding_provider(settings)
    warmup = getattr(provider, "warmup", None)
    if warmup is not None:
        await warmup()
        vectors = await provider.embed(["task: search result | query: prefetch check"], dim=spec.dim)
        if len(vectors) != 1 or len(vectors[0]) != spec.dim:
            raise RuntimeError(f"embedding check failed: expected 1 vector of {spec.dim} dims")
    SparseEncoder(DataPaths.from_settings(settings).fastembed_dir).warmup(("en", "fr", "ar"))
    print(f"prefetched {spec.model_id} and BM25 en/fr/ar into {settings.data_root}")


if __name__ == "__main__":
    asyncio.run(main())
