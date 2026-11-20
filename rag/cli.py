"""Command line: python -m rag {build,gold,eval,promote,status}.

Exit codes: 0 ok, 1 error, 3 embedding quota exhausted (resume later), 4 retrieval gate failed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import replace

import structlog
from qdrant_client import AsyncQdrantClient

from core.config import Settings, get_settings
from core.errors import AusculaError, UpstreamError
from core.ports import LLMProvider
from rag.build import BuildRequest, IndexBuilder
from rag.cli_eval import Handler
from rag.embed_cache import EmbeddingCache
from rag.embedding import EmbeddingBackend, embedding_backend
from rag.errors import EmbeddingQuotaExhausted, GateFailed
from rag.offline import CacheOnlyLLM
from rag.paths import DataPaths
from rag.registry import load_registry
from rag.sparse import SparseEncoder

EXIT_OK, EXIT_ERROR, EXIT_QUOTA, EXIT_GATE = 0, 1, 3, 4
log = structlog.get_logger(__name__)


def out(text: str = "") -> None:
    """CLI output goes to stdout; structured logs go to stderr."""
    sys.stdout.write(f"{text}\n")
    sys.stdout.flush()


class _CurrentStderr:
    """Writes to whatever `sys.stderr` is at call time. Binding the stream object itself would keep a
    reference to a stream that may later be replaced and closed (pytest capture, redirection), and every
    later log call would then fail with "I/O operation on closed file"."""

    def write(self, text: str) -> int:
        return sys.stderr.write(text)

    def flush(self) -> None:
        sys.stderr.flush()


def configure_logging() -> None:
    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=_CurrentStderr()),  # type: ignore[arg-type]
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )


def qdrant_client(settings: Settings, *, timeout: int = 60) -> AsyncQdrantClient:
    key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=key, timeout=timeout)


def llm_provider(settings: Settings) -> LLMProvider:
    from app.llm.factory import build_llm_provider

    return build_llm_provider(settings)


async def close_llm(llm: LLMProvider) -> None:
    closer = getattr(llm, "aclose", None)
    if closer is not None:
        await closer()


def embedding_for(
    settings: Settings, *, llm: LLMProvider | None = None, cache_only: bool = False
) -> EmbeddingBackend:
    """The deployment's embedding backend (AUSCULTA_EMBED_BACKEND, default local EmbeddingGemma). With
    `cache_only` its provider refuses every call like a spent quota, so only cached vectors are used."""
    if cache_only:
        return replace(embedding_backend(settings, provider=CacheOnlyLLM()), quota_limited=True)
    return embedding_backend(settings, llm=llm)


# ---- build -------------------------------------------------------------------------------------------
async def cmd_build(args: argparse.Namespace, settings: Settings) -> int:
    if settings.session_secret is None:
        out("AUSCULTA_SESSION_SECRET is not set: the corpus manifest cannot be signed.")
        return EXIT_ERROR
    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    only_docs = tuple(tuple(spec.split("=", 1)) for spec in args.only_docs or ())
    req = BuildRequest(
        args.corpus_version,
        sources,
        limit=args.limit,
        batch_size=args.batch_size,
        only_docs=only_docs,
    )
    paths = DataPaths.from_settings(settings)
    embedding = embedding_for(settings, cache_only=args.cache_only)
    out(f"Embedding model: {embedding.model_id} ({embedding.name} backend)")
    client = qdrant_client(settings)
    try:
        with EmbeddingCache(paths.embed_cache_db) as cache:
            builder = IndexBuilder(
                paths=paths,
                registry=load_registry(),
                client=client,
                embedder=embedding.document_embedder(cache, batch_size=args.batch_size),
                sparse=SparseEncoder(paths.fastembed_dir),
                secret=settings.session_secret.get_secret_value(),
                alias=settings.qdrant_alias,
                dim=embedding.dim,
            )
            report = await builder.build(req)
    except EmbeddingQuotaExhausted as exc:
        if args.cache_only:
            out(f"Cache-only build stopped: {exc.remaining} chunk(s) not in the cache (0 API calls made).")
        else:
            out(f"Embedding quota exhausted ({exc.scope}); progress is saved in {paths.embed_cache_db}.")
        out(f"Resume later with (repeats zero embeddings):\n  {req.resume_command()}")
        return EXIT_QUOTA
    except UpstreamError as exc:  # local inference failed (no quota involved): progress is cached too
        out(f"Embedding failed [{exc.code}]: {exc}; progress is saved in {paths.embed_cache_db}.")
        out(f"Re-run (repeats zero embeddings):\n  {req.resume_command()}")
        log.error("command_failed", command="build", code=exc.code, error=str(exc))
        return EXIT_ERROR
    finally:
        await client.close()
        await embedding.aclose()
    out(f"Indexed {report.chunks} chunks from {report.documents} documents into {report.collection}")
    skipped = {source: dict(reasons) for source, reasons in report.skipped.items()}
    out(f"  per source: {dict(report.per_source_chunks)}  skipped: {skipped}")
    out(f"  embedded {report.embedded} (embedding calls {report.api_calls}), cache hits {report.cache_hits}")
    out(f"  manifest: {report.manifest_path}  elapsed {report.elapsed_s:.0f}s")
    out(f"Next: python -m rag eval --collection {report.collection}")
    return EXIT_OK


# ---- dispatch ----------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rag", description="Ausculta retrieval index tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="chunk, embed and index sources into a new collection")
    b.add_argument("--corpus-version", required=True)
    b.add_argument("--sources", required=True, help="comma-separated source ids (must be ACTIVE)")
    b.add_argument("--limit", type=int, default=None, help="max documents per source")
    b.add_argument(
        "--only-docs",
        action="append",
        metavar="SOURCE=FILE",
        help="index only the doc ids listed in FILE (one per line) for SOURCE; repeatable",
    )
    b.add_argument("--batch-size", type=int, default=90)
    b.add_argument(
        "--cache-only", action="store_true", help="never call the embedding API; stop at the first cache miss"
    )
    from rag.cli_eval import add_eval_parsers
    from rag.cli_plan import add_plan_parser

    add_plan_parser(sub)
    add_eval_parsers(sub)
    return parser


def _handlers() -> dict[str, Handler]:
    from rag.cli_eval import EVAL_HANDLERS
    from rag.cli_plan import cmd_plan

    return {"build": cmd_build, "plan": cmd_plan, **EVAL_HANDLERS}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configure_logging()
    settings = get_settings()
    try:
        return asyncio.run(_handlers()[args.cmd](args, settings))
    except GateFailed as exc:
        out(f"Gate failed: {exc}")
        return EXIT_GATE
    except AusculaError as exc:
        out(f"Error [{exc.code}]: {exc}")
        # also on stderr: a run logged with `2> file` (stderr only) must still show why it exited 1
        log.error("command_failed", command=args.cmd, code=exc.code, error=str(exc))
        return EXIT_ERROR
