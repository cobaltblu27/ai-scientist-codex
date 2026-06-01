from __future__ import annotations

import json
import sys
from typing import Any


def emit(status: str, **fields: Any) -> int:
    sys.stdout.write(json.dumps({"status": status, **fields}, indent=2, sort_keys=True) + "\n")
    return 0 if status == "ok" else 1
