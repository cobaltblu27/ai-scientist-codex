from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
