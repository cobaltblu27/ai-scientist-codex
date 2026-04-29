# AI Scientist Artifact Contract

Target repositories keep all plugin state in `.ai-scientist/` so ordinary project files remain auditable separately from research governance artifacts.

## Required root artifacts

- `.ai-scientist/config.json` — target repository path, strictness mode, benchmark/split policy, API budgets, optional `S2_API_KEY` enablement flag, and cache paths.
- `.ai-scientist/ideas/ideas.json` — array of structured candidate ideas from `ideation`.
- `.ai-scientist/runs/<run-id>/dependency-plan.json` — planned packages and per-package status: `approved`, `rejected`, or `not_needed`.
- `.ai-scientist/runs/<run-id>/api-ledger.jsonl` — one JSON object per API call or cache hit, including phase, provider, budget, and cache key where applicable.
- `.ai-scientist/runs/<run-id>/journal.json` — chronological decisions, commands, observations, and rationale.
- `.ai-scientist/runs/<run-id>/run-status.json` — active phase, status, strictness mode, selected node, and `last_validation`.
- `.ai-scientist/runs/<run-id>/handoff.jsonl` — append-only phase transition approvals.
- `.ai-scientist/runs/<run-id>/verifier-decision.json` — final `go`/`no_go`, checks, evidence, and blockers.
- `.ai-scientist/runs/<run-id>/principles.json` — traceability from governance principles to gates and evidence artifacts.

## Experiment node contract

Each `.ai-scientist/runs/<run-id>/nodes/<node-id>/` directory should contain:

- `command.log` with command, exit code, and relevant output path.
- `metrics.json` using the declared benchmark metric.
- `split_integrity.json` with fixed benchmark/split evidence and pass/fail status.
- `leakage_check.json` with leakage checks and pass/fail status.
- `result_summary.json` explaining the result, limitations, and comparison to baseline.
- `mode_deliverables.json` covering the active strictness mode requirements.

## Phase gates

All phase transitions run `scripts/validate_run.py`. A non-zero validator exit blocks the next phase.

### Ideation to research

Requires ideas, config, dependency approval statuses, initialized API ledger, current run status validation, and an approved handoff.

### Research to review

Requires baseline metrics, command logs, at least one experiment node, split integrity evidence, leakage evidence, baseline beat, active-mode deliverables, current run status validation, and an approved handoff.

### Review to writeup

Requires structured review, verdict, leakage/split/baseline/mode criteria coverage, current run status validation, and an approved handoff. Rejected runs must block writeup or be clearly marked as failed/negative.

### Launch

Requires `verifier-decision.json` with `decision: "go"` and no blockers.
