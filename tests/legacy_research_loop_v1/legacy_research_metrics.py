from __future__ import annotations

import unittest

from research.loop import metrics


def beats(candidate: float, baseline: float, direction: str) -> bool:
    if hasattr(metrics, "beats_baseline"):
        return bool(metrics.beats_baseline(candidate, baseline, direction))
    if hasattr(metrics, "compare_metric"):
        result = metrics.compare_metric(candidate=candidate, baseline=baseline, direction=direction)
        return bool(getattr(result, "beats_baseline", result if isinstance(result, bool) else result.get("beats_baseline")))
    if hasattr(metrics, "MetricComparison"):
        return bool(metrics.MetricComparison(metric_direction=direction).beats_baseline(candidate, baseline))
    raise AssertionError("research.loop.metrics must expose beats_baseline/compare_metric behavior")


def threshold(candidate: float, limit: float, direction: str) -> bool:
    for name in ("meets_threshold", "threshold_passed", "threshold_passes"):
        func = getattr(metrics, name, None)
        if func is not None:
            return bool(func(candidate, limit, direction))
    raise AssertionError("research.loop.metrics must expose direction-aware threshold comparison")


class MetricTests(unittest.TestCase):
    def test_metric_comparison_supports_maximize_and_minimize(self) -> None:
        cases = [
            (0.61, 0.60, "maximize", True),
            (0.59, 0.60, "maximize", False),
            (0.39, 0.40, "minimize", True),
            (0.41, 0.40, "minimize", False),
        ]
        for candidate, baseline, direction, expected in cases:
            with self.subTest(candidate=candidate, baseline=baseline, direction=direction):
                self.assertIs(beats(candidate, baseline, direction), expected)

    def test_metric_threshold_uses_declared_direction(self) -> None:
        cases = [
            (0.80, 0.75, "maximize", True),
            (0.70, 0.75, "maximize", False),
            (0.20, 0.25, "minimize", True),
            (0.30, 0.25, "minimize", False),
        ]
        for candidate, limit, direction, expected in cases:
            with self.subTest(candidate=candidate, limit=limit, direction=direction):
                self.assertIs(threshold(candidate, limit, direction), expected)


if __name__ == "__main__":
    unittest.main()
