#!/usr/bin/env python3
"""Compatibility entrypoint for hook-driven AI Scientist ideation.

The ideation loop now runs in the live Codex session through plugin hooks and
durable `.ai-scientist/` state. This module keeps the historical entrypoint
available for local initialization and tests, but it does not launch nested
Codex agents.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ideation_state import IDEA_OUTPUT_SCHEMA, IDEATION_PROTOCOL, initialize_ideation, next_instruction

DEFAULT_CODEX_IDEATION_MODEL = "gpt-5.5"
DEFAULT_CODEX_IDEATION_REASONING_EFFORT = "xhigh"


def build_proposal_prompt(prompt: str, idea_id: str, strictness_mode: str, previous_ideas: list[dict[str, Any]]) -> str:
    return f"""{IDEATION_PROTOCOL}

Goal prompt:
{prompt}

Strictness mode: {strictness_mode}
Idea id: {idea_id}
Already finalized ideas:
{json.dumps(previous_ideas, indent=2)}

Generate one distinct proposal and choose SearchSemanticScholar before attempting FinalizeIdea.
Avoid thin metric-improvement tickets; include scientific insight, related work, execution plan,
baseline, ablations, leakage/split considerations, and concrete minimum evidence.
"""


def build_reflection_prompt(
    prompt: str,
    idea_id: str,
    strictness_mode: str,
    current_idea: dict[str, Any],
    search_results: list[dict[str, Any]],
    reflection_round: int,
    num_reflections: int,
    previous_reflections: list[dict[str, Any]],
) -> str:
    return f"""{IDEATION_PROTOCOL}

Goal prompt:
{prompt}

Strictness mode: {strictness_mode}
Idea id: {idea_id}
Reflection round: {reflection_round}/{num_reflections}

Current idea:
{json.dumps(current_idea, indent=2)}

Semantic Scholar search results:
{json.dumps(search_results, indent=2)}

Previous reflections:
{json.dumps(previous_reflections, indent=2)}

Reflect on novelty, feasibility, baseline, ablations, leakage/split risk, and execution detail.
Then either choose SearchSemanticScholar with a better query or FinalizeIdea with a schema-complete idea.
"""


def build_finalization_prompt(
    prompt: str,
    idea_id: str,
    strictness_mode: str,
    current_idea: dict[str, Any],
    reflection_history: list[dict[str, Any]],
    reflection_round: int,
    num_reflections: int,
) -> str:
    return f"""{IDEATION_PROTOCOL}

Goal prompt:
{prompt}

Strictness mode: {strictness_mode}
Idea id: {idea_id}
Reflection round: {reflection_round}/{num_reflections}

Current refined idea:
{json.dumps(current_idea, indent=2)}

Reflection history:
{json.dumps(reflection_history, indent=2)}

Use FinalizeIdea only if the idea is proposal-grade and cites searched related work.
Otherwise continue reflection with SearchSemanticScholar or skip only when the idea is unsalvageable.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", help="Research prompt. If omitted, stdin is used.")
    parser.add_argument("--target-repo", type=Path, default=Path.cwd())
    parser.add_argument("--run-id")
    parser.add_argument("--strictness-mode", default="scientist")
    parser.add_argument("--benchmark", default="unspecified")
    parser.add_argument("--split-policy", default="Preserve the declared benchmark split; clarify before research if unspecified.")
    parser.add_argument("--num-ideas", type=int, default=10)
    parser.add_argument("--num-reflections", type=int, default=5)
    args = parser.parse_args()

    prompt = args.prompt or sys.stdin.read().strip()
    if not prompt:
        raise SystemExit("ERROR: provide --prompt or pipe a prompt on stdin")
    state = initialize_ideation(
        args.target_repo,
        prompt,
        run_id=args.run_id,
        strictness_mode=args.strictness_mode,
        benchmark=args.benchmark,
        split_policy=args.split_policy,
        target_num_ideas=args.num_ideas,
        max_reflections=args.num_reflections,
    )
    print(json.dumps({"run_id": state["run_id"], "state_path": f".ai-scientist/runs/{state['run_id']}/ideation-state.json", "instruction": next_instruction(state)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
