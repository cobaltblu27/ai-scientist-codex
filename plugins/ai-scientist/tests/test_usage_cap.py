from __future__ import annotations

import io
import json
import unittest
from unittest import mock

from test_support import import_planned_module

usage_cap = import_planned_module("usage_cap")


class FakeProcess:
    def __init__(self, lines: list[str]):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(lines))
        self.stderr = io.StringIO()
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.terminated = True


def json_line(payload: dict) -> str:
    return json.dumps(payload) + "\n"


class UsageCapTests(unittest.TestCase):
    def test_read_codex_rate_limits_parses_successful_response(self) -> None:
        response = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": "2026-05-28T12:00:00Z"},
                        "secondary": {"usedPercent": 34, "windowDurationMins": 10080, "resetsAt": "2026-05-29T12:00:00Z"},
                        "planType": "pro",
                    }
                }
            },
        }
        with mock.patch.object(usage_cap.subprocess, "Popen", return_value=FakeProcess([json_line(response)])):
            snapshot = usage_cap.read_codex_rate_limits(timeout_seconds=1)
        self.assertEqual(snapshot["limit_id"], "codex")
        self.assertEqual(snapshot["primary"]["usedPercent"], 12.0)
        self.assertEqual(snapshot["secondary"]["usedPercent"], 34.0)
        self.assertEqual(snapshot["effective_used_percent"], 34.0)
        self.assertEqual(snapshot["planType"], "pro")

    def test_notifications_before_response_are_ignored(self) -> None:
        lines = [
            json_line({"jsonrpc": "2.0", "method": "account/rateLimits/changed", "params": {}}),
            json_line({"jsonrpc": "2.0", "id": 1, "result": {}}),
            json_line({"jsonrpc": "2.0", "id": 2, "result": {"limit_id": "codex", "usedPercent": 44}}),
        ]
        with mock.patch.object(usage_cap.subprocess, "Popen", return_value=FakeProcess(lines)):
            snapshot = usage_cap.read_codex_rate_limits(timeout_seconds=1)
        self.assertEqual(snapshot["effective_used_percent"], 44.0)

    def test_primary_only_secondary_only_and_lookup_normalize(self) -> None:
        primary = usage_cap.normalize_rate_limit_response({"result": {"limit_id": "codex", "primary": {"usedPercent": 20}}})
        secondary = usage_cap.normalize_rate_limit_response({"result": {"limitId": "codex", "secondary": {"usedPercent": 70}}})
        lookup = usage_cap.normalize_rate_limit_response(
            {"result": {"rateLimitsByLimitId": {"codex": {"secondary": {"usedPercent": 81}}}}},
            limit_id="codex",
        )
        self.assertEqual(primary["effective_used_percent"], 20.0)
        self.assertEqual(secondary["effective_used_percent"], 70.0)
        self.assertEqual(lookup["effective_used_percent"], 81.0)

    def test_malformed_no_response_and_timeout_failures(self) -> None:
        with mock.patch.object(usage_cap.subprocess, "Popen", return_value=FakeProcess(["not-json\n"])):
            with self.assertRaises(usage_cap.UsageCapError):
                usage_cap.read_codex_rate_limits(timeout_seconds=1)
        with mock.patch.object(usage_cap.subprocess, "Popen", return_value=FakeProcess([json_line({"jsonrpc": "2.0", "id": 2, "result": {"limit_id": "codex"}})])):
            with self.assertRaises(usage_cap.UsageCapError):
                usage_cap.read_codex_rate_limits(timeout_seconds=1)
        with mock.patch.object(usage_cap.subprocess, "Popen", return_value=FakeProcess([])):
            with self.assertRaises(usage_cap.UsageCapError):
                usage_cap.read_codex_rate_limits(timeout_seconds=0.01)


if __name__ == "__main__":
    unittest.main()
