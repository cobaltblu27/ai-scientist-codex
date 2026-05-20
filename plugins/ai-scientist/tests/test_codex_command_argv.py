from __future__ import annotations

import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
from test_support import SCRIPTS_DIR

agents = importlib.import_module("research_loop.agents")
config_module = importlib.import_module("research_loop.config")


def assert_approval_before_exec(testcase: unittest.TestCase, cmd: list[str]) -> None:
    exec_index = cmd.index("exec")
    approval_index = cmd.index("--ask-for-approval")
    testcase.assertLess(approval_index, exec_index)
    testcase.assertEqual(cmd[approval_index + 1], "never")
    testcase.assertNotIn("--ask-for-approval", cmd[exec_index + 1 :])


class CodexCommandArgvTests(unittest.TestCase):
    def test_ideation_no_longer_defines_codex_agent_runner(self) -> None:
        text = (SCRIPTS_DIR / "ideation_orchestrator.py").read_text()
        self.assertNotIn("CodexAgentRunner", text)
        self.assertNotIn("subprocess.run", text)

    def test_research_codex_runner_uses_global_approval_flag(self) -> None:
        config = config_module.ResearchConfig(
            target_repo=SCRIPTS_DIR,
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
