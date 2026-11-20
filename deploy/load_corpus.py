"""Load a promoted corpus collection from the build machine's Qdrant into the Docker stack and make it live.

The corpus is built, evaluated and promoted locally (`python -m rag build / eval / promote`). This copies it
into the stack: snapshot of the collection -> the stack's Qdrant (recovered under the same name), the signed
manifest, retrieval config and active pointer -> the API's /data/manifests, the alias switched, the API
restarted so it verifies the new corpus at startup. The previous collection stays in the stack for rollback.

Run from the repo root with the dev venv (reads the build machine's .env):
    python deploy/load_corpus.py ausculta_corpus_2026_11_20_en2
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from qdrant_client import QdrantClient

from core.config import get_settings
from rag.paths import DataPaths, validate_collection

COMPOSE = ["docker", "compose", "-f", "deploy/compose.yaml", "--env-file", "deploy/.env.prod"]
STACK_SNAPSHOT_DIR = "/qdrant/snapshots"
API_MANIFESTS_DIR = "/data/manifests"
API_UID = "10001:10001"  # the `app` user of deploy/api.Dockerfile
HEALTH_WAIT_S = 300
VERIFY_WAIT_S = 180  # the corpus check runs after startup (checksums of every point)

# Runs inside the API container (it can reach the internal Qdrant and holds QDRANT_API_KEY).
RECOVER_SCRIPT = """
import os, sys
from qdrant_client import QdrantClient, models
collection, snapshot, alias = sys.argv[1], sys.argv[2], sys.argv[3]
c = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ.get("QDRANT_API_KEY"), timeout=900)
c.recover_snapshot(collection, location=f"file:///qdrant/snapshots/{snapshot}", wait=True)
ops = [models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=a.alias_name))
       for a in c.get_aliases().aliases if a.alias_name == alias]
new = models.CreateAlias(collection_name=collection, alias_name=alias)
ops.append(models.CreateAliasOperation(create_alias=new))
c.update_collection_aliases(change_aliases_operations=ops)
print("points", c.get_collection(collection).points_count)
"""


def run(args: list[str], *, stdin: str | None = None) -> str:
    # fixed argv (no shell): docker compose with a validated collection name and local file paths
    done = subprocess.run(  # noqa: S603
        args, input=stdin, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if done.returncode != 0:
        raise SystemExit(f"command failed ({done.returncode}): {' '.join(args)}\n{done.stderr.strip()}")
    return done.stdout


def local_files(paths: DataPaths, collection: str) -> list[Path]:
    """Manifest, retrieval config and active pointer; the pointer must name this collection."""
    files = [paths.manifest_file(collection), paths.retrieval_config_file(collection), paths.active_pointer]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise SystemExit(f"missing: {', '.join(missing)} (build, eval and promote the collection first)")
    active = json.loads(paths.active_pointer.read_text(encoding="utf-8")).get("collection")
    if active != collection:
        raise SystemExit(
            f"active.json names {active!r}, not {collection!r}: run `python -m rag promote` first"
        )
    return files


def download_snapshot(collection: str, dest_dir: Path) -> Path:
    settings = get_settings()
    key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    client = QdrantClient(url=settings.qdrant_url, api_key=key, timeout=900)
    snap = client.create_snapshot(collection, wait=True)
    if snap is None:
        raise SystemExit(f"Qdrant returned no snapshot for {collection}")
    dest = dest_dir / snap.name
    headers = {"api-key": key} if key else {}
    url = f"{settings.qdrant_url}/collections/{collection}/snapshots/{snap.name}"
    with httpx.stream("GET", url, headers=headers, timeout=900) as resp, dest.open("wb") as fh:
        resp.raise_for_status()
        for block in resp.iter_bytes(1 << 20):
            fh.write(block)
    client.delete_snapshot(collection, snap.name, wait=True)
    return dest


def wait_healthy(service: str) -> None:
    deadline = time.monotonic() + HEALTH_WAIT_S
    while time.monotonic() < deadline:
        if run([*COMPOSE, "ps", service, "--format", "{{.Health}}"]).strip() == "healthy":
            return
        time.sleep(4)
    raise SystemExit(f"{service} not healthy after {HEALTH_WAIT_S}s: see `docker compose logs {service}`")


def wait_verified(collection: str) -> None:
    """Wait for the API's startup corpus check to log its verdict for this collection."""
    deadline = time.monotonic() + VERIFY_WAIT_S
    while time.monotonic() < deadline:
        for line in run([*COMPOSE, "logs", "api", "--since", "5m"]).splitlines():
            if collection in line and '"corpus_unverified"' in line:
                raise SystemExit(f"the API refused the corpus: {line.strip()}")
            if collection in line and '"corpus_verified"' in line:
                return
        time.sleep(5)
    raise SystemExit(
        f"no corpus verdict for {collection} after {VERIFY_WAIT_S}s: see `docker compose logs api`"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("collection")
    args = parser.parse_args(argv)
    collection = validate_collection(args.collection)
    settings = get_settings()
    files = local_files(DataPaths.from_settings(settings), collection)

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = download_snapshot(collection, Path(tmp))
        print(f"snapshot {snapshot.name}: {snapshot.stat().st_size / 1e6:.0f} MB")
        run([*COMPOSE, "cp", snapshot.as_posix(), f"qdrant:{STACK_SNAPSHOT_DIR}/{snapshot.name}"])
    out = run(
        [*COMPOSE, "exec", "-T", "api", "python", "-", collection, snapshot.name, settings.qdrant_alias],
        stdin=RECOVER_SCRIPT,
    )
    print(f"recovered {collection} in the stack ({out.strip()}), alias {settings.qdrant_alias!r} switched")
    run([*COMPOSE, "exec", "-T", "-u", "root", "qdrant", "rm", "-f", f"{STACK_SNAPSHOT_DIR}/{snapshot.name}"])

    run([*COMPOSE, "exec", "-T", "api", "mkdir", "-p", API_MANIFESTS_DIR])
    for f in files:
        run([*COMPOSE, "cp", f.as_posix(), f"api:{API_MANIFESTS_DIR}/{f.name}"])
    run([*COMPOSE, "exec", "-T", "-u", "root", "api", "chown", "-R", API_UID, API_MANIFESTS_DIR])
    print(f"copied {', '.join(f.name for f in files)}")

    run([*COMPOSE, "restart", "api"])
    wait_healthy("api")
    wait_verified(collection)
    print(f"API restarted and verified {collection}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
