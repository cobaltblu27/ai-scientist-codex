from __future__ import annotations

import sys
from pathlib import Path


def ensure_src() -> None:
    src = Path(__file__).resolve().parents[3] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
