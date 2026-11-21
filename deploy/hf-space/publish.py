"""Publish Ausculta to a free Hugging Face Space (run on the build machine with the dev venv).

    python deploy/hf-space/publish.py export   # snapshot + signed manifests of the live collection
    python deploy/hf-space/publish.py dataset  # upload them to the public dataset {owner}/ausculta-corpus
    python deploy/hf-space/publish.py space    # stage the Space repo from tracked files, upload, set secrets

Needs `hf auth login` (a write token) for `dataset` and `space`. The Space secrets GEMINI_API_KEY and
AUSCULTA_SESSION_SECRET are read from the local settings (.env) and sent to the Hub API, never printed.
The session secret must be the one that signed the manifest (the API verifies the corpus with it).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from huggingface_hub import HfApi
from qdrant_client import QdrantClient

from core.config import REPO_ROOT, get_settings
from rag.paths import DataPaths

SPACE_NAME = "ausculta"
DATASET_NAME = "ausculta-corpus"
SNAPSHOT_FILE = "corpus.snapshot"
# Tracked paths the Space image needs (deploy/hf-space/Dockerfile copies these).
SPACE_PATHS = (
    "core",
    "app",
    "rag",
    "config",
    "evals/__init__.py",
    "evals/fakes",
    "data_pipeline/__init__.py",
    "data_pipeline/drug_synonyms.yaml",
    "data_pipeline/sources/registry.yaml",
    "deploy/requirements.lock",
    "deploy/prefetch_models.py",
    "deploy/hf-space",
    "web",
)
DATASET_CARD = """---
license: other
license_name: us-government-public-domain
pretty_name: Ausculta corpus (Qdrant snapshot)
tags: [medical, rag, qdrant]
---

# Ausculta corpus `{version}`

Qdrant snapshot (`corpus.snapshot`, collection `{collection}`, {chunks} chunks, EmbeddingGemma-300M
dense vectors 768-d + BM25 sparse vectors) and its signed manifest, used by the Ausculta demo Space.
Created by Oussama Tabakh.

All text comes from U.S. Government sources that are public domain or copyright-free; please keep the credits:

{credits}
"""


def _git(*args: str) -> str:
    """Fixed git subcommands on this repository (no shell, no user input)."""
    done = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True)  # noqa: S603, S607
    return done.stdout


def _api() -> HfApi:
    return HfApi()


def _owner(api: HfApi) -> str:
    return str(api.whoami()["name"])


def export_dir() -> Path:
    return DataPaths.from_settings(get_settings()).root / "exports" / "hf-corpus"


def cmd_export() -> None:
    settings = get_settings()
    paths = DataPaths.from_settings(settings)
    active = json.loads(paths.active_pointer.read_text(encoding="utf-8"))
    collection = active["collection"]
    out = export_dir()
    out.mkdir(parents=True, exist_ok=True)
    for src in (
        paths.active_pointer,
        paths.manifest_file(collection),
        paths.retrieval_config_file(collection),
    ):
        shutil.copyfile(src, out / src.name)
    key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    client = QdrantClient(url=settings.qdrant_url, api_key=key, timeout=900)
    snap = client.create_snapshot(collection, wait=True)
    if snap is None:
        raise SystemExit(f"no snapshot for {collection}")
    url = f"{settings.qdrant_url}/collections/{collection}/snapshots/{snap.name}"
    headers = {"api-key": key} if key else {}
    with (
        httpx.stream("GET", url, headers=headers, timeout=900) as resp,
        (out / SNAPSHOT_FILE).open("wb") as fh,
    ):
        resp.raise_for_status()
        for block in resp.iter_bytes(1 << 20):
            fh.write(block)
    client.delete_snapshot(collection, snap.name, wait=True)
    size = (out / SNAPSHOT_FILE).stat().st_size / 1e6
    print(f"exported {collection} ({size:.0f} MB snapshot) and its manifests to {out}")


def _credits(collection: str) -> str:
    import yaml

    manifest = json.loads((export_dir() / f"{collection}.manifest.json").read_text(encoding="utf-8"))
    registry = yaml.safe_load((REPO_ROOT / "data_pipeline/sources/registry.yaml").read_text(encoding="utf-8"))
    sources = registry["sources"]
    items = sources if isinstance(sources, list) else [{"id": k, **v} for k, v in sources.items()]
    by_id = {s["id"]: s for s in items}
    lines = []
    for source_id in sorted(manifest["sources"]):
        lic = by_id[source_id].get("licence") or by_id[source_id].get("license") or {}
        lines.append(f"- `{source_id}`: {lic.get('attribution', '')} Licence: {lic.get('name', '')}.")
    return "\n".join(lines)


def cmd_dataset() -> None:
    api = _api()
    repo_id = f"{_owner(api)}/{DATASET_NAME}"
    out = export_dir()
    active = json.loads((out / "active.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / f"{active['collection']}.manifest.json").read_text(encoding="utf-8"))
    card = DATASET_CARD.format(
        version=active["corpus_version"],
        collection=active["collection"],
        chunks=manifest["chunks"],
        credits=_credits(active["collection"]),
    )
    (out / "README.md").write_text(card, encoding="utf-8")
    api.create_repo(repo_id, repo_type="dataset", private=False, exist_ok=True)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=str(out),
        commit_message="corpus " + active["corpus_version"],
    )
    print(f"uploaded {out} to https://huggingface.co/datasets/{repo_id}")


def _stage(dest: Path) -> None:
    tracked = _git("ls-files", "--", *SPACE_PATHS).splitlines()
    for rel in tracked:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, target)
    shutil.copyfile(REPO_ROOT / "deploy/hf-space/Dockerfile", dest / "Dockerfile")
    shutil.copyfile(REPO_ROOT / "deploy/hf-space/README.space.md", dest / "README.md")
    print(f"staged {len(tracked)} tracked files")


def cmd_space() -> None:
    settings = get_settings()
    if settings.gemini_api_key is None or settings.session_secret is None:
        raise SystemExit(
            "GEMINI_API_KEY and AUSCULTA_SESSION_SECRET must be set in the local settings (.env)"
        )
    api = _api()
    owner = _owner(api)
    repo_id = f"{owner}/{SPACE_NAME}"
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    api.add_space_secret(repo_id, "GEMINI_API_KEY", settings.gemini_api_key.get_secret_value())
    api.add_space_secret(repo_id, "AUSCULTA_SESSION_SECRET", settings.session_secret.get_secret_value())
    origin = f"https://{owner.lower()}-{SPACE_NAME}.hf.space"
    api.add_space_variable(repo_id, "AUSCULTA_ALLOWED_ORIGINS", origin)
    api.add_space_variable(repo_id, "AUSCULTA_CORPUS_REPO", f"{owner}/{DATASET_NAME}")
    api.add_space_variable(repo_id, "GEMINI_TIER", "free")
    with tempfile.TemporaryDirectory() as tmp:
        _stage(Path(tmp))
        api.upload_folder(
            repo_id=repo_id,
            repo_type="space",
            folder_path=tmp,
            commit_message="deploy " + _git("rev-parse", "--short", "HEAD").strip(),
            delete_patterns=["*"],
        )
    print(f"uploaded the Space: https://huggingface.co/spaces/{repo_id}  (app: {origin})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("step", choices=("export", "dataset", "space"))
    args = parser.parse_args()
    {"export": cmd_export, "dataset": cmd_dataset, "space": cmd_space}[args.step]()


if __name__ == "__main__":
    main()
