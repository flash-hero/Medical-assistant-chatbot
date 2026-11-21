"""Publish Ausculta to a free Hugging Face Space (run on the build machine with the dev venv).

    python deploy/hf-space/publish.py export   # snapshot + signed manifests of the live collection
    python deploy/hf-space/publish.py release  # upload them as a public GitHub release (gh CLI)
    python deploy/hf-space/publish.py space    # create the Space, set its secrets, upload Dockerfile + README

The Space's Dockerfile clones the public GitHub repository at the current commit, and the container downloads
the corpus from the release, so only `space` needs a Hugging Face login (`hf auth login`, a write token). Its
secrets GEMINI_API_KEY and AUSCULTA_SESSION_SECRET come from the local settings (.env) and go to the Hub API,
never printed. The session secret must be the one that signed the manifest (the API verifies the corpus).
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
GITHUB_REPO = "flash-hero/Medical-assistant-chatbot"
SNAPSHOT_FILE = "corpus.snapshot"
RELEASE_NOTES = """Signed corpus `{version}` for the Ausculta demo Space: Qdrant snapshot `corpus.snapshot`
(collection `{collection}`, {chunks} chunks, EmbeddingGemma-300M 768-d dense + BM25 sparse vectors), its
signed manifest, retrieval config and active pointer. Restored by `deploy/hf-space/restore_corpus.py`.

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


def release_tag(corpus_version: str) -> str:
    return f"corpus-{corpus_version}"


def cmd_release() -> None:
    out = export_dir()
    active = json.loads((out / "active.json").read_text(encoding="utf-8"))
    collection = active["collection"]
    manifest = json.loads((out / f"{collection}.manifest.json").read_text(encoding="utf-8"))
    notes = out.parent / "release-notes.md"
    notes.write_text(
        RELEASE_NOTES.format(
            version=active["corpus_version"],
            collection=collection,
            chunks=manifest["chunks"],
            credits=_credits(collection),
        ),
        encoding="utf-8",
    )
    tag = release_tag(active["corpus_version"])
    files = [
        str(out / n)
        for n in (SNAPSHOT_FILE, "active.json", f"{collection}.manifest.json", f"{collection}.retrieval.json")
    ]
    exists = (
        subprocess.run(  # noqa: S603 (fixed gh subcommand)
            ["gh", "release", "view", tag, "--repo", GITHUB_REPO],  # noqa: S607
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    if exists:
        args = ["gh", "release", "upload", tag, *files, "--repo", GITHUB_REPO, "--clobber"]
    else:
        title = f"Corpus {active['corpus_version']}"
        args = [
            "gh",
            "release",
            "create",
            tag,
            *files,
            "--repo",
            GITHUB_REPO,
            "--title",
            title,
            "--notes-file",
            str(notes),
            "--latest=false",
        ]
    subprocess.run(args, check=True)  # noqa: S603 (fixed gh subcommand, local file paths)
    print(f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}")


def _deploy_message() -> str:
    return "deploy " + _git("rev-parse", "--short", "HEAD").strip()


def _stage(dest: Path) -> None:
    """The Space repo: the Dockerfile with REF pinned to the current (pushed) commit, and the README card."""
    head = _git("rev-parse", "HEAD").strip()
    if _git("branch", "-r", "--contains", head).strip() == "":
        raise SystemExit(f"{head[:7]} is not pushed: the Space build clones it from GitHub")
    dockerfile = (REPO_ROOT / "deploy/hf-space/Dockerfile").read_text(encoding="utf-8")
    pinned = dockerfile.replace("ARG REF=main", f"ARG REF={head}", 1)
    if pinned == dockerfile:
        raise SystemExit("deploy/hf-space/Dockerfile has no 'ARG REF=main' line to pin")
    (dest / "Dockerfile").write_text(pinned, encoding="utf-8")
    shutil.copyfile(REPO_ROOT / "deploy/hf-space/README.space.md", dest / "README.md")


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
    api.add_space_variable(repo_id, "GEMINI_TIER", "free")
    with tempfile.TemporaryDirectory() as tmp:
        _stage(Path(tmp))
        api.upload_folder(
            repo_id=repo_id, repo_type="space", folder_path=tmp, commit_message=_deploy_message()
        )
    print(f"uploaded the Space: https://huggingface.co/spaces/{repo_id}  (app: {origin})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("step", choices=("export", "release", "space"))
    args = parser.parse_args()
    {"export": cmd_export, "release": cmd_release, "space": cmd_space}[args.step]()


if __name__ == "__main__":
    main()
