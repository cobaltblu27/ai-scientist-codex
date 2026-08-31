from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from test_support import PLUGIN_ROOT

from core import agents
from core.state import active_run_owned_by_caller, stop_caller_identity


class ClaudeAgentRenderTests(unittest.TestCase):
    def test_rendered_agents_are_valid_frontmatter_documents(self) -> None:
        for spec in agents.AGENT_SPECS:
            rendered = agents.render_agent_md(spec)
            self.assertTrue(rendered.startswith("---\n"), spec.name)
            frontmatter, body = rendered[4:].split("\n---\n", 1)
            meta = yaml.safe_load(frontmatter)
            self.assertEqual(set(meta), {"name", "description"}, spec.name)
            self.assertEqual(meta["name"], spec.name)
            self.assertEqual(meta["description"], spec.description)
            self.assertTrue(body.strip(), spec.name)
            self.assertNotIn("model_reasoning_effort", rendered)

    def test_build_writes_one_file_per_spec_and_prunes_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "agents"
            out.mkdir()
            stale = out / "ai-scientist-research-worker-scientist.md"
            stale.write_text("---\nname: old\n---\nstale\n")
            written = agents.build_claude_agents(out_dir=out)
            self.assertEqual(len(written), len(agents.AGENT_SPECS))
            self.assertFalse(stale.exists())
            self.assertEqual(
                {p.stem for p in out.glob("*.md")},
                {spec.name for spec in agents.AGENT_SPECS},
            )

    def test_committed_agents_match_current_prompts(self) -> None:
        for spec in agents.AGENT_SPECS:
            path = PLUGIN_ROOT / "agents" / f"{spec.name}.md"
            self.assertTrue(path.exists(), f"{path} missing; run `ai-scientist agents build`")
            self.assertEqual(
                path.read_text(),
                agents.render_agent_md(spec),
                f"{path} is stale; run `ai-scientist agents build`",
            )


class SessionIdentityTests(unittest.TestCase):
    def test_identity_reads_both_runtime_payload_shapes(self) -> None:
        self.assertEqual(stop_caller_identity({"session_id": "claude-1"}), "claude-1")
        self.assertEqual(stop_caller_identity({"codex_session_id": "codex-1"}), "codex-1")

    def test_ownership_holds_the_owner_and_releases_other_sessions(self) -> None:
        active = {"owner_session_id": "owner"}
        self.assertIs(active_run_owned_by_caller(active, {"session_id": "owner"}), True)
        self.assertIs(active_run_owned_by_caller(active, {"session_id": "worker"}), False)

    def test_unowned_run_is_not_attributed_to_any_session(self) -> None:
        self.assertIsNone(active_run_owned_by_caller({"owner_session_id": None}, {"session_id": "x"}))


class ClaudePluginManifestTests(unittest.TestCase):
    def test_plugin_and_marketplace_manifests_are_consistent(self) -> None:
        plugin = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        marketplace = json.loads((PLUGIN_ROOT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(plugin["name"], "ai-scientist")
        self.assertIn("description", plugin)
        self.assertEqual([p["name"] for p in marketplace["plugins"]], [plugin["name"]])

    def test_stop_hook_is_the_only_wired_event(self) -> None:
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(list(hooks), ["Stop"])
        command = hooks["Stop"][0]["hooks"][0]["command"]
        self.assertIn("hooks stop-gate", command)


if __name__ == "__main__":
    unittest.main()
