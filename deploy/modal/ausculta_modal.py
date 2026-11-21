"""Ausculta on Modal (free Starter plan, no payment method: $1 of compute per month).

Not named app.py: inside the image PYTHONPATH holds the project, whose `app` package would shadow this module.

The image is the single-container stack of deploy/hf-space (Caddy -> Next.js + FastAPI, with Qdrant, Redis and
PostgreSQL on localhost), built from this repository at a pinned, pushed commit. The signed corpus is restored
into the image at build time, so a cold start does not download it. One container at most; it scales to zero
after SCALEDOWN_S idle seconds, which keeps a demo inside the monthly free credit.

    python deploy/modal/stage.py            # writes build/modal/Dockerfile pinned to the current commit
    modal deploy deploy/modal/ausculta_modal.py   # needs `modal token new` and the secret below

Secret `ausculta-secrets` (create with `modal secret create ausculta-secrets --from-dotenv <file>`):
GEMINI_API_KEY and AUSCULTA_SESSION_SECRET (the secret that signed the corpus manifest).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import modal

APP_NAME = "ausculta"
STAGED = Path(__file__).resolve().parents[2] / "build" / "modal"
SCALEDOWN_S = 300
URL = "https://flash-hero--ausculta-web.us-east.modal.run"

# Restore the signed corpus at build time: start Qdrant, run restore_corpus.py (downloads the public GitHub
# release, recovers the collection, checks the point count), stop Qdrant, hand the files to the app user.
BAKE_CORPUS = (
    "export QDRANT__SERVICE__HOST=127.0.0.1 QDRANT__STORAGE__STORAGE_PATH=/home/user/data/qdrant "
    "QDRANT__STORAGE__SNAPSHOTS_PATH=/home/user/data/qdrant-snapshots QDRANT__TELEMETRY_DISABLED=true "
    "&& mkdir -p /home/user/data/qdrant /home/user/data/qdrant-snapshots /home/user/data/manifests "
    "&& cd /home/user/qdrant && { qdrant > /tmp/qdrant-build.log 2>&1 & echo $! > /tmp/qdrant.pid; } "
    "&& cd /home/user/app && python deploy/hf-space/wait_deps.py --only qdrant "
    "&& python deploy/hf-space/restore_corpus.py "
    "&& kill $(cat /tmp/qdrant.pid) && sleep 5 && chown -R 1000:1000 /home/user/data"
)

image = modal.Image.from_dockerfile(
    STAGED / "Dockerfile", context_dir=STAGED, add_python="3.11"
).run_commands(BAKE_CORPUS)

app = modal.App(APP_NAME)


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("ausculta-secrets"),
        modal.Secret.from_dict({"AUSCULTA_ALLOWED_ORIGINS": URL}),
    ],
    cpu=0.5,
    memory=2048,
    timeout=3600,
    scaledown_window=SCALEDOWN_S,
    max_containers=1,
)
@modal.concurrent(max_inputs=100)
@modal.web_server(port=7860, startup_timeout=600)
def web() -> None:
    subprocess.Popen(["sh", "/home/user/app/deploy/hf-space/start.sh"])  # noqa: S607 (fixed entrypoint)
