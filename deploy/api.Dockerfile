# syntax=docker/dockerfile:1.7
# Ausculta API (FastAPI). Build from the repo root:  docker build -f deploy/api.Dockerfile -t ausculta-api .
FROM python:3.11-slim-bookworm AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir uv==0.13.8
WORKDIR /src
COPY pyproject.toml README.md ./
COPY core ./core
COPY app ./app
COPY rag ./rag
COPY evals/__init__.py ./evals/__init__.py
COPY evals/fakes ./evals/fakes
COPY data_pipeline/__init__.py ./data_pipeline/__init__.py
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python --no-cache .

FROM python:3.11-slim-bookworm AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    AUSCULTA_ENV=prod AUSCULTA_DATA_ROOT=/data
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /nonexistent app \
    && mkdir -p /data && chown app:app /data
COPY --from=build /opt/venv /opt/venv
WORKDIR /srv
COPY --chown=app:app config ./config
COPY --chown=app:app data_pipeline/sources/registry.yaml ./data_pipeline/sources/registry.yaml
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"
# One worker per container by default (each holds the embedding model); state is shared through Redis.
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-1} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 20"]
