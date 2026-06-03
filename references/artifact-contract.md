# AI Scientist Artifact Contract

Target repositories keep all plugin state in `.ai-scientist/` so ordinary project files remain auditable separately from research governance artifacts.

## Required root and run artifacts

- `.ai-scientist/config.json` — optional target-repository override for plugin defaults from `config/config.json`.
- `.ai-scientist/active-run.json` — current run pointer used by the AI Scientist Codex Stop hook.
- `.ai-scientist/runs/<run-id>/ideas.json` — generation-order array of terminal valid idea objects from `ideation`, including `evaluation`, `score`, and `rank` where applicable.
- `.ai-scientist/runs/<run-id>/logs/...` — ideation-only draft, critic, ranking, and Semantic Scholar cache records retained for auditability.
- `.ai-scientist/runs/<run-id>/config.json` — frozen run configuration, active mode, selected idea snapshot, optional custom criteria, prompt paths, and explicit resource caps.
- `.ai-scientist/runs/<run-id>/loop-state.json` — mutable progress state, orchestrator work records/checkpoints, shared baseline state, lightweight node/outcome summaries, resource leases, orchestration cursor, and Stop-hook gate state.
- `.ai-scientist/runs/<run-id>/journal.jsonl` — append-only audit stream for orchestration decisions, API calls, Stop-hook events, resource events, handoff events, and notable validations.
- `.ai-scientist/runs/<run-id>/selection.json` — final selected accepted node/outcome details, evidence refs, and acceptance rationale.
- `.ai-scientist/runs/<run-id>/run-status.json` — optional derived user-facing status snapshot; not a source of truth.
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

Requires at least one researchable candidate under the frozen mode config, generated run config, dependency approval statuses, run-local `ideas.json`, finalized ranking, and an approved handoff journal entry.
Modes that require Semantic Scholar evidence must also include journal `api_call` entries. Also requires `loop-state.json` to include a terminal successful `ideation` phase with a passing `completion_audit`.

The Codex-native ideation orchestrator must:

- read the starting point from a prompt string, not a Markdown workshop file;
- use project-local Stop-hook state so active ideation blocks session end;
- use the current Codex session as orchestrator and never run a Python-owned nested Codex loop;
- record subagent intents before generation, criticism, and ranking;
- write terminal ideas to `.ai-scientist/runs/<run-id>/ideas.json` with `evaluation` values of `ACCEPTED`, `ACCEPTED_WITHOUT_REFERENCE`, or `REJECTED`;
- include a hybrid `research_contract` on accepted ideas with a primary hypothesis, goal type, hard success/failure criteria, non-drift definition, metrics, and non-negotiable comparisons; performance contracts also need a usable baseline reference, benchmark plan, and target threshold;
- run a dedicated ranking agent after generation; ranking scores all terminal ideas and assigns dense `rank` only to plain `ACCEPTED` ideas;
- end as `EXHAUSTED_NO_CANDIDATE` with a denied handoff when no researchable candidate exists;
- keep intermediate JSON audit artifacts under `.ai-scientist/runs/<run-id>/logs/`.

### Research to review

Requires completed research loop state, no unresolved checkpointed work, no active resource
leases, final selection pointing at an accepted node/outcome, a passing
completion audit, and an approved handoff journal entry.

### Review to writeup

Requires structured review, verdict, leakage/split/baseline/mode criteria coverage, canonical state validation, and an approved handoff journal entry. Rejected runs must block writeup or be clearly marked as failed/negative.

### Launch

Requires `verifier-decision.json` with `decision: "go"` and no blockers.
