#!/bin/sh
# Wait for PostgreSQL, Redis and Qdrant, apply the schema, make the signed corpus live (first boot), then run
# the API. Emergency, crisis and front-desk turns work as soon as the API is up; medical answers start once
# the startup corpus check logs corpus_verified.
set -eu
cd /home/user/app
python deploy/hf-space/wait_deps.py
alembic -c app/storage/alembic.ini upgrade head
HF_HUB_OFFLINE=0 python deploy/hf-space/restore_corpus.py
export HF_HUB_OFFLINE=1
exec uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers "${WEB_CONCURRENCY:-1}" \
     --proxy-headers --forwarded-allow-ips=127.0.0.1 --timeout-graceful-shutdown 20
