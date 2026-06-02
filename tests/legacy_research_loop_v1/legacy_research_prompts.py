from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from research.loop import prompts

ACTIONS = ["draft", "debug", "improve", "tuning", "ablation"]
MODES = ["scientist", "researcher", "balanced", "builder", "engineer"]


def build_prompt(action: str, mode: str, node_dir: Path) -> dict:
    kwargs = {
        "action": action,
        "strictness_mode": mode,
        "node_id": f"{action}-{mode}",
        "parent_node_id": "draft-balanced" if action != "draft" else None,
        "idea": {"id": "fixture-idea", "title": "Fixture"},
        "metric_contract": {"metric_key": "accuracy", "metric_direction": "maximize"},
        "split_policy": "fixed fixture split",
        "root_guidance_summary": "Preserve split integrity.",
        "node_dir": node_dir,
    }
    if hasattr(prompts, "build_prompt"):
        try:
            result = prompts.build_prompt(**kwargs)
        except TypeError:
            config = SimpleNamespace(
                strictness_mode=mode,
                metric_key="accuracy",
                metric_direction="maximize",
                success_threshold=0.75,
                split_policy="fixed fixture split",
                target_repo=node_dir.parent.parent,
            )
            result = prompts.build_prompt(config, action, f"{action}-{mode}", kwargs["parent_node_id"], kwargs["idea"])
    elif hasattr(prompts, "PromptBuilder"):
        result = prompts.PromptBuilder().build(**kwargs)
    else:
        raise AssertionError("research.loop.prompts must expose build_prompt or PromptBuilder.build")

    prompt_path = node_dir / "prompt.json"
    if prompt_path.exists():
        return json.loads(prompt_path.read_text())
    if isinstance(result, dict):
        return result
    if isinstance(result, (str, Path)) and Path(result).exists():
        return json.loads(Path(result).read_text())
    raise AssertionError("prompt builder must emit prompt.json or return prompt metadata")


class PromptTests(unittest.TestCase):
    def test_prompt_builder_emits_action_and_strictness_mode_metadata(self) -> None:
        for action in ACTIONS:
            for mode in MODES:
                with self.subTest(action=action, mode=mode), TemporaryDirectory() as td:
                    node_dir = Path(td) / "nodes" / f"{action}-{mode}"
                    node_dir.mkdir(parents=True)
                    prompt = build_prompt(action, mode, node_dir)
                    self.assertEqual(prompt["action"], action)
                    self.assertEqual(prompt["strictness_mode"], mode)
                    self.assertEqual(prompt.get("node_id"), f"{action}-{mode}")
                    self.assertIn("template_id", prompt)
                    self.assertIn("template_version", prompt)
                    self.assertTrue(prompt.get("expected_manifest_schema_version") or prompt.get("schema_version"))
                    self.assertEqual(prompt.get("metric_contract", {}).get("metric_key"), "accuracy")
                    self.assertIn("manifest", json.dumps(prompt).lower())


if __name__ == "__main__":
    unittest.main()
