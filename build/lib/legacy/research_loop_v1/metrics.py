from __future__ import annotations

from typing import Any


def metric_value(metrics: dict[str, Any], key: str) -> float:
    if key not in metrics:
        raise ValueError(f"metrics missing declared key: {key}")
    try:
        return float(metrics[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metric {key} must be numeric") from exc


def beats_baseline(candidate: float, baseline: float, direction: str) -> bool:
    if direction == "maximize":
        return candidate > baseline
    if direction == "minimize":
        return candidate < baseline
    raise ValueError(f"unknown metric direction: {direction}")


def threshold_passes(candidate: float, threshold: float | None, direction: str) -> bool:
    if threshold is None:
        return True
    if direction == "maximize":
        return candidate >= threshold
    if direction == "minimize":
        return candidate <= threshold
    raise ValueError(f"unknown metric direction: {direction}")


def comparison_symbol(direction: str) -> str:
    return ">" if direction == "maximize" else "<"
