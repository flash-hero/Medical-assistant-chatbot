"""Real LLMProvider on the Gemini Developer API (google-genai 3.3.0, v1beta, generateContent + Decisions).

Guarantees:
  - model IDs come only from core.models; paid-only models are refused on the free tier
  - SDK retries disabled; one RetryPolicy (app/llm/retry.py); streams retry only before the first chunk
  - explicit safety settings; provider blocks raise UpstreamBlocked (a RISK SIGNAL for the engine)
  - store=False on every generation; nothing is persisted upstream by us
  - cancelling a stream consumer closes the upstream HTTP stream (finally: aclose)
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from typing import Any, TypeVar, cast

from google import genai
from google.genai import types

from app.llm.errors import BLOCK_FINISH, map_exception
from app.llm.retry import RetryPolicy, with_retry
from app.llm.throttle import TokenBucket
from core.config import Settings
from core.errors import UpstreamBadRequest, UpstreamBlocked, UpstreamError
from core.models import EMBED_MAX_BATCH, ModelRole, ModelSpec, model_for
from core.ports import (
    DecisionAnswer,
    DecisionQuestion,
    DecisionResult,
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    SpendMeter,
)

T = TypeVar("T")
STREAM_IDLE_TIMEOUT_S = 15.0
FREE_TIER_EMBED_TEXTS_PER_MIN = 90.0  # measured quota: 100 texts/min on the free tier
_HC = types.HarmCategory
_HT = types.HarmBlockThreshold
# Medical information about doses, overdose and self-harm must reach our own guardrails instead of being
# silently dropped, so dangerous_content blocks only HIGH; harmful intent is handled by the engine's guard.
SAFETY_SETTINGS: tuple[types.SafetySetting, ...] = (
    types.SafetySetting(category=_HC.HARM_CATEGORY_HARASSMENT, threshold=_HT.BLOCK_MEDIUM_AND_ABOVE),
    types.SafetySetting(category=_HC.HARM_CATEGORY_HATE_SPEECH, threshold=_HT.BLOCK_MEDIUM_AND_ABOVE),
    types.SafetySetting(category=_HC.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=_HT.BLOCK_MEDIUM_AND_ABOVE),
    types.SafetySetting(category=_HC.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=_HT.BLOCK_ONLY_HIGH),
)


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 3.5))


def _cost(spec: ModelSpec, tokens_in: int, tokens_out: int) -> float:
    return (tokens_in * spec.usd_per_m_input + tokens_out * spec.usd_per_m_output) / 1_000_000


def _visible_text(chunk: types.GenerateContentResponse) -> str:
    if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
        return ""
    return "".join(p.text for p in chunk.candidates[0].content.parts if p.text and not p.thought)


def _finish(chunk: types.GenerateContentResponse) -> str | None:
    if chunk.candidates and chunk.candidates[0].finish_reason:
        fr = chunk.candidates[0].finish_reason
        return str(getattr(fr, "value", fr))
    return None


def _raise_if_blocked(chunk: types.GenerateContentResponse) -> None:
    pf = chunk.prompt_feedback
    if pf is not None and pf.block_reason:
        reason = str(getattr(pf.block_reason, "value", pf.block_reason)).lower()
        raise UpstreamBlocked("prompt blocked by provider", reason=reason, stage="prompt")
    finish = _finish(chunk)
    if finish in BLOCK_FINISH:
        raise UpstreamBlocked("response blocked by provider", reason=finish.lower(), stage="response")


def _question_param(q: DecisionQuestion) -> dict[str, Any]:
    param: dict[str, Any] = {"type": q.kind, "instructions": q.instructions}
    if q.kind == "choice":
        param["criteria"] = dict(q.criteria or {})  # type: ignore[arg-type]
    elif q.kind == "score":
        param["criteria"] = list(q.criteria or [])
    return param


def _answer(raw: Any) -> DecisionAnswer:
    kind = getattr(raw, "type", None)
    probs = dict(getattr(raw, "probabilities", None) or {})
    conf = float(getattr(raw, "confidence", 0.0) or 0.0)
    if kind == "noul":
        return DecisionAnswer(kind="noul", confidence=conf, noul=float(raw.noul))
    if kind == "choice":
        return DecisionAnswer(kind="choice", confidence=conf, choice=str(raw.choice), probabilities=probs)
    if kind == "score":
        return DecisionAnswer(kind="score", confidence=conf, score=float(raw.score), probabilities=probs)
    raise UpstreamError(f"unknown decision answer type {kind!r}")


class GeminiProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        spend: SpendMeter | None = None,
        policy: RetryPolicy | None = None,
        client: genai.Client | None = None,
        embed_rate_per_min: float | None = None,
    ) -> None:
        if embed_rate_per_min is None and settings.is_free_tier:
            embed_rate_per_min = FREE_TIER_EMBED_TEXTS_PER_MIN
        self._embed_bucket = TokenBucket(embed_rate_per_min) if embed_rate_per_min else None
        if client is None:
            if settings.gemini_api_key is None:
                raise UpstreamBadRequest("GEMINI_API_KEY is not configured")
            client = genai.Client(
                api_key=settings.gemini_api_key.get_secret_value(),
                http_options=types.HttpOptions(
                    api_version="v1beta", timeout=90_000, retry_options=types.HttpRetryOptions(attempts=1)
                ),
            )
        self._client = client
        self._tier = settings.gemini_tier
        self._spend = spend
        self._policy = policy or RetryPolicy()

    async def aclose(self) -> None:
        """Close pooled HTTP connections (call on app shutdown / test teardown)."""
        closer = getattr(self._client.aio, "aclose", None)
        if closer is not None:
            await closer()

    # ---- helpers -------------------------------------------------------------------------------
    def _spec(self, role: ModelRole) -> ModelSpec:
        spec = model_for(role, self._tier)
        if spec.paid_only and self._tier != "paid":
            raise UpstreamBadRequest(f"{spec.model_id} requires a paid tier")
        return spec

    def _config(self, spec: ModelSpec, request: GenerationRequest) -> types.GenerateContentConfig:
        kwargs: dict[str, Any] = {
            "system_instruction": request.system,
            "max_output_tokens": request.max_output_tokens or spec.max_output_tokens,
            "safety_settings": list(SAFETY_SETTINGS),
            "store": False,
        }
        if spec.thinking_level:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(spec.thinking_level.upper())
            )
        if request.json_schema is not None:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_json_schema"] = dict(request.json_schema)
        return types.GenerateContentConfig(**kwargs)

    async def _reserve(self, spec: ModelSpec, request: GenerationRequest) -> tuple[str | None, int]:
        tokens_in = _estimate_tokens(request.system + request.prompt)
        if self._spend is None:
            return None, tokens_in
        est = _cost(spec, tokens_in, request.max_output_tokens or spec.max_output_tokens or 1024)
        return await self._spend.reserve(est), tokens_in

    async def _settle(self, rid: str | None, spec: ModelSpec, tokens_in: int, tokens_out: int) -> None:
        if self._spend is not None and rid is not None:
            await self._spend.settle(rid, _cost(spec, tokens_in, tokens_out))

    # ---- LLMProvider ---------------------------------------------------------------------------
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        spec = self._spec(request.role)
        cfg = self._config(spec, request)
        timeout = request.timeout_s or spec.timeout_s
        rid, est_in = await self._reserve(spec, request)
        t0 = time.perf_counter()
        tokens_in, tokens_out = 0, 0  # a failed request is not billed; set from usage on success
        try:

            async def call() -> types.GenerateContentResponse:
                return await _bounded(
                    self._client.aio.models.generate_content(
                        model=spec.model_id, contents=request.prompt, config=cfg
                    ),
                    timeout,
                )

            resp = await with_retry(call, self._policy)
            _raise_if_blocked(resp)
            um = resp.usage_metadata
            tokens_in = (um.prompt_token_count if um else None) or est_in
            tokens_out = ((um.candidates_token_count or 0) + (um.thoughts_token_count or 0)) if um else 0
            return GenerationResult(
                text=_visible_text(resp),
                finish_reason=_finish(resp) or "STOP",
                model_id=spec.model_id,
                input_tokens=tokens_in,
                output_tokens=(um.candidates_token_count or 0) if um else 0,
                thinking_tokens=(um.thoughts_token_count or 0) if um else 0,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        finally:
            await asyncio.shield(self._settle(rid, spec, tokens_in, tokens_out))

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        spec = self._spec(request.role)
        cfg = self._config(spec, request)
        first_timeout = request.timeout_s or spec.timeout_s
        rid, est_in = await self._reserve(spec, request)
        usage = [0, 0]  # [tokens_in, tokens_out]: nothing is billed until the stream opens
        agen: Any = None

        async def open_and_first() -> tuple[Any, types.GenerateContentResponse | None]:
            it = await _bounded(
                self._client.aio.models.generate_content_stream(
                    model=spec.model_id, contents=request.prompt, config=cfg
                ),
                first_timeout,
            )
            agen = it.__aiter__()
            try:
                return agen, await _bounded(agen.__anext__(), first_timeout)
            except StopAsyncIteration:
                return agen, None
            except BaseException:
                await _aclose(agen)
                raise

        # The try starts right after the reservation: a failed or cancelled open must still settle
        # (review P1/S2); cleanup is shielded so a repeated cancel cannot skip settle or close (review P4).
        try:
            agen, chunk = await with_retry(open_and_first, self._policy)
            usage[0] = est_in
            while chunk is not None:
                _raise_if_blocked(chunk)
                if chunk.usage_metadata:
                    um = chunk.usage_metadata
                    usage[0] = um.prompt_token_count or usage[0]
                    usage[1] = (um.candidates_token_count or 0) + (um.thoughts_token_count or 0)
                text = _visible_text(chunk)
                finish = _finish(chunk)
                if text or finish:
                    yield GenerationChunk(text=text, finish_reason=finish)
                try:
                    chunk = await _bounded(agen.__anext__(), STREAM_IDLE_TIMEOUT_S)
                except StopAsyncIteration:
                    chunk = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    raise map_exception(exc) from exc
        finally:
            await asyncio.shield(self._cleanup(rid, spec, usage[0], usage[1], agen))

    async def _cleanup(
        self, rid: str | None, spec: ModelSpec, tokens_in: int, tokens_out: int, agen: Any
    ) -> None:
        try:
            await self._settle(rid, spec, tokens_in, tokens_out)
        finally:
            if agen is not None:
                await _aclose(agen)

    async def decide(
        self, role: ModelRole, input_text: str, questions: Mapping[str, DecisionQuestion]
    ) -> DecisionResult:
        spec = self._spec(role)
        params = {k: _question_param(q) for k, q in questions.items()}
        t0 = time.perf_counter()

        async def call() -> Any:
            return await _bounded(
                self._client.aio.decisions.create(
                    model=spec.model_id, input=input_text, questions=cast(Any, params)
                ),
                spec.timeout_s,
            )

        res = await with_retry(call, self._policy)
        pf = getattr(res, "prompt_feedback", None)
        if pf is not None and getattr(pf, "block_reason", None):
            reason = str(getattr(pf.block_reason, "value", pf.block_reason)).lower()
            raise UpstreamBlocked("decision input blocked", reason=reason, stage="prompt")
        raw = dict(res.answers or {})
        missing = set(questions) - set(raw)
        if missing:
            raise UpstreamError(f"decision response missing answers: {sorted(missing)}")
        usage = getattr(res, "usage", None)
        return DecisionResult(
            answers={k: _answer(raw[k]) for k in questions},
            model_id=spec.model_id,
            input_tokens=int(getattr(usage, "total_input_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    async def embed(self, texts: Sequence[str], *, dim: int) -> list[list[float]]:
        spec = self._spec(ModelRole.EMBED)
        cfg = types.EmbedContentConfig(output_dimensionality=dim)
        out: list[list[float]] = []
        step = EMBED_MAX_BATCH
        if self._embed_bucket is not None:
            step = min(step, int(self._embed_bucket.capacity))
        for start in range(0, len(texts), step):
            batch = list(texts[start : start + step])
            if self._embed_bucket is not None:
                await self._embed_bucket.acquire(len(batch))
            contents = [types.Content(parts=[types.Part(text=t)]) for t in batch]

            async def call(contents: list[types.Content] = contents) -> types.EmbedContentResponse:
                return await _bounded(
                    self._client.aio.models.embed_content(model=spec.model_id, contents=contents, config=cfg),
                    spec.timeout_s,
                )

            res = await with_retry(call, self._policy)
            vectors = [list(e.values or []) for e in (res.embeddings or [])]
            if len(vectors) != len(batch) or any(len(v) != dim for v in vectors):
                raise UpstreamError(f"embedding count/dim mismatch: got {len(vectors)} for {len(batch)}")
            out.extend(_unit(v) for v in vectors)
        return out


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 or abs(n - 1.0) < 1e-3 else [x / n for x in v]


async def _aclose(agen: Any) -> None:
    closer = getattr(agen, "aclose", None)
    if closer is not None:
        with contextlib.suppress(Exception):  # best-effort close of a dead stream
            await closer()


async def _bounded(awaitable: Awaitable[T], seconds: float) -> T:
    """Timeout that never swallows an outer cancellation.

    On Python 3.11, asyncio.wait_for can drop a task.cancel() when the inner awaitable completes in the same
    loop iteration, which would leave an upstream stream open after a client disconnect.
    asyncio.timeout() has no such race. Expiry raises TimeoutError (mapped to UpstreamTimeout).
    """
    async with asyncio.timeout(seconds):
        return await awaitable
