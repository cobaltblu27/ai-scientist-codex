---
name: writeup
description: Create a final report from accepted AI Scientist artifacts with disclosure, limitations, split details, figures, and negative-result handling.
---

# Writeup

<Purpose>

Use this skill only after `review_to_writeup` validation and approved handoff are recorded for the run.

</Purpose>

<Requirements>

## Requirements

- Run `ai-scientist --target-repo <target> writeup doctor` first. If it reports missing Python or TeX dependencies, stop and ask the user to install them.
- Include at least one final-paper plot. The default helper creates `writeup/figures/generated/baseline-vs-selected.png` from the accepted run metrics.
- Include an explicit AI Scientist disclosure section stating that Codex assisted ideation, experimentation, review, and/or writing.
- State the benchmark and split exactly as recorded in the run artifacts and structured review.
- Include result limitations, failed attempts, known validity threats, split integrity evidence, leakage evidence, baseline comparison, and reproducibility artifacts.
- Handle negative or failed results honestly; do not present rejected outcomes as supported research claims.

</Requirements>

<Workflow>

## Workflow

1. Start state: `ai-scientist --target-repo <target> writeup start --run-id <run-id>`.
2. Generate figures: `... writeup collect-figures --run-id <run-id>`.
3. Draft `writeup/report.md` and `writeup/latex/template.tex`; both must reference every required figure and include disclosure plus limitations.
4. Record the drafts: `... writeup record-reports --run-id <run-id>`.
5. Compile PDF: `... writeup compile --run-id <run-id>`. If TeX dependencies are missing, stop and ask the user to install them; do not mark positive launch writeup complete without a PDF.
6. Start or complete final audit: `... writeup audit-start --run-id <run-id>`, then record an independent JSON verdict with `... writeup audit-complete --run-id <run-id> --json '{"verdict":"ACCEPT",...}'`.
7. Complete writeup: `... writeup complete --run-id <run-id>`.
8. Run `ai-scientist validate run <target> --gate launch --run-id <run-id>`.
9. Record validation and handoff: `... validation record --gate launch --exit-code 0`, then `... handoff record --gate launch --exit-code 0 --approved`.

If the result is rejected, impossible to write honestly, or blocked by missing evidence, use `writeup negative-complete --reason <reason>` and do not claim launch approval.

</Workflow>
