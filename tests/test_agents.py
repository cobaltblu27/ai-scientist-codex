from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from test_support import AI_SCIENTIST_CMD, REPO_ROOT

from core import agents


class AgentGenerationTests(unittest.TestCase):
    def test_expected_agent_names_and_reasoning_effort(self) -> None:
        listed = {item["name"]: item for item in agents.list_agents()}
        self.assertEqual(
            set(listed),
            {
                "ai-scientist-ideation-generator",
                "ai-scientist-ideation-critic",
                "ai-scientist-ideation-ranker",
                "ai-scientist-research-baseline-worker",
                "ai-scientist-research-worker",
                "ai-scientist-research-ranker",
                "ai-scientist-research-revision-worker",
            },
        )
        self.assertEqual(listed["ai-scientist-ideation-generator"]["model_reasoning_effort"], "xhigh")
        self.assertEqual(listed["ai-scientist-research-baseline-worker"]["model_reasoning_effort"], "medium")
        self.assertEqual(listed["ai-scientist-research-worker"]["model_reasoning_effort"], "xhigh")
        self.assertEqual(listed["ai-scientist-research-ranker"]["prompt_source"], "prompts/research-loop/ranker.md")

    def test_render_strips_frontmatter_and_escapes_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.md"
            prompt.write_text('---\nname: fixture\n---\n# Title\nText with "quotes" and newline.\n')
            spec = agents.AgentSpec(
                name="ai-scientist-fixture",
                description='Fixture "agent"',
                prompt_source="prompt.md",
                model_reasoning_effort="high",
            )
            rendered = agents.render_agent_toml(spec, root=root)
            self.assertTrue(rendered.startswith("# ai-scientist agent: ai-scientist-fixture\n"))
            parsed = tomllib.loads("\n".join(rendered.splitlines()[1:]))
            self.assertEqual(parsed["name"], "ai-scientist-fixture")
            self.assertEqual(parsed["description"], 'Fixture "agent"')
            self.assertEqual(parsed["developer_instructions"], '# Title\nText with "quotes" and newline.\n')
            self.assertNotIn("name: fixture", parsed["developer_instructions"])

    def test_cli_install_check_and_conflict_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / "codex"
            obsolete_critic = codex_home / "agents" / "ai-scientist-research-revision-worker-scientist.toml"
            obsolete_critic.parent.mkdir(parents=True)
            obsolete_critic.write_text(
                "# ai-scientist agent: ai-scientist-research-revision-worker-scientist\n"
                'name = "ai-scientist-research-revision-worker-scientist"\n'
            )
            install = subprocess.run(
                [*AI_SCIENTIST_CMD, "agents", "install", "--codex-home", str(codex_home)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            installed = json.loads(install.stdout)
            self.assertEqual(installed["status"], "ok")
            self.assertTrue((codex_home / "agents" / "ai-scientist-research-worker.toml").exists())
            self.assertTrue((codex_home / "agents" / "ai-scientist-research-ranker.toml").exists())
            self.assertFalse(obsolete_critic.exists())

            check = subprocess.run(
                [*AI_SCIENTIST_CMD, "agents", "check", "--codex-home", str(codex_home)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertTrue(json.loads(check.stdout)["ok"])

            unmanaged = codex_home / "agents" / "ai-scientist-research-worker.toml"
            unmanaged.write_text("name = \"user-owned\"\n")
            conflict = subprocess.run(
                [*AI_SCIENTIST_CMD, "agents", "install", "--codex-home", str(codex_home)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("unmanaged agent file exists", conflict.stdout)

            forced = subprocess.run(
                [*AI_SCIENTIST_CMD, "agents", "install", "--codex-home", str(codex_home), "--force"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(forced.returncode, 0, forced.stdout + forced.stderr)
            self.assertTrue(unmanaged.read_text().startswith("# ai-scientist agent: ai-scientist-research-worker"))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
