from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from test_support import PLUGIN_ROOT, SCRIPTS_DIR, read_json


def run_hook(event: str, payload: dict, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "ideation_hook.py"), event],
        input=json.dumps(payload),
        cwd=cwd or PLUGIN_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class IdeationHookTests(unittest.TestCase):
    def test_user_prompt_requires_explicit_marker(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            proc = run_hook("UserPromptSubmit", {"cwd": str(target), "prompt": "please brainstorm ideas"})

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse((target / ".ai-scientist").exists())

    def test_user_prompt_explicit_marker_initializes_state(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            proc = run_hook("UserPromptSubmit", {"cwd": str(target), "prompt": "/ideate study robust baselines", "thread_id": "thread-1", "turn_id": "turn-1"})

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["active"])
            self.assertIn("SearchSemanticScholar", payload["message"])
            pointer = read_json(target / ".ai-scientist" / "state" / "active-ideation.json")
            state = read_json(target / pointer["state_file"])
            self.assertEqual(state["codex_thread_id"], "thread-1")

    def test_pre_tool_use_blocks_nested_codex_exec_during_active_ideation(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            init = run_hook("UserPromptSubmit", {"cwd": str(target), "prompt": "/ideate study robust baselines"})
            self.assertEqual(init.returncode, 0, init.stderr)

            proc = run_hook("PreToolUse", {"cwd": str(target), "tool_input": {"command": "codex exec --cd . -"}}, cwd=PLUGIN_ROOT)

            self.assertEqual(proc.returncode, 2)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["decision"], "block")
            pointer = read_json(target / ".ai-scientist" / "state" / "active-ideation.json")
            state = read_json(target / pointer["state_file"])
            self.assertEqual(state["status"], "blocked")
            self.assertEqual(state["reason"], "blocked_tool_pattern")


if __name__ == "__main__":
    unittest.main()
