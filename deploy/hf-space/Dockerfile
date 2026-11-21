# syntax=docker/dockerfile:1.7
# Ausculta on a free Hugging Face Space (Docker SDK, "CPU basic": 2 vCPU, 16 GB RAM, no card, no expiry).
# The whole stack runs in this one container, managed by supervisord:
#   Caddy :7860 (the Space port) -> Next.js web (127.0.0.1:3000) and the FastAPI API (127.0.0.1:8000),
#   with Qdrant, Redis and PostgreSQL on localhost only. The signed corpus is downloaded on first start
#   (deploy/hf-space/restore_corpus.py).
# Source: SRC=git (the default, used by the Space) clones the public GitHub repository at REF, so the Space repo
# only holds this Dockerfile and its README. SRC=context builds the local tree instead:
#   docker build -f deploy/hf-space/Dockerfile --build-arg SRC=context -t ausculta-space .
ARG SRC=git
ARG REPO=https://github.com/flash-hero/Medical-assistant-chatbot.git
ARG REF=main

FROM buildpack-deps:bookworm-scm AS src-git
ARG REPO
ARG REF
RUN git clone --quiet --filter=blob:none --no-checkout "$REPO" /src && git -C /src checkout --quiet "$REF"

FROM scratch AS src-context
COPY . /src

FROM src-${SRC} AS src

FROM python:3.11-slim-bookworm AS deps
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir uv==0.13.8
COPY --from=src /src/deploy/requirements.lock /tmp/requirements.lock
RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python --no-cache --require-hashes -r /tmp/requirements.lock

# Process manager (supervisor imports pkg_resources, which ships with setuptools). Separate from `deps` so the
# model stage below, which copies `deps`, stays cached when this changes.
FROM deps AS tools
RUN uv pip install --python /opt/venv/bin/python --no-cache supervisor==4.2.5 setuptools==75.8.0

# Embedding model (~1.2 GB) and BM25 analysers, baked so the API starts without downloading them.
FROM python:3.11-slim-bookworm AS models
COPY --from=deps /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/build PYTHONDONTWRITEBYTECODE=1 HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /build
COPY --from=src /src/core ./core
COPY --from=src /src/app/__init__.py ./app/__init__.py
COPY --from=src /src/app/llm ./app/llm
COPY --from=src /src/rag/__init__.py /src/rag/paths.py /src/rag/sparse.py ./rag/
COPY --from=src /src/deploy/prefetch_models.py ./deploy/prefetch_models.py
RUN HF_HOME=/tmp/hf-home AUSCULTA_ENV=dev AUSCULTA_EMBED_BACKEND=local AUSCULTA_DATA_ROOT=/home/user/data \
    python deploy/prefetch_models.py && rm -rf /tmp/hf-home

# Next.js standalone build (glibc, like the runtime image). /api is routed by Caddy before Next.js.
FROM node:24-bookworm-slim AS web
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=src /src/web/package.json /src/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=src /src/web ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-15 ca-certificates libunwind8 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 user
COPY --from=node:24-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=caddy:2.10 /usr/bin/caddy /usr/local/bin/caddy
COPY --from=qdrant/qdrant:v1.20.1 /qdrant/qdrant /usr/local/bin/qdrant
COPY --from=qdrant/qdrant:v1.20.1 --chown=1000:1000 /qdrant/config /home/user/qdrant/config
COPY --from=redis:8-bookworm /usr/local/bin/redis-server /usr/local/bin/redis-server
COPY --from=tools /opt/venv /opt/venv
COPY --from=models --chown=1000:1000 /home/user/data /home/user/data

ENV PATH=/opt/venv/bin:/usr/lib/postgresql/15/bin:$PATH PYTHONPATH=/home/user/app PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 HOME=/home/user \
    AUSCULTA_ENV=prod AUSCULTA_DEMO_MODE=true AUSCULTA_DATA_ROOT=/home/user/data \
    AUSCULTA_EMBED_BACKEND=local AUSCULTA_TRUSTED_PROXY_COUNT=2 WEB_CONCURRENCY=1 \
    QDRANT_URL=http://127.0.0.1:6333 HF_HOME=/home/user/data/.hf-home HF_HUB_DISABLE_TELEMETRY=1 \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /home/user/app
COPY --from=src --chown=1000:1000 /src/core ./core
COPY --from=src --chown=1000:1000 /src/app ./app
COPY --from=src --chown=1000:1000 /src/rag ./rag
COPY --from=src --chown=1000:1000 /src/config ./config
COPY --from=src --chown=1000:1000 /src/evals/__init__.py ./evals/__init__.py
COPY --from=src --chown=1000:1000 /src/evals/fakes ./evals/fakes
COPY --from=src --chown=1000:1000 /src/data_pipeline/__init__.py /src/data_pipeline/drug_synonyms.yaml ./data_pipeline/
COPY --from=src --chown=1000:1000 /src/data_pipeline/sources/registry.yaml ./data_pipeline/sources/registry.yaml
COPY --from=src --chown=1000:1000 /src/deploy/hf-space ./deploy/hf-space
COPY --from=web --chown=1000:1000 /web/.next/standalone /home/user/web
COPY --from=web --chown=1000:1000 /web/.next/static /home/user/web/.next/static
COPY --from=web --chown=1000:1000 /web/public /home/user/web/public

USER 1000
EXPOSE 7860
CMD ["sh", "/home/user/app/deploy/hf-space/start.sh"]
