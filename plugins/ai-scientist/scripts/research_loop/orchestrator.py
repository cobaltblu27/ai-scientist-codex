from __future__ import annotations

from _ai_scientist_src import ensure_src

ensure_src()

from ai_scientist_codex.research.loop.orchestrator import *  # noqa: F401,F403
from ai_scientist_codex.research.loop.orchestrator import main


if __name__ == "__main__":
    raise SystemExit(main())
