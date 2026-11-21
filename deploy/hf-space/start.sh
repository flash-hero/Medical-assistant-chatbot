#!/bin/sh
# Container entrypoint: per-boot passwords for the local-only Redis and PostgreSQL, a fresh database cluster
# (the free Space has no persistent disk: sessions and appointment requests last until the next restart),
# then supervisord runs every service. The corpus and the schema are set up by api-start.sh.
set -eu

export PGDATA="${PGDATA:-/home/user/pgdata}"
PG_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
REDIS_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
export REDIS_PASSWORD
export DATABASE_URL="postgresql+asyncpg://ausculta:${PG_PASSWORD}@127.0.0.1:5432/ausculta"
export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
export QDRANT__SERVICE__HOST=127.0.0.1
export QDRANT__STORAGE__STORAGE_PATH=/home/user/data/qdrant
export QDRANT__STORAGE__SNAPSHOTS_PATH=/home/user/data/qdrant-snapshots
export QDRANT__TELEMETRY_DISABLED=true

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  pwfile="$(mktemp)"
  printf '%s' "$PG_PASSWORD" > "$pwfile"
  initdb --pgdata="$PGDATA" --username=ausculta --pwfile="$pwfile" --auth=scram-sha-256 \
         --encoding=UTF8 --locale=C.UTF-8 >/dev/null
  rm -f "$pwfile"
  pg_ctl --pgdata="$PGDATA" --wait --silent \
         --options="-c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp" start
  PGPASSWORD="$PG_PASSWORD" createdb --host=127.0.0.1 --username=ausculta ausculta
  pg_ctl --pgdata="$PGDATA" --wait --silent stop
fi

mkdir -p "$QDRANT__STORAGE__STORAGE_PATH" "$QDRANT__STORAGE__SNAPSHOTS_PATH" /home/user/data/manifests
exec supervisord --configuration /home/user/app/deploy/hf-space/supervisord.conf
