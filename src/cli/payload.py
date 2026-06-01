from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


class PayloadError(ValueError):
    pass


def load_json_object(*, json_text: str | None = None, json_file: Path | None = None, stdin: bool = False) -> dict[str, Any]:
    if json_file is not None:
        value = json.loads(json_file.read_text())
    elif json_text is not None:
        value = json.loads(json_text)
    elif stdin:
        raw = sys.stdin.read().strip()
        value = json.loads(raw) if raw else {}
    else:
        value = {}
    if not isinstance(value, dict):
        raise PayloadError("payload must be a JSON object")
    return value

