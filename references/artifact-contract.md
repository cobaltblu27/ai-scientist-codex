# AI Scientist Artifact Contract

Target repositories keep all plugin state in `.ai-scientist/` so ordinary project files remain auditable separately from research governance artifacts.

## Required root and run artifacts

- `.ai-scientist/active-run.json` — current run pointer used by the AI Scientist Codex Stop hook.
- `.ai-scientist/runs/<run-id>/contract.json` — frozen ideation contract copied from the standalone contract artifact.
- `.ai-scientist/runs/<run-id>/run.md` — ideation progress, reflection rounds, selected ids, manual checks, and completion status.
- `.ai-scientist/runs/<run-id>/ideas.json` — lightweight selected-idea index containing ids, titles, idea-file refs, and pilot-report refs.
- `.ai-scientist/runs/<run-id>/ideas/<idea-id>.md` — detailed idea handoff document.
- `.ai-scientist/runs/<run-id>/logs/pilots/<idea-id>/report.md` — pilot viability evidence for a selected idea.
- `.ai-scientist/runs/<run-id>/config.json` — frozen run configuration, active mode, selected idea snapshot, optional custom criteria, prompt paths, and explicit resource caps.
- `.ai-scientist/runs/<run-id>/loop-state.json` — mutable progress state, orchestrator work records/checkpoints, shared baseline state, lightweight node/outcome summaries, resource leases, orchestration cursor, and Stop-hook gate state.
- `.ai-scientist/runs/<run-id>/journal.jsonl` — append-only audit stream for orchestration decisions, API calls, Stop-hook events, resource events, handoff events, and notable validations.
- `.ai-scientist/runs/<run-id>/selection.json` — final selected accepted node/outcome details, evidence refs, and acceptance rationale.
- `.ai-scientist/runs/<run-id>/baseline/` — shared baseline unit for frozen dataset splits, cloned baseline-paper repositories, baseline score calculations, and `baseline.json`.

Do not create separate v1 research-loop ledgers for dependency plans, API calls,
Stop-hook events, handoffs, resource state, or orchestrator locks. Store those
under `config.json`, `journal.jsonl`, or `loop-state.json` as appropriate.
Normal state mutation must go through the `ai-scientist` CLI; hand-editing
`loop-state.json` is a manual recovery path, not normal orchestration.

## Research work and outcome contract

Canonical research-loop state is intentionally compact:

- `state.orchestrator` records the current cursor, active assignment notes, prompt/result refs, and decisions through checkpoints.
- `state.work` may record lightweight worker, critic, revision-worker, and revision-critic assignment summaries when useful; it is checkpoint-owned, not managed by separate task commands.
- `state.baseline` records shared baseline readiness, fixed split refs, baseline score refs, and baseline repository refs when required.
- `state.nodes` records lightweight candidate/outcome summaries keyed by node id.
- `state.resources.leases` records active resource leases; `state.resources.completed_leases` records released leases.
- `state.selection` records the final selected accepted node/outcome.

Large command logs, stdout/stderr, metrics, and raw worker payloads belong under
`logs/`. Experiment commands should use `resource run` so command refs and
lease events are auditable.

## Phase gates

All phase transitions run `ai-scientist validate run`. A non-zero validator exit blocks the next phase.

Hard continuation also requires the project-local Codex Stop hook installed by `ai-scientist hooks install`. The hook reads `active-run.json` and `loop-state.json`; active phases or terminal phases without a passing `completion_audit` return `decision: "block"` to Codex.

### Ideation to research

Ideation is goal-driven and has no CLI lifecycle or transition validator. Research
startup consumes the frozen `contract.json`, selected Markdown idea files, pilot
reports, and the lightweight `ideas.json` index. The ideation orchestrator records
its manual artifact checks and `status: complete` in `run.md`.

### Research to review

Requires completed research loop state, no unresolved checkpointed work, no active resource
leases, final selection pointing at an accepted node/outcome, and a passing
completion audit. After validation passes, record validation and approved handoff
journal evidence so the Stop hook can release the orchestrator.

### Review to writeup

Requires structured review, verdict, and leakage/split/baseline/mode criteria
coverage. Record validation and approved handoff evidence after the validator
passes. Rejected reviews block positive writeup.

### Launch

Requires complete writeup artifacts, at least one figure, the required PDF,
disclosure and limitations coverage, and an independent final audit with verdict
`ACCEPT`.
