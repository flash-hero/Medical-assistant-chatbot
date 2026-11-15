"""Export JSON Schemas of the public contracts to docs/contracts/ (consumed by the web app's TS types).

Run: .venv/Scripts/python.exe scripts/export_contracts.py
CI checks the exported files are up to date (git diff --exit-code docs/contracts).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.schemas.chat import Citation  # noqa: E402
from core.schemas.events import CHAT_EVENT_ADAPTER  # noqa: E402
from core.schemas.hospital import HospitalProfile  # noqa: E402

OUT = ROOT / "docs" / "contracts"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    schemas = {
        "chat-events.schema.json": CHAT_EVENT_ADAPTER.json_schema(),
        "citation.schema.json": Citation.model_json_schema(),
        "hospital-profile.schema.json": HospitalProfile.model_json_schema(),
    }
    for name, schema in schemas.items():
        (OUT / name).write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote docs/contracts/{name}")


if __name__ == "__main__":
    main()
