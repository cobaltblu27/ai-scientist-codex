# AI Scientist Artifact Contract

Target repositories keep all plugin state in `.ai-scientist/` so ordinary project files remain auditable separately from research governance artifacts.

## Required root and run artifacts

- `.ai-scientist/config.json` — optional target-repository override for plugin defaults from `config/config.json`.
- `.ai-scientist/active-run.json` — current run pointer used by the AI Scientist Codex Stop hook.
- `.ai-scientist/runs/<run-id>/ideas.json` — generation-order array of terminal valid idea objects from `ideation`, including `evaluation`, `score`, and `rank` where applicable.
- `.ai-scientist/runs/<run-id>/logs/...` — ideation-only draft, critic, ranking, and Semantic Scholar cache records retained for auditability.
- `.ai-scientist/runs/<run-id>/config.json` — frozen run configuration and contracts, including workspace plan, dependency plan, benchmark contract, resource config, strictness mode, seed policy, and selection weights.
- `.ai-scientist/runs/<run-id>/loop-state.json` — mutable progress state, official node statuses, resources, subagent ledger, orchestration cursor, and Stop-hook gate state.
- `.ai-scientist/runs/<run-id>/journal.jsonl` — append-only audit stream for orchestration decisions, API calls, Stop-hook events, resource events, handoff events, and notable validations.
- `.ai-scientist/runs/<run-id>/selection.json` — interim/final ranking, component scores, manual override rationale, and selected-node details.
- `.ai-scientist/runs/<run-id>/run-status.json` — optional derived user-facing status snapshot; not a source of truth.

Do not create separate v1 research-loop ledgers for dependency plans, API calls,
Stop-hook events, handoffs, resource state, or orchestrator locks. Store those
under `config.json`, `journal.jsonl`, or `loop-state.json` as appropriate.
Normal state mutation must go through the `ai-scientist` CLI; hand-editing
`loop-state.json` is a manual recovery path, not normal orchestration.

## Experiment node contract

Each `.ai-scientist/runs/<run-id>/nodes/<node-id>/` directory should contain:

- `node.json` — canonical per-node evidence. Reviewed nodes include `node_id`, `status`, `benchmark_contract_version`, `metrics_ref` or `metrics`, `split_integrity.pass`, `leakage_check.pass`, `result_summary`, `mode_deliverables`, `trials`, and evidence/log refs.
- `workspace/` — copied per-node mutable workspace.
- `trials/<trial-id>/...` — raw command logs, stdout/stderr, benchmark-produced metrics, patches, and other large/raw artifacts.

Split integrity, leakage status, result summary, mode deliverables, worker
reports, adapter-extension requests, and rich reasoning belong in `node.json`
unless they are too large/raw for the compact node artifact.

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
- run a dedicated ranking agent after generation; ranking scores all terminal ideas and assigns dense `rank` only to plain `ACCEPTED` ideas;
- end as `EXHAUSTED_NO_CANDIDATE` with a denied handoff when no researchable candidate exists;
- keep intermediate JSON audit artifacts under `.ai-scientist/runs/<run-id>/logs/`.

### Research to review

Requires baseline metrics, command logs, at least one experiment node, split integrity evidence, leakage evidence, baseline beat when required by the active mode, active-mode deliverables, final selection evidence, and an approved handoff journal entry.
Also requires `loop-state.json` to include a completed `research` phase with a passing `completion_audit`, accepted selected node, and no unresolved node states.
For `scientist` and `researcher` modes, accepted nodes also require passing
novelty evidence in `node.json`.

### Review to writeup

Requires structured review, verdict, leakage/split/baseline/mode criteria coverage, canonical state validation, and an approved handoff journal entry. Rejected runs must block writeup or be clearly marked as failed/negative.

### Launch

Requires `verifier-decision.json` with `decision: "go"` and no blockers.
