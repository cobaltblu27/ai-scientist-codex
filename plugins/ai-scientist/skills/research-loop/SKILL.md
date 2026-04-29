---
name: research-loop
description: Execute bounded Codex-native experiment loops with dependency planning, API ledgers, strictness modes, and fail-closed .ai-scientist/ phase gates.
---

# Research Loop

Use this skill to run selected ideas against a target boilerplate repository while preserving benchmark and split integrity.

## Required artifacts

All run state lives under `.ai-scientist/`, including `run-status.json`, `handoff.jsonl`, `verifier-decision.json`, `principles.json`, `dependency-plan.json`, and `api-ledger.jsonl`.

## Strictness modes

Default mode is `scientist`.

- `scientist`: multi-seed reproducibility, strict ablation, hypothesis-causality evidence, leakage/split checks, and no cherry-picking.
- `researcher`: reproducibility, meaningful ablation, leakage/split checks, and limited pragmatic tuning after hypothesis validation.
- `balanced`: baseline beat, leakage/split checks, and lightweight ablation or sensitivity evidence.
- `builder`: credible held-out score, baseline beat, leakage/split checks, and practical tuning disclosure.
- `engineer`: strong credible score, fixed benchmark/split, leakage checks, and a selection/tuning log.

No mode permits leakage, split manipulation, or deceptive scoring.

## Dependency and API controls

1. Pre-loop dependency planning is mandatory. Propose a full useful dependency list in `dependency-plan.json` before implementation.
2. Every planned dependency must be marked `approved`, `rejected`, or `not_needed` before research starts.
3. User-supervised approval is required before installing dependencies.
4. During the loop, newly needed dependencies require one approval per package and are remembered per run.
5. API calls are autonomous only within configured phase budgets, logged to `api-ledger.jsonl`, and cached where practical. `S2_API_KEY` is optional and must never be hardcoded.

## Workflow

1. Map the target repo, dataset, loader, benchmark, and split policy. Add missing dataset/loader scaffolding only when necessary and only when it preserves the intended benchmark and split.
2. Create a baseline node with command log and metrics.
3. For each experiment node, record bounded responsibility, command log, metrics, split integrity evidence, leakage evidence, result summary, and mode deliverables.
4. Keep a journal of decisions and rejected alternatives in `journal.json`.
5. Use Codex subagents only for bounded, auditable work such as repo mapping, experiment implementation, fixture validation, gate verification, security review, or scientific critique.
6. Before phase transition, run `plugins/ai-scientist/scripts/validate_run.py <target> --gate research_to_review`.
7. Any non-zero validator exit blocks the next phase. Do not proceed to review until the validator passes and an approved `handoff.jsonl` record exists.

## Completion

Return the selected node, baseline comparison, leakage/split status, strictness mode, validation command, and artifact paths.
