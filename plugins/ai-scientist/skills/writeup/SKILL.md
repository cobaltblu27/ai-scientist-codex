---
name: writeup
description: Create a final report from accepted AI Scientist artifacts with disclosure, limitations, mode/split details, and negative-result handling.
---

# Writeup

Use this skill only after review artifacts and launch checks are available.

## Requirements

- Include an explicit AI Scientist disclosure section stating that Codex assisted ideation, experimentation, review, and/or writing.
- State the strictness mode and benchmark/split exactly as recorded in `.ai-scientist/config.json` and `run-status.json`.
- Include result limitations, failed attempts, and known validity threats.
- Handle negative or failed results honestly; do not present rejected or engineer-mode outcomes as scientist-mode research claims.
- Reference command logs, metrics, split integrity evidence, leakage evidence, baseline comparison, structured review, and verifier decision.

## Workflow

1. Confirm `plugins/ai-scientist/scripts/validate_run.py <target> --gate launch` passes.
2. Read accepted artifacts and structured review.
3. Draft the report with abstract, setup, method, evidence, limitations, disclosure, and reproducibility appendix.
4. If `verifier-decision.json` is missing, `no_go`, or has blockers, produce only a failed/negative run summary and do not claim launch approval.
5. Record final report path in `journal.json` and summarize the artifact trail.
