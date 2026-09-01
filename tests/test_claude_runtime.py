from __future__ import annotations

import json
import subprocess
import unittest

from test_support import PLUGIN_ROOT


class ClaudePluginManifestTests(unittest.TestCase):
    def test_plugin_and_marketplace_manifests_are_consistent(self) -> None:
        plugin = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        marketplace = json.loads((PLUGIN_ROOT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(plugin["name"], "ai-scientist")
        self.assertIn("description", plugin)
        self.assertEqual([p["name"] for p in marketplace["plugins"]], [plugin["name"]])

    def test_plugin_does_not_ship_hooks(self) -> None:
        self.assertFalse((PLUGIN_ROOT / "hooks" / "hooks.json").exists())

    def test_bundled_cli_launcher_runs_without_a_global_install(self) -> None:
        launcher = PLUGIN_ROOT / "bin" / "ai-scientist"
        result = subprocess.run(
            [launcher, "--help"],
            cwd=PLUGIN_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AI Scientist", result.stdout)
        self.assertNotIn("hooks", result.stdout)

    def test_research_loop_uses_claude_native_routing(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "research-loop" / "SKILL.md").read_text()
        bootstrap = (PLUGIN_ROOT / "skills" / "research-loop-bootstrap" / "SKILL.md").read_text()
        worker = (PLUGIN_ROOT / "agents" / "ai-scientist-research-worker.md").read_text()
        self.assertIn("disable-model-invocation: true", skill)
        self.assertIn("ai-scientist:ai-scientist-research-worker", skill)
        self.assertNotIn("update_goal", skill)
        self.assertIn("`/goal`", skill)
        self.assertIn("`/goal`", bootstrap)
        self.assertIn("ai-scientist --target-repo <target-repo> resource run", worker)


if __name__ == "__main__":
    unittest.main()
