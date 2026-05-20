---
name: ideation
description: Generate structured research ideas from a prompt and initialize non-mutating .ai-scientist/ ideation artifacts for a target repository.
---

# Ideation

Use this skill when the user wants research ideas, hypotheses, or experiment proposals before running a research loop. This skill is backed by hook-driven state helpers under `plugins/ai-scientist/scripts/`; Codex performs the reasoning in the live session and Python owns only deterministic state, search, validation, and artifact writes.

## Inputs

- A prompt input describing the research goal, target benchmark, constraints, and desired strictness mode.
- Optional target repository path for artifact placement.
- Optional literature lookup budget. `S2_API_KEY` is optional; without it, Semantic Scholar may apply stricter rate limits.
- Optional `num_ideas` and `num_reflections` settings. Defaults are `10` ideas and `5` reflection rounds per idea.

## Workflow

1. Start ideation only from an explicit marker: `/ideate ...`, `$ai-scientist ideate ...`, or `ai-scientist: ideate ...`.
2. Clarify the benchmark, dataset/split policy, and default strictness mode (`scientist`) when missing.
3. Do not mutate target repo code during ideation. The only permitted target repo writes are `.ai-scientist/` artifacts.
4. Follow the hook-injected action protocol: return exactly one `SearchSemanticScholar`, `FinalizeIdea`, or explicit skip action per turn. Do not launch nested Codex sessions.
5. The hook state machine records every action, reflection, draft, search cache, and ledger entry. Stop-hook continuation is bounded by `max_stop_continuations` and repeated-block counters.
6. Semantic Scholar lookup is performed by Python one query at a time and logged to `.ai-scientist/runs/<run-id>/api-ledger.jsonl`.
7. Finalized ideas are written to `.ai-scientist/ideas/ideas.json` using the idea schema. A finalized idea must include a falsifiable hypothesis, scientific insight, related work grounded in search cache, conference-style abstract, novelty rationale, required data, expected metric, execution plan with dataset/model/evaluation fields, experiments, risks, and minimum evidence.
8. Finalization checks filesystem diff, state transitions, cached citations, idea quality, canonical schemas, and `plugins/ai-scientist/scripts/validate_run.py <target> --gate ideation_to_research --run-id <run-id>`.

## Output contract

Return a concise idea summary and artifact paths. The canonical ideas output is JSON in `.ai-scientist/ideas/ideas.json`; prose summaries are secondary and must not replace the JSON artifact.

Key generated paths:

- `.ai-scientist/ideas/ideas.json`
- `.ai-scientist/state/active-ideation.json`
- `.ai-scientist/runs/<run-id>/ideation-state.json`
- `.ai-scientist/runs/<run-id>/actions/*.json`
- `.ai-scientist/runs/<run-id>/drafts/*.json`
- `.ai-scientist/runs/<run-id>/reflections/*.md`
- `.ai-scientist/logs/<run-id>/ideation-run.json`
- `.ai-scientist/runs/<run-id>/api-ledger.jsonl`
- `.ai-scientist/runs/<run-id>/run-status.json`
- `.ai-scientist/runs/<run-id>/handoff.jsonl`
