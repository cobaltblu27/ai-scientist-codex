from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from research.loop import agents
from research.loop import config as config_module

from test_support import SRC_DIR


def assert_approval_before_exec(testcase: unittest.TestCase, cmd: list[str]) -> None:
    exec_index = cmd.index("exec")
    approval_index = cmd.index("--ask-for-approval")
    testcase.assertLess(approval_index, exec_index)
    testcase.assertEqual(cmd[approval_index + 1], "never")
    testcase.assertNotIn("--ask-for-approval", cmd[exec_index + 1 :])


class CodexCommandArgvTests(unittest.TestCase):
    def test_ideation_no_longer_defines_codex_agent_runner(self) -> None:
        texts = [path.read_text() for path in (SRC_DIR / "ideation").rglob("*.py")]
        text = "\n".join(texts)
        subprocess_codex_lines = [
            line
            for source in texts
            for line in source.splitlines()
            if "subprocess." in line and "codex" in line.lower()
        ]

        self.assertNotIn("CodexAgentRunner", text)
        self.assertEqual(subprocess_codex_lines, [])

    def test_research_codex_runner_uses_global_approval_flag(self) -> None:
        config = config_module.ResearchConfig(
            target_repo=SRC_DIR,
            idea_json=None,
            run_id="run-001",
            strictness_mode="balanced",
            entry_script=None,
            dataset_loader=None,
            baseline_command="true",
            metric_key="accuracy",
            metric_direction="maximize",
            success_threshold=None,
            split_policy="fixed",
            split_manifest=None,
            max_nodes=1,
            max_debug_attempts=1,
            max_improve_attempts=1,
            max_tuning_attempts=1,
            max_ablation_attempts=1,
            max_parallel=1,
            resources=config_module.ResourceCaps(),
            node_timeout_sec=30,
            agent_runner="codex",
            codex_cmd="codex",
            codex_model="gpt-5.5",
            fixture_scenario="success",
        )
        with mock.patch.object(agents.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}\n", stderr="")

            agents.CodexRunner().run({"action": "draft"}, config)

        cmd = run.call_args.args[0]
        assert_approval_before_exec(self, cmd)


if __name__ == "__main__":
    unittest.main()
