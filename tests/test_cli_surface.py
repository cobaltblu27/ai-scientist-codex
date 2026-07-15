from __future__ import annotations

import subprocess
import unittest

from test_support import AI_SCIENTIST_CMD


def run_help(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*AI_SCIENTIST_CMD, *args, "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class CliSurfaceTests(unittest.TestCase):
    def test_top_level_surface_excludes_retired_ideation(self) -> None:
        result = run_help()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ideation", result.stdout)
        for group in ["hooks", "agents", "research", "writeup", "validation", "handoff", "resource"]:
            self.assertIn(group, result.stdout)

    def test_research_start_exposes_only_documented_payload_input(self) -> None:
        result = run_help("research", "start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--json-file", result.stdout)
        for removed in ["--json ", "--path", "--resource-config", "--codex-session-id", "--codex-thread-id"]:
            self.assertNotIn(removed, result.stdout)

    def test_retired_validation_gates_are_not_accepted(self) -> None:
        for gate in ["ideation_to_research", "principles", "all"]:
            result = subprocess.run(
                [*AI_SCIENTIST_CMD, "validate", "run", ".", "--gate", gate],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0, gate)

    def test_minor_legacy_commands_are_removed(self) -> None:
        agents = run_help("agents")
        self.assertNotIn("list", agents.stdout)
        writeup = run_help("writeup")
        self.assertNotIn("resume", writeup.stdout)


if __name__ == "__main__":
    unittest.main()
