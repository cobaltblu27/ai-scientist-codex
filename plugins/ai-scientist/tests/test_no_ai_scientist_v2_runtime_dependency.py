from __future__ import annotations

import unittest

from test_support import PLUGIN_ROOT


class RuntimeDependencyTests(unittest.TestCase):
    def test_research_runtime_has_no_ai_scientist_v2_dependency_reference(self) -> None:
        runtime_paths = [PLUGIN_ROOT / "scripts" / "research_orchestrator.py", PLUGIN_ROOT / "scripts" / "research_loop"]
        matches: list[str] = []
        for path in runtime_paths:
            if not path.exists():
                continue
            files = [path] if path.is_file() else [p for p in path.rglob("*.py") if p.is_file()]
            for file in files:
                text = file.read_text(errors="ignore")
                for needle in ("AI-Scientist-v2", "AI_Scientist_v2", "ai-scientist-v2"):
                    if needle in text:
                        matches.append(f"{file}: contains {needle}")
        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
