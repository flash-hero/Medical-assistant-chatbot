"""Write build/modal/Dockerfile for `modal deploy deploy/modal/ausculta_modal.py`.

It is deploy/hf-space/Dockerfile cloning this repository at the current commit (which must be pushed),
without the local-tree source option, the BuildKit syntax line and the final USER (Modal's image builder and
its Python runtime install run as root; start.sh drops to the unprivileged user at runtime).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "modal"


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)  # noqa: S603, S607
    return done.stdout.strip()


def render(dockerfile: str, ref: str) -> str:
    text = dockerfile.replace("ARG REF=main", f"ARG REF={ref}", 1)
    text = re.sub(r"^# syntax=.*\n", "", text, flags=re.M)
    text = re.sub(r"^ARG SRC=git\n", "", text, flags=re.M)
    text = text.replace("FROM scratch AS src-context\nCOPY . /src\n\n", "")
    text = text.replace("FROM src-${SRC} AS src", "FROM src-git AS src")
    text = re.sub(r"^USER 1000\n", "", text, flags=re.M)
    for needle in (f"ARG REF={ref}", "FROM src-git AS src"):
        if needle not in text:
            raise SystemExit(f"stage: expected {needle!r} in the rendered Dockerfile")
    if "src-context" in text or "${SRC}" in text:
        raise SystemExit("stage: the local-tree source option is still in the rendered Dockerfile")
    return text


def main() -> None:
    ref = _git("rev-parse", "HEAD")
    if not _git("branch", "-r", "--contains", ref):
        raise SystemExit(f"{ref[:7]} is not pushed: the Modal build clones it from GitHub")
    OUT.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "deploy/hf-space/Dockerfile").read_text(encoding="utf-8")
    (OUT / "Dockerfile").write_text(render(source, ref), encoding="utf-8")
    print(f"wrote {OUT / 'Dockerfile'} pinned to {ref[:7]}")


if __name__ == "__main__":
    main()
