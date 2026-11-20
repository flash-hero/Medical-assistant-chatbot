# syntax=docker/dockerfile:1.7
# Ausculta API (FastAPI). Build from the repo root:  docker build -f deploy/api.Dockerfile -t ausculta-api .
#
# The app runs from the source tree (/srv, same layout as the repo) so every path it resolves relative to the repo
# (config/, data_pipeline/sources/registry.yaml, data_pipeline/drug_synonyms.yaml) exists in the image. Only the
# third-party dependencies are installed into the venv, from the hash-pinned lockfile.

FROM python:3.11-slim-bookworm AS deps
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir uv==0.13.8
COPY deploy/requirements.lock /tmp/requirements.lock
# Regenerate: uv pip compile pyproject.toml --python-version 3.11 --python-platform x86_64-unknown-linux-gnu
#   --generate-hashes -o deploy/requirements.lock
RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python --no-cache --require-hashes -r /tmp/requirements.lock

# Bake the embedding model (~1.2 GB) and BM25 analysers into /data so the API starts without internet access.
# Own stage with only the modules the download script imports: config, template and pipeline changes do not
# re-download the model. AUSCULTA_ENV=dev only here (the production settings guard needs Redis/Postgres).
FROM python:3.11-slim-bookworm AS models
COPY --from=deps /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/build PYTHONDONTWRITEBYTECODE=1 HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /build
COPY core ./core
COPY app/__init__.py ./app/__init__.py
COPY app/llm ./app/llm
COPY rag/__init__.py rag/paths.py rag/sparse.py ./rag/
COPY deploy/prefetch_models.py ./deploy/prefetch_models.py
RUN HF_HOME=/tmp/hf-home AUSCULTA_ENV=dev AUSCULTA_EMBED_BACKEND=local AUSCULTA_DATA_ROOT=/data \
    python deploy/prefetch_models.py && rm -rf /tmp/hf-home

FROM python:3.11-slim-bookworm AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/srv PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    AUSCULTA_ENV=prod AUSCULTA_DATA_ROOT=/data \
    HF_HOME=/data/.hf-home HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /nonexistent app \
    && mkdir -p /data && chown app:app /data
COPY --from=deps /opt/venv /opt/venv
WORKDIR /srv
COPY --chown=app:app core ./core
COPY --chown=app:app app ./app
COPY --chown=app:app rag ./rag
COPY --chown=app:app config ./config
COPY --chown=app:app evals/__init__.py ./evals/__init__.py
COPY --chown=app:app evals/fakes ./evals/fakes
COPY --chown=app:app data_pipeline/__init__.py data_pipeline/drug_synonyms.yaml ./data_pipeline/
COPY --chown=app:app data_pipeline/sources/registry.yaml ./data_pipeline/sources/registry.yaml
# Docker copies /data into the api_data volume on first use.
COPY --from=models --chown=app:app /data /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"
# One worker per container by default (each holds the embedding model); state is shared through Redis.
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-1} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 20"]
