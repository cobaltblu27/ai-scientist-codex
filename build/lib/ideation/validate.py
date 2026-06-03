#!/usr/bin/env python3
"""Strict deterministic checks for finalized ideation proposals."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from ideation.state import IDEA_OUTPUT_SCHEMA

PROPOSAL_GRADE_REQUIRED = [
    "title",
    "hypothesis",
    "scientific_insight",
    "related_work",
    "abstract",
    "novelty_rationale",
    "required_data",
    "expected_metric",
    "execution_plan",
    "experiments",
    "risks",
    "minimum_evidence",
]

MEASURABLE_TERMS = re.compile(
    r"\b(metric|accuracy|loss|error|rmse|mae|pearson|spearman|auc|f1|precision|recall|score|latency|throughput|perplexity|bleu|rouge|calibration|correlation)\b",
    re.IGNORECASE,
)
EXPERIMENT_TERMS = re.compile(r"\b(run|train|evaluate|compare|ablate|measure|test|baseline|control)\b", re.IGNORECASE)
RISK_TERMS = re.compile(r"\b(fail|risk|leak|overfit|confound|bias|unstable|negative|invalid|spurious|limitation)\b", re.IGNORECASE)
ACCEPTANCE_TERMS = re.compile(r"\b(command|run|metric|threshold|pass|compare|baseline|artifact|evidence|evaluate|validation)\b", re.IGNORECASE)
DATASET_TERMS = re.compile(r"\b(dataset|data|benchmark|split|corpus|table|sample|train|test|validation)\b", re.IGNORECASE)
MODEL_TERMS = re.compile(r"\b(model|architecture|baseline|method|network|estimator|classifier|regressor|transformer|encoder)\b", re.IGNORECASE)
EVAL_TERMS = re.compile(r"\b(evaluation|metric|held-out|test|validation|score|measure|compare)\b", re.IGNORECASE)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def normalize_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def search_cache_titles(search_files: list[Path]) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for path in search_files:
        payload = load_json(path)
        for result in normalize_list(payload.get("results")):
            if isinstance(result, dict) and result.get("title"):
                title = str(result["title"])
                key = title.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    titles.append(title)
    return titles


def title_is_cited(title: str, related_work: str) -> bool:
    related = related_work.lower()
    title_l = title.lower()
    if title_l in related:
        return True
    words = [word for word in re.findall(r"[a-z0-9]+", title_l) if len(word) > 3]
    if len(words) >= 3 and all(word in related for word in words[:3]):
        return True
    return False


def schema_minimum_errors(idea: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    compact = all(field in idea for field in IDEA_OUTPUT_SCHEMA["required"])
    required = IDEA_OUTPUT_SCHEMA["required"] if compact else PROPOSAL_GRADE_REQUIRED
    for field in required:
        if field not in idea:
            errors.append(f"missing required field: {field}")
    if compact:
        for field in ["title", "hypothesis", "unique_protocol", "expected_metric", "family_key"]:
            if field in idea and not str(idea[field]).strip():
                errors.append(f"field must not be empty: {field}")
        if not isinstance(idea.get("smoke_runnable_now"), bool):
            errors.append("smoke_runnable_now must be boolean")
        for field in ("requires_implementation", "evidence_refs", "risk_flags"):
            if field in idea and not isinstance(idea[field], list):
                errors.append(f"{field} must be a list")
        if "rubric_scores" in idea and not isinstance(idea.get("rubric_scores"), dict):
            errors.append("rubric_scores must be an object")
        return errors
    for field in ["title", "hypothesis", "scientific_insight", "related_work", "abstract", "novelty_rationale", "required_data", "expected_metric"]:
        if field in idea and not str(idea[field]).strip():
            errors.append(f"field must not be empty: {field}")
    if len(normalize_list(idea.get("execution_plan"))) < 4:
        errors.append("execution_plan must contain at least 4 steps")
    for index, step in enumerate(normalize_list(idea.get("execution_plan")), start=1):
        if not isinstance(step, dict):
            errors.append(f"execution_plan step {index} must be an object")
            continue
        for field in ("dataset", "model", "evaluation"):
            if not str(step.get(field, "")).strip():
                errors.append(f"execution_plan step {index} missing {field}")
    if len(normalize_list(idea.get("experiments"))) < 2:
        errors.append("experiments must contain at least 2 concrete experiments")
    if len(normalize_list(idea.get("risks"))) < 2:
        errors.append("risks must contain at least 2 failure modes")
    if len(normalize_list(idea.get("minimum_evidence"))) < 4:
        errors.append("minimum_evidence must contain at least 4 acceptance criteria")
    return errors


def validate_idea(idea: dict[str, Any], search_files: list[Path]) -> list[str]:
    errors = schema_minimum_errors(idea)
    hypothesis = str(idea.get("hypothesis", ""))
    if not MEASURABLE_TERMS.search(hypothesis):
        errors.append("hypothesis must name a measurable dependent variable or metric")
    compact = all(field in idea for field in IDEA_OUTPUT_SCHEMA["required"])
    if compact:
        if len(str(idea.get("unique_protocol", "")).split()) < 4:
            errors.append("unique_protocol must describe a concrete protocol")
        if idea.get("smoke_runnable_now") is True and not str(idea.get("minimum_command") or "").strip():
            errors.append("smoke_runnable_now requires minimum_command")
        return errors

    concrete_experiments = [str(exp) for exp in normalize_list(idea.get("experiments")) if EXPERIMENT_TERMS.search(str(exp)) and len(str(exp).split()) >= 8]
    if len(concrete_experiments) < 2:
        errors.append("experiments must include at least 2 concrete runnable comparisons")

    titles = search_cache_titles(search_files)
    related_work = str(idea.get("related_work", ""))
    cited_count = sum(1 for title in titles if title_is_cited(title, related_work))
    if cited_count < 2:
        errors.append("related_work must cite at least 2 papers from the Semantic Scholar search cache")

    failure_modes = [str(risk) for risk in normalize_list(idea.get("risks")) if RISK_TERMS.search(str(risk))]
    if len(failure_modes) < 2:
        errors.append("risks must include at least 2 concrete failure modes")

    evidence = " ".join(str(item) for item in normalize_list(idea.get("minimum_evidence")))
    if not ACCEPTANCE_TERMS.search(evidence):
        errors.append("minimum_evidence must name executable acceptance criteria")

    plan_text = " ".join(json.dumps(step, sort_keys=True) if isinstance(step, dict) else str(step) for step in normalize_list(idea.get("execution_plan")))
    if not DATASET_TERMS.search(plan_text):
        errors.append("execution_plan must include dataset or benchmark details")
    if not MODEL_TERMS.search(plan_text):
        errors.append("execution_plan must include model or method details")
    if not EVAL_TERMS.search(plan_text):
        errors.append("execution_plan must include evaluation details")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idea-json", type=Path, required=True)
    parser.add_argument("--search-cache", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    idea = load_json(args.idea_json)
    errors = validate_idea(idea, args.search_cache)
    print(json.dumps({"ok": not errors, "errors": errors}, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
