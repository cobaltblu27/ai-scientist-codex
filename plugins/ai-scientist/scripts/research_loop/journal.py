from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


class Journal:
    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "journal.json"
        if not self.path.exists():
            write_json(self.path, {"entries": []})

    def record(self, event: str, **fields: Any) -> None:
        data = json.loads(self.path.read_text()) if self.path.exists() else {"entries": []}
        data.setdefault("entries", []).append({"timestamp": utc_now(), "event": event, **fields})
        write_json(self.path, data)
