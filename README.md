# Ausculta

Sourced health information and hospital front-desk assistant, in English, French and Arabic.
Retrieval-augmented generation over a licence-checked public-health corpus, on the Gemini API.

> **Demo mode.** Not for use with real patients until the pilot gate in
> [docs/intended-purpose.md](docs/intended-purpose.md) is signed.

**Live demo:** https://flash-hero--ausculta-web.us-east.modal.run ([`/en`](https://flash-hero--ausculta-web.us-east.modal.run/en),
[`/fr`](https://flash-hero--ausculta-web.us-east.modal.run/fr), [`/ar`](https://flash-hero--ausculta-web.us-east.modal.run/ar)).
Free hosting on Modal with scale-to-zero: the first visit after a few idle minutes takes about 35 s.
Created by **Oussama Tabakh**, AI and data science engineer. Project documents:
[summary (EN, 2 pages)](docs/deliverables/ausculta-project-summary.pdf) and
[full explanation (Darija, 59 pages)](docs/deliverables/ausculta-explication-darija.pdf).

## Layout

| Path | What |
|---|---|
| `core/` | Shared contracts: settings, pinned model IDs, schemas, ports, errors |
| `data_pipeline/` | Source registry, fetchers, parsers, normalisation, quality gates |
| `rag/` | Chunking, embeddings, Qdrant index, hybrid retrieval, rerank |
| `app/` | FastAPI service: turn pipeline, guardrails, LLM wrapper, hospital profile, storage, limits |
| `evals/` | Gold sets, safety and red-team suites, load tests, release gates, fake Gemini server |
| `web/` | Next.js landing page and chat UI |
| `deploy/` | Dockerfiles, compose, Caddy |
| `docs/` | Intended purpose, decision records, runbook, attribution |

Bulk data lives outside the repo in `C:\dev\ausculta-data` (`AUSCULTA_DATA_ROOT`).

## Dev setup (Windows)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install uv
.venv\Scripts\uv pip install --python .venv\Scripts\python.exe -e ".[dev,load,data]"
git config core.hooksPath .githooks
copy .env.example .env   # then fill GEMINI_API_KEY and AUSCULTA_SESSION_SECRET
```

Services: `docker compose -f deploy/compose.dev.yaml up -d` (Qdrant, Postgres, Redis).
Without Docker, run the native Qdrant binary: `scripts/dev/qdrant.sh`.

## Tests

```powershell
.venv\Scripts\python -m pytest                 # unit + contract (no network)
.venv\Scripts\python -m pytest -m live         # small real-API checks (needs GEMINI_API_KEY)
.venv\Scripts\python -m evals.run --gates evals/gates.yaml
```
