from __future__ import annotations

import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from test_support import AI_SCIENTIST_CMD, REPO_ROOT


EXPECTED_AGENTS = {
    "ai-scientist-ideation-generator",
    "ai-scientist-ideation-critic",
    "ai-scientist-ideation-ranker",
    "ai-scientist-research-baseline-worker",
    "ai-scientist-research-worker",
    "ai-scientist-research-ranker",
    "ai-scientist-research-revision-worker",
}


class AgentDefinitionTests(unittest.TestCase):
    def test_committed_agent_definitions_are_valid(self) -> None:
        paths = sorted((REPO_ROOT / "agents").glob("*.toml"))
        self.assertEqual({path.stem for path in paths}, EXPECTED_AGENTS)
        for path in paths:
            text = path.read_text()
            self.assertTrue(text.startswith(f"# ai-scientist agent: {path.stem}\n"))
            definition = tomllib.loads(text)
            self.assertEqual(definition["name"], path.stem)
            self.assertTrue(definition["description"])
            self.assertTrue(definition["developer_instructions"])

    def test_cli_installs_constants_prunes_stale_and_protects_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / "codex"
            agents_dir = codex_home / "agents"
            agents_dir.mkdir(parents=True)
            stale = agents_dir / "ai-scientist-research-worker-scientist.toml"
            stale.write_text("# ai-scientist agent: old\nname = \"old\"\n")

            install = subprocess.run(
                [*AI_SCIENTIST_CMD, "agents", "install", "--codex-home", str(codex_home)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            self.assertEqual({item["name"] for item in json.loads(install.stdout)["installed"]}, EXPECTED_AGENTS)
            self.assertFalse(stale.exists())

            unmanaged = agents_dir / "ai-scientist-research-worker.toml"
            unmanaged.write_text('name = "user-owned"\n')
            conflict = subprocess.run(
                [*AI_SCIENTIST_CMD, "agents", "install", "--codex-home", str(codex_home)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("unmanaged agent file exists", conflict.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
