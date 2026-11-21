# syntax=docker/dockerfile:1.7
# Ausculta on a free Hugging Face Space (Docker SDK, "CPU basic": 2 vCPU, 16 GB RAM, no card, no expiry).
# The whole stack runs in this one container, managed by supervisord:
#   Caddy :7860 (the Space port) -> Next.js web (127.0.0.1:3000) and the FastAPI API (127.0.0.1:8000),
#   with Qdrant, Redis and PostgreSQL on localhost only. The signed corpus is downloaded from a public
#   Hugging Face dataset on first start (deploy/hf-space/restore_corpus.py).
# Build context = a tree with the repo layout (the Space repo is staged by deploy/hf-space/publish.py):
#   docker build -f deploy/hf-space/Dockerfile -t ausculta-space .

FROM python:3.11-slim-bookworm AS deps
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir uv==0.13.8
COPY deploy/requirements.lock /tmp/requirements.lock
RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python --no-cache --require-hashes -r /tmp/requirements.lock \
 && uv pip install --python /opt/venv/bin/python --no-cache supervisor==4.2.5

# Embedding model (~1.2 GB) and BM25 analysers, baked so the API starts without downloading them.
FROM python:3.11-slim-bookworm AS models
COPY --from=deps /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/build PYTHONDONTWRITEBYTECODE=1 HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /build
COPY core ./core
COPY app/__init__.py ./app/__init__.py
COPY app/llm ./app/llm
COPY rag/__init__.py rag/paths.py rag/sparse.py ./rag/
COPY deploy/prefetch_models.py ./deploy/prefetch_models.py
RUN HF_HOME=/tmp/hf-home AUSCULTA_ENV=dev AUSCULTA_EMBED_BACKEND=local AUSCULTA_DATA_ROOT=/home/user/data \
    python deploy/prefetch_models.py && rm -rf /tmp/hf-home

# Next.js standalone build (glibc, like the runtime image). /api is routed by Caddy before Next.js.
FROM node:24-bookworm-slim AS web
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-15 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 user
COPY --from=node:24-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=caddy:2.10 /usr/bin/caddy /usr/local/bin/caddy
COPY --from=qdrant/qdrant:v1.20.1 /qdrant/qdrant /usr/local/bin/qdrant
COPY --from=qdrant/qdrant:v1.20.1 --chown=1000:1000 /qdrant/config /home/user/qdrant/config
COPY --from=redis:8-bookworm /usr/local/bin/redis-server /usr/local/bin/redis-server
COPY --from=deps /opt/venv /opt/venv
COPY --from=models --chown=1000:1000 /home/user/data /home/user/data

ENV PATH=/opt/venv/bin:/usr/lib/postgresql/15/bin:$PATH PYTHONPATH=/home/user/app PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 HOME=/home/user \
    AUSCULTA_ENV=prod AUSCULTA_DEMO_MODE=true AUSCULTA_DATA_ROOT=/home/user/data \
    AUSCULTA_EMBED_BACKEND=local AUSCULTA_TRUSTED_PROXY_COUNT=2 WEB_CONCURRENCY=1 \
    QDRANT_URL=http://127.0.0.1:6333 HF_HOME=/home/user/data/.hf-home HF_HUB_DISABLE_TELEMETRY=1 \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /home/user/app
COPY --chown=1000:1000 core ./core
COPY --chown=1000:1000 app ./app
COPY --chown=1000:1000 rag ./rag
COPY --chown=1000:1000 config ./config
COPY --chown=1000:1000 evals/__init__.py ./evals/__init__.py
COPY --chown=1000:1000 evals/fakes ./evals/fakes
COPY --chown=1000:1000 data_pipeline/__init__.py data_pipeline/drug_synonyms.yaml ./data_pipeline/
COPY --chown=1000:1000 data_pipeline/sources/registry.yaml ./data_pipeline/sources/registry.yaml
COPY --chown=1000:1000 deploy/hf-space ./deploy/hf-space
COPY --from=web --chown=1000:1000 /web/.next/standalone /home/user/web
COPY --from=web --chown=1000:1000 /web/.next/static /home/user/web/.next/static
COPY --from=web --chown=1000:1000 /web/public /home/user/web/public

USER 1000
EXPOSE 7860
CMD ["sh", "/home/user/app/deploy/hf-space/start.sh"]
