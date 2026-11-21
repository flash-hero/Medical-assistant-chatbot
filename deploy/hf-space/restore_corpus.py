"""Make the signed corpus live in the Space's Qdrant (idempotent; runs before every API start).

First boot: download the collection snapshot and its signed manifest, retrieval config and active pointer
from AUSCULTA_CORPUS_URL (a public GitHub release of the repository; no token needed), or copy them from
AUSCULTA_CORPUS_LOCAL_DIR (a local test of the image). Then recover the collection, point the alias at it
and drop the snapshot file. Later boots only re-check the alias and the files. The API then verifies the
collection against the signed manifest (checksums, ids, count, HMAC) and refuses to answer medical
questions from anything else.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from qdrant_client import QdrantClient, models

BASE_URL = os.environ.get(
    "AUSCULTA_CORPUS_URL",
    "https://github.com/flash-hero/Medical-assistant-chatbot/releases/download/corpus-2026-11-20.en2",
)
LOCAL_DIR = os.environ.get("AUSCULTA_CORPUS_LOCAL_DIR")
ALIAS = os.environ.get("QDRANT_ALIAS", "ausculta_corpus")
DATA_ROOT = Path(os.environ["AUSCULTA_DATA_ROOT"])
MANIFESTS = DATA_ROOT / "manifests"
SNAPSHOTS = Path(os.environ.get("QDRANT__STORAGE__SNAPSHOTS_PATH", str(DATA_ROOT / "qdrant-snapshots")))
SNAPSHOT_FILE = "corpus.snapshot"


def _fetch(name: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    if LOCAL_DIR:
        target = dest_dir / name
        shutil.copyfile(Path(LOCAL_DIR) / name, target)
        return target
    import httpx

    target = dest_dir / name
    partial = target.with_suffix(target.suffix + ".part")
    with httpx.stream("GET", f"{BASE_URL.rstrip('/')}/{name}", follow_redirects=True, timeout=600) as resp:
        resp.raise_for_status()
        with partial.open("wb") as fh:
            for block in resp.iter_bytes(1 << 20):
                fh.write(block)
    partial.replace(target)
    return target


def _active_collection() -> str:
    pointer = _fetch("active.json", MANIFESTS)
    collection = json.loads(pointer.read_text(encoding="utf-8"))["collection"]
    for suffix in (".manifest.json", ".retrieval.json"):
        _fetch(f"{collection}{suffix}", MANIFESTS)
    return str(collection)


def main() -> int:
    collection = _active_collection()
    client = QdrantClient(url=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"), timeout=900)
    if collection not in {c.name for c in client.get_collections().collections}:
        snapshot = _fetch(SNAPSHOT_FILE, SNAPSHOTS)
        print(f"restore_corpus: recovering {collection} from {snapshot.stat().st_size / 1e6:.0f} MB snapshot")
        client.recover_snapshot(collection, location=snapshot.resolve().as_uri(), wait=True)
        snapshot.unlink(missing_ok=True)
    ops: list[models.AliasOperations] = [
        models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=a.alias_name))
        for a in client.get_aliases().aliases
        if a.alias_name == ALIAS
    ]
    new_alias = models.CreateAlias(collection_name=collection, alias_name=ALIAS)
    ops.append(models.CreateAliasOperation(create_alias=new_alias))
    client.update_collection_aliases(change_aliases_operations=ops)
    manifest = json.loads((MANIFESTS / f"{collection}.manifest.json").read_text(encoding="utf-8"))
    points = client.get_collection(collection).points_count
    if points != manifest["chunks"]:
        print(
            f"restore_corpus: {collection} holds {points} points, manifest says {manifest['chunks']}",
            file=sys.stderr,
        )
        return 1
    print(f"restore_corpus: {collection} live behind {ALIAS!r} ({points} points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
