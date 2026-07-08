from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_support import AI_SCIENTIST_CMD

CLI_ARGS = AI_SCIENTIST_CMD


class IdeationHookTests(unittest.TestCase):
    def test_legacy_codex_event_hook_bridge_is_removed(self) -> None:
        proc = subprocess.run(
            [*CLI_ARGS, "hooks", "codex-event", "UserPromptSubmit"],
            input=json.dumps({"prompt": "/ideate legacy"}),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("invalid choice", proc.stderr)

    def test_stop_gate_command_remains_available(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            proc = subprocess.run(
                [*CLI_ARGS, "hooks", "stop-gate", "--target-repo", str(target)],
                input=json.dumps({"hook_event_name": "Stop", "cwd": str(target)}),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), {})


if __name__ == "__main__":
    unittest.main()
