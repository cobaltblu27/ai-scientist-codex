# AI Scientist Artifact Contract

Target repositories keep all plugin state in `.ai-scientist/` so ordinary project files remain auditable separately from research governance artifacts. The plugin is Codex-native and must not import, invoke, shell into, or wrap `AI-Scientist-v2` at runtime.

## Required root artifacts

- `.ai-scientist/config.json` — target repository path, strictness mode, benchmark/split policy, API budgets, optional root defaults, and optional metric contract defaults. Fresh research targets create this non-destructively; existing files are preserved unless explicitly updated by the orchestrator.
- `.ai-scientist/ideas/ideas.json` — array of structured candidate ideas. Ideation-produced ideas are proposal-grade records with `hypothesis`, `scientific_insight`, required `related_work`, `abstract`, `novelty_rationale`, executable `execution_plan`, `experiments`, `risks`, and `minimum_evidence`. Fresh research targets bootstrap this from `--idea-json`; existing registries must not be deleted.
- Optional root mirrors/summaries: `.ai-scientist/dependency-plan.json`, `.ai-scientist/dependency-status.json`, `.ai-scientist/api-ledger.jsonl`, and `.ai-scientist/principles.json`. These are supplementary only; run-owned governance artifacts are authoritative for validation.
- `.ai-scientist/logs/<run-id>/ideation-run.json` and `.ai-scientist/logs/<run-id>/agents/*.json` — ideation audit logs when the ideation flow is used.
- `.ai-scientist/logs/<run-id>/semantic-scholar-cache/*.json` — cached Semantic Scholar search results keyed by query hash when that API is enabled.

## Required run artifacts

Every active run under `.ai-scientist/runs/<run-id>/` owns the authoritative artifacts for that run:

- `research-plan.json` — selected idea/run plan, `strictness_mode`, `metric_key`, `metric_direction` (`maximize` or `minimize`), optional `success_threshold`, split policy, baseline command, and mode requirements.
- `dependency-plan.json` — requested packages/system tools.
- `dependency-status.json` — approval state for requested dependencies. Unapproved or blocked dependencies prevent research handoff.
- `api-ledger.jsonl` — append-only API/model usage audit, including an explicit no-calls entry for fixture/offline runs.
- `principles.json` — run-owned principles derived from target-root `GUIDELINES.md`, CLI options, and idea metadata. `GUIDELINES.md` means the target repository file, not plugin-local docs.
- `baseline/` — `command.log`, `metrics.json`, `split_integrity.json`, `leakage_check.json`, and `runtime-mutation-check.json`.
- `nodes/<node-id>/` — experiment node artifacts listed below.
- `dispatcher-events.jsonl` — append-only FIFO/resource scheduling events.
- `selection.json` — selected node, declared metric contract, baseline metric, selected metric, comparison operator, threshold result when present, lineage, artifact snapshot, and reason.
- `journal.json` — chronological decisions, commands, observations, failures, and rationale.
- `run-status.json` — active phase/status, strictness mode, selected node, legacy `last_validation`, and authoritative plural `last_validations.<gate>`. New writers should write both; validators read plural first and use singular only as compatibility fallback.
- `handoff.jsonl` — append-only phase transition approvals.
- `verifier-decisions/research_to_review.json` — gate-specific research handoff decision using `approved`, `blocked`, or `rejected`.
- `verifier-decision.json` — existing launch/final decision using `go` or `no_go`; it is not a research handoff artifact and must not be overloaded.

## Experiment node contract

Each `.ai-scientist/runs/<run-id>/nodes/<node-id>/` directory must contain:

- `node.json` — node id, parent id, action (`draft`, `debug`, `improve`, `tuning`, or `ablation`), strictness mode, and status.
- `prompt.json` — prompt metadata emitted before agent execution: action, strictness mode, node id, parent node id, template id/version, idea metadata, metric contract, split policy, root guidance summary/presence, required deliverables, and expected manifest schema version. Prompts instruct manifest-only output; Codex does not write directly to the target repo.
- `agent-manifest.json` and `manifest-validation.json` — read-only Codex/fixture manifest and Python validation result before materialization.
- `workspace/` — node-local materialized generated files.
- `command.log` — command, exit code, and relevant output paths.
- `metrics.json` — must include the declared `metric_key`; optional `score` is only a compatibility alias.
- `split_integrity.json` and `leakage_check.json` — pass/fail split and leakage evidence.
- `result_summary.json` — result, limitations, and baseline comparison.
- `mode_deliverables.json` — active strictness-mode deliverables.
- `resource_usage.json` — bounded CPU/GPU/memory/time usage evidence.
- `runtime-mutation-check.json` — pass/fail evidence that commands did not mutate unexpected repository paths outside `.ai-scientist/`/the node workspace.

## Metric and selection contract

Research validation is direction-aware:

- `research-plan.json`, `selection.json`, and validation metadata record `metric_key` and `metric_direction`.
- For `maximize`, selected metric must be greater than baseline; threshold success means selected metric is `>= success_threshold`.
- For `minimize`, selected metric must be lower than baseline; threshold success means selected metric is `<= success_threshold`.
- Validators compare the selected node named by `selection.json`; they do not choose the max score across all nodes.
- Optional `score` may mirror the declared metric for compatibility but is not authoritative when `metric_key` is declared.

## Phase gates

All phase transitions run `scripts/validate_run.py`. A non-zero validator exit blocks the next phase.

### Ideation to research

Requires ideas, config, dependency approval statuses, initialized API ledger, current run status validation, an approved handoff, and retained ideation orchestration logs under `.ai-scientist/logs/<run-id>/` when ideation produced the run.

### Research to review: two-phase protocol

Research handoff uses separate evidence and final validation modes to avoid circularity.

1. Evidence validation, before handoff exists:

   ```bash
   python3 plugins/ai-scientist/scripts/validate_run.py <target> \
     --gate research_to_review --run-id <run-id> --validation-mode evidence
   ```

   Evidence mode checks scientific and artifact evidence only: governance artifacts, research plan, baseline/node metrics, selected-node direction-aware comparison, threshold semantics, split/leakage checks, prompt/action/mode metadata, mode deliverables, resource usage, dispatcher events, runtime mutation evidence, and selection freshness. It intentionally does **not** require `last_validation`, `handoff.jsonl`, or a gate-specific verifier decision.

2. After evidence validation succeeds, writers record validation metadata in both `run-status.json.last_validation` and `run-status.json.last_validations.research_to_review`, then append an approved `handoff.jsonl` record for `research_to_review`.

3. The verifier/finalizer writes `verifier-decisions/research_to_review.json` with `decision: "approved"` only when the approved handoff and the evidence snapshot are acceptable. `blocked` or `rejected` prevent final validation.

4. Final transition validation:

   ```bash
   python3 plugins/ai-scientist/scripts/validate_run.py <target> \
     --gate research_to_review --run-id <run-id> --validation-mode final
   ```

   Final mode reruns evidence checks and additionally requires current successful validation metadata, an approved handoff, and an approved gate-specific verifier decision referencing the same snapshot. `--validation-mode final` is the default for backward-compatible CLI behavior.

### Review to writeup

Requires structured review, verdict, leakage/split/baseline/mode criteria coverage, current run status validation, and an approved handoff. Rejected runs must block writeup or be clearly marked as failed/negative.

### Launch

Requires `verifier-decision.json` with `decision: "go"` and no blockers. Launch validation preserves the existing `go`/`no_go` semantics and does not inspect `verifier-decisions/research_to_review.json`.
