---
name: review
description: Review AI Scientist run evidence for leakage, split integrity, baseline comparison, strictness-mode criteria, and a structured verdict.
---

# Review

Use this skill after research-loop artifacts are complete and before writeup.

## Required review checks

- split integrity evidence for every accepted node.
- leakage evidence for every accepted node.
- Baseline comparison using the declared benchmark metric and split.
- Strictness-mode criteria for `scientist`, `researcher`, `balanced`, `builder`, or `engineer` as declared in `run-status.json`.
- Command/evidence trail for claimed scores.
- A verdict: accept, revise, reject, or negative-result.

## Workflow

1. Read `.ai-scientist/config.json`, `run-status.json`, node evidence, and `journal.json`.
2. Confirm benchmark/split was not changed unless explicitly part of setup.
3. Confirm no train/test leakage and no deceptive metric selection.
4. Compare best accepted node to baseline and check mode-specific criteria.
5. Write `.ai-scientist/runs/<run-id>/review/structured-review.json` with sections for leakage, split integrity, baseline comparison, strictness-mode criteria, limitations, and verdict.
6. Run `ai-scientist validate run <target> --gate review_to_writeup`.
7. Any rejection blocks writeup unless the writeup is clearly marked failed/negative.

## Output

Report verdict, blockers, evidence paths, and whether writeup is allowed.
