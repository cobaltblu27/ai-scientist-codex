---
name: review
description: Explicit-only final AI Scientist run-level evidence review; do not use for idea, draft, node, revision, paper, or code critic/review tasks. DO NOT USE; this skill is explicit-usuage ONLY.
---

# Review

<Use_When>
Use this skill ONLY when the user explicitly triggers the AI Scientist review skill for a final run-level review. This skill audits completed AI Scientist artifacts after the research loop, and after writeup when a writeup exists, to decide whether the run evidence supports the claimed outcome.
</Use_When>

<Do_Not_Use_When>
- Do not use this skill just because an agent is told to review, critique, score, or evaluate an idea.
- Do not use this skill for ideation critic subagents, research-loop node critics, revision critics, paper reviewers, or generic code review.
- Do not use this skill before the run-level artifacts needed for final evidence review exist; use the ideation critic prompt or active phase skill instead.
</Do_Not_Use_When>

<Purpose>

Use this skill for the explicit run-level review phase after research-loop artifacts are complete. In the normal pipeline this gates writeup; if a writeup already exists, use it only as additional evidence for final run-level review.

</Purpose>

<Required_Review_Checks>

## Required review checks

- split integrity evidence for every accepted node.
- leakage evidence for every accepted node.
- Baseline comparison using the declared benchmark metric and split.
- Scientific acceptance criteria declared in the research contract and selection evidence.
- Command/evidence trail for claimed scores.
- A verdict: accept, revise, reject, or negative-result.

</Required_Review_Checks>

<Workflow>

## Workflow

1. Read `.ai-scientist/config.json`, `run-status.json`, node evidence, and `journal.json`.
2. Confirm benchmark/split was not changed unless explicitly part of setup.
3. Confirm no train/test leakage and no deceptive metric selection.
4. Compare the best accepted node to the baseline and check the contract's scientific acceptance criteria.
5. Write `.ai-scientist/runs/<run-id>/review/structured-review.json` with sections for leakage, split integrity, baseline comparison, scientific acceptance criteria, limitations, and verdict.
6. Run `ai-scientist validate run <target> --gate review_to_writeup`.
7. Any rejection blocks writeup unless the writeup is clearly marked failed/negative.

</Workflow>

<Output>

## Output

Report verdict, blockers, evidence paths, and whether writeup is allowed.

</Output>
