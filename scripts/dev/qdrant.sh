#!/bin/sh
# Run the native Qdrant binary for local development when Docker is unavailable.
# Storage lives outside the repo and outside OneDrive.
set -eu
DATA_ROOT="${AUSCULTA_DATA_ROOT:-/c/dev/ausculta-data}"
BIN="$DATA_ROOT/bin/qdrant-1.20.1/qdrant.exe"
CONF_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DATA_ROOT/qdrant/storage" "$DATA_ROOT/qdrant/snapshots"
export QDRANT__STORAGE__STORAGE_PATH="$DATA_ROOT/qdrant/storage"
export QDRANT__STORAGE__SNAPSHOTS_PATH="$DATA_ROOT/qdrant/snapshots"
export QDRANT__SERVICE__HOST=127.0.0.1
export QDRANT__SERVICE__HTTP_PORT=6333
export QDRANT__SERVICE__GRPC_PORT=6334
export QDRANT__TELEMETRY_DISABLED=true
cd "$DATA_ROOT/qdrant"
exec "$BIN"
