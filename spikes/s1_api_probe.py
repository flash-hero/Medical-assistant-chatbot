"""Spike S1: probe the real Gemini API with synthetic prompts only.

Measures: which generation models answer on this key, streaming chunk shape, thinking config,
Decisions API shape and latency, embedding shape/dims/normalisation, and 429 bodies.
Run: .venv/Scripts/python.exe -m spikes.s1_api_probe  (prints a JSON report)
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
KEY = os.environ["GEMINI_API_KEY"]

GEN_MODELS = [
    "gemini-4-hydrogen",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-4-argon",
    "gemini-4-carbon",
]
REPORT: dict[str, object] = {}


def short_err(e: BaseException) -> dict[str, object]:
    out: dict[str, object] = {"type": type(e).__name__, "msg": str(e)[:600]}
    for attr in ("code", "status", "details"):
        if hasattr(e, attr):
            val = getattr(e, attr)
            out[attr] = val if isinstance(val, (int, str)) else str(val)[:600]
    return out


async def probe_generate(client: genai.Client, model: str) -> dict[str, object]:
    t0 = time.perf_counter()
    try:
        resp = await client.aio.models.generate_content(
            model=model,
            contents="In one short sentence: what does the liver do? (synthetic test)",
            config=types.GenerateContentConfig(
                max_output_tokens=200,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        um = resp.usage_metadata
        return {
            "ok": True,
            "ms": round((time.perf_counter() - t0) * 1000),
            "text": (resp.text or "")[:160],
            "finish": str(resp.candidates[0].finish_reason) if resp.candidates else None,
            "usage": {
                "prompt": um.prompt_token_count,
                "out": um.candidates_token_count,
                "thoughts": um.thoughts_token_count,
            }
            if um
            else None,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "ms": round((time.perf_counter() - t0) * 1000), "err": short_err(e)}


async def probe_stream(client: genai.Client, model: str) -> dict[str, object]:
    t0 = time.perf_counter()
    first = None
    chunks = []
    try:
        stream = await client.aio.models.generate_content_stream(
            model=model,
            contents="List three healthy habits, one line each. (synthetic test)",
            config=types.GenerateContentConfig(
                max_output_tokens=300,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
                system_instruction="You are a concise assistant.",
            ),
        )
        async for ch in stream:
            if first is None:
                first = round((time.perf_counter() - t0) * 1000)
            cand = ch.candidates[0] if ch.candidates else None
            chunks.append(
                {
                    "text": (ch.text or "")[:60],
                    "finish": str(cand.finish_reason) if cand and cand.finish_reason else None,
                    "pf": str(ch.prompt_feedback) if ch.prompt_feedback else None,
                }
            )
        return {
            "ok": True,
            "ttft_ms": first,
            "total_ms": round((time.perf_counter() - t0) * 1000),
            "n_chunks": len(chunks),
            "chunks": chunks[:8],
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "err": short_err(e)}


async def probe_decisions(client: genai.Client) -> dict[str, object]:
    t0 = time.perf_counter()
    try:
        res = await client.aio.decisions.create(
            model="gemini-decision-1",
            input="User message: 'I have crushing chest pain spreading to my left arm and I am sweating.'",
            questions={
                "emergency": {
                    "type": "noul",
                    "instructions": "Does the user describe a possible medical emergency right now?",
                },
                "intent": {
                    "type": "choice",
                    "instructions": "What is the user's main intent?",
                    "criteria": {
                        "medical_info": "Wants general health information",
                        "emergency": "Describes an acute emergency",
                        "hospital_admin": "Asks about hospital logistics",
                        "other": "Anything else",
                    },
                },
                "relevance": {
                    "type": "score",
                    "instructions": "How relevant is the message to cardiology? 0=none, 3=highly",
                    "criteria": {"levels": ["0", "1", "2", "3"]},
                },
            },
        )
        dumped = res.model_dump(mode="json", exclude_none=True)
        return {"ok": True, "ms": round((time.perf_counter() - t0) * 1000), "resp": dumped}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "ms": round((time.perf_counter() - t0) * 1000), "err": short_err(e)}


async def probe_embed(client: genai.Client) -> dict[str, object]:
    out: dict[str, object] = {}
    texts = [
        "task: search result | query: what are symptoms of type 2 diabetes",
        "title: Diabetes | text: Type 2 diabetes is a condition in which blood sugar is too high.",
        "task: search result | query: quels sont les symptômes du diabète de type 2",
        "task: search result | query: ما هي أعراض مرض السكري من النوع الثاني",
    ]
    for dim in (768, 1536, 3072):
        t0 = time.perf_counter()
        try:
            res = await client.aio.models.embed_content(
                model="gemini-embedding-2",
                contents=[types.Content(parts=[types.Part(text=t)]) for t in texts],
                config=types.EmbedContentConfig(output_dimensionality=dim),
            )
            vecs = [e.values for e in (res.embeddings or [])]
            norms = [round(math.sqrt(sum(v * v for v in vec)), 4) for vec in vecs]

            def cos(a: list[float], b: list[float]) -> float:
                return sum(x * y for x, y in zip(a, b, strict=True)) / (
                    math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
                )

            sims = (
                {
                    "q_en__doc": round(cos(vecs[0], vecs[1]), 4),
                    "q_fr__doc": round(cos(vecs[2], vecs[1]), 4),
                    "q_ar__doc": round(cos(vecs[3], vecs[1]), 4),
                }
                if len(vecs) == 4
                else None
            )
            out[str(dim)] = {
                "ok": True,
                "ms": round((time.perf_counter() - t0) * 1000),
                "n": len(vecs),
                "dims": [len(v) for v in vecs],
                "norms": norms,
                "sims": sims,
                "vec_head": vecs[0][:3] if vecs else None,
            }
        except Exception as e:  # noqa: BLE001
            out[str(dim)] = {"ok": False, "err": short_err(e)}
    # list of plain strings: aggregated or one per text?
    try:
        res = await client.aio.models.embed_content(
            model="gemini-embedding-2", contents=texts[:3], config=types.EmbedContentConfig(output_dimensionality=768)
        )
        out["plain_strings_n_vectors"] = len(res.embeddings or [])
    except Exception as e:  # noqa: BLE001
        out["plain_strings"] = {"ok": False, "err": short_err(e)}
    return out


async def main() -> None:
    client = genai.Client(
        api_key=KEY,
        http_options=types.HttpOptions(
            api_version="v1beta", timeout=60_000, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    REPORT["sdk"] = genai.__version__ if hasattr(genai, "__version__") else "?"
    REPORT["generate"] = {m: await probe_generate(client, m) for m in GEN_MODELS}
    ok_models = [m for m, r in REPORT["generate"].items() if r.get("ok")]  # type: ignore[union-attr]
    REPORT["stream"] = await probe_stream(client, ok_models[0]) if ok_models else "no model available"
    REPORT["decisions"] = await probe_decisions(client)
    REPORT["embed"] = await probe_embed(client)
    print(json.dumps(REPORT, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
