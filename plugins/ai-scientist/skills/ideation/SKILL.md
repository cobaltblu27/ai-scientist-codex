---
name: ideation
description: Generate structured research ideas from a prompt and initialize non-mutating .ai-scientist/ ideation artifacts for a target repository.
---

# Ideation

Use this skill when the user wants research ideas, hypotheses, or experiment proposals before running a research loop.

## Inputs

- A prompt input describing the research goal, target benchmark, constraints, and desired strictness mode.
- Optional target repository path for artifact placement.
- Optional literature lookup budget. `S2_API_KEY` may be used only when literature search is needed and only within the configured API budget.

## Workflow

1. Clarify the benchmark, dataset/split policy, and default strictness mode (`scientist`) when missing.
2. Do not mutate target repo code during ideation. The only permitted target repo writes are `.ai-scientist/` artifacts.
3. Create or update `.ai-scientist/config.json` with strictness mode, target repo path, benchmark/split policy, and API budgets.
4. Produce `.ai-scientist/ideas/ideas.json` as JSON with stable idea ids, hypothesis, novelty rationale, required data, expected metric, risks, and minimum evidence.
5. If Semantic Scholar lookup is configured, log each request or cache hit to the active run `api-ledger.jsonl` and stop before exceeding the phase budget.
6. Draft a dependency-plan placeholder for likely packages, but do not install anything.
7. Run `plugins/ai-scientist/scripts/validate_run.py <target> --gate ideation_to_research` before handing off to research.

## Output contract

Return a concise idea summary and artifact paths. The canonical ideas output is JSON in `.ai-scientist/ideas/ideas.json`; prose summaries are secondary and must not replace the JSON artifact.
