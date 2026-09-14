# Artifact Schema

Ground truth for the files the plugin writes under `<target-repo>/.ai-scientist/`.
Skills and agents write these files by hand. The CLI validates their shape. The
dashboard reads them. When a skill prompt, a JSON schema under `schemas/`, the
validator, or the scanner disagrees with this document, this document wins and
the other side gets fixed.

Design rule: the burden sits on the readers, not the writers. Agents honor a
short list of **required** keys; everything else is **conventional** (readers
use it when present) or **free** (readers ignore it). Readers tolerate missing
files, unknown keys, and unparseable lines.

Conventions:

- `*` marks a required field.
- Paths inside a run are relative to `.ai-scientist/runs/<run-id>/` unless they start with `.ai-scientist/`.
- Timestamps are ISO 8601 UTC strings with a `Z` suffix.
- Status tokens are lowercase words.

---

## 1. Root layout

```text
.ai-scientist/
├── active-run.json                       current run pointer
├── contracts/<contract-id>/
│   └── research-contract.json            standalone frozen contract
├── evaluators/                           user-supplied evaluator scripts (free)
└── runs/<run-id>/                        one directory per run
```

| Path | Writer | Readers |
|---|---|---|
| `active-run.json` | `research-loop-bootstrap`, `ideation`, research completion | cli, dash |
| `contracts/<id>/research-contract.json` | `create-contract` | dash |
| `evaluators/` | user | none |

`<run-id>` and `<contract-id>` are single path segments, never `.` or `..`.

---

## 2. Run layout

A run directory belongs to one phase. A research run has `loop-state.json`; an ideation run has `run.md` and no `loop-state.json`. That difference is how readers tell them apart.

### 2.1 Ideation run

```text
runs/<run-id>/
├── contract.json                         verbatim copy of the user's contract
├── run.md                                durable resume context, free Markdown
├── ideas.json                            selected-idea index, section 3.6
├── ideas/<idea-id>.md                    canonical idea files, free Markdown
└── logs/
    ├── filter.md                         rejected candidates with reasons
    ├── pilots/<idea-id>/report.md        pilot evidence per surviving idea
    ├── data-insight/ideation/            section 2.4
    └── *.md                              any other free Markdown log
```

Conventional: `run.md` starts with a bullet `- status: <token>` so the overview can show it. Anything else in `run.md` is free.

### 2.2 Research run

```text
runs/<run-id>/
├── loop-state.json                       mutable orchestration state, section 3.3
├── journal.jsonl                         append-only audit stream, section 3.4
├── config.md                             immutable run config, section 3.5
├── discovery-notes.md                    campaign wiki, free Markdown
├── learning-notes.md                     cross-node insights, free Markdown
├── selection.json                        present only on outcome success, section 3.7
├── *.md                                  any other run-level report, free
├── baseline/
│   └── baseline.json                     baseline manifest, section 3.8
├── nodes/<node-id>/workspace/            worker workspace; contents are free
├── architectures/                        architecture-tree skill output (optional)
├── logs/
│   ├── baseline/<work-id>/result.md
│   ├── workers/<node-id>/<work-id>/result.md
│   ├── revisions/<node-id>/<work-id>/result.md
│   ├── rankings/<work-id>/result.md
│   ├── resources/<work-id>/<lease-id>/   resource run evidence (CLI-owned)
│   ├── data-insight/revision/<node-id>/<work-id>/   section 2.4
│   └── *.md                              free Markdown logs
├── review/structured-review.json         review phase, section 3.9
└── writeup/                              writeup phase, section 3.10
```

Node ids and work ids are stable tokens chosen by the orchestrator. There is no format rule. Readers locate a work item's report through `result_ref` in state, never by parsing ids.

Review and writeup run inside the research run directory; they add `review/` and `writeup/` and change `phase` in `loop-state.json`.

### 2.3 Run-level reports

Any `*.md` directly under the run directory or under `logs/` is a report. Readers list them by filename. No fixed names.

### 2.4 Data-insight directories

Written by the data-insight skills.

```text
logs/data-insight/ideation/data_insight_ideation_report.md            * required output
logs/data-insight/revision/<node-id>/<work-id>/data_insight_revision_report.md   * required output
```

Supporting files (`inspection.py`, `profile.json`, `split_audit.json`, `evidence_inventory.json`) are free.

---

## 3. File definitions

### 3.1 `active-run.json`

```json
{
  "schema_version": 1,
  "run_id": "<run-id>",
  "phase": "research",
  "status": "active",
  "updated_at": "2026-09-09T18:14:29Z",
  "target_repository": "/abs/path/to/target-repo"
}
```

| Field | Notes |
|---|---|
| `run_id` * | directory name under `runs/` |
| `phase` * | `ideation`, `research`, `review`, `writeup` |
| `status` * | `active` while a goal is running; otherwise the run's terminal `phase_status` |
| `updated_at` * | |
| `target_repository` * | absolute path |
| `schema_version` | `1` |

Removed when the run's final phase completes with release evidence.

### 3.2 `contracts/<contract-id>/research-contract.json`

```json
{"research_contract": {"contract_id": "...", "title": "...", "goal": "...", "...": "..."}}
```

`research_contract` * wraps the contract. Inside it `contract_id` * and `goal` * are required; the rest is defined by the `create-contract` skill and is free here.

A run's `contract.json` (ideation) or the file named by `contract_path` in `config.md` (research) is a verbatim copy of what the user supplied. It may be this wrapped form or a bare object. Readers look for the goal at `research_contract.goal`, then `goal`, then `primary_hypothesis`.

### 3.3 `loop-state.json`

```json
{
  "schema_version": 1,
  "run_id": "<run-id>",
  "active": true,
  "phase": "research",
  "phase_status": "running",
  "updated_at": "2026-09-09T18:14:29Z",
  "last_transition_id": "tr-20260909181429-dispatch",
  "run_outcome": null,
  "blocked_reason": null,
  "links": {
    "config": "config.md",
    "contract": "contract_gdsc_2p10.json",
    "idea_batch": ".ai-scientist/runs/<ideation-run-id>/ideas.json",
    "discovery_notes": "discovery-notes.md",
    "learning_notes": "learning-notes.md"
  },
  "state": {}
}
```

**Top level**

| Field | Notes |
|---|---|
| `run_id` * | |
| `phase` * | `research`, `review`, `writeup` |
| `phase_status` * | `running` while the loop is active. Terminal for research: `success`, `exhausted`, `cancelled`, `blocked` (from `skills/research-loop/SKILL.md`). Terminal for review and writeup: `complete`, `cancelled` |
| `active` * | `false` once `phase_status` is terminal |
| `updated_at` * | |
| `last_transition_id` | matches the newest `state_transition` journal record |
| `run_outcome` | repeats the terminal `phase_status` |
| `blocked_reason` | required when `phase_status` is `blocked` |
| `links` | conventional paths to companion files; keys above are the standard ones |
| `state` * | object, sections below |

Waiting on the user or on a resource is not a status: the run stays `running` and `orchestrator.next_action` says what it waits for.

**`state`** has the sections the checkpoint skill merges: `orchestrator`, `baseline`, `nodes`, `work`, `tasks`, `resources`, `resource_queue`, `selection`. Extra keys are tolerated; readers ignore them.

**`state.orchestrator`** (free beyond these)

| Field | Notes |
|---|---|
| `next_action` * | human-readable next step |
| `last_checkpoint_at` | |
| `open_questions` | conventional: object keyed by question id, each with `statement` and `status` |
| `completion_audit` | conventional: prose or path, at terminal |

**`state.baseline`**

| Field | Notes |
|---|---|
| `status` * | `not_required`, or any lowercase token; `ready` / `completed` mean node workers may use the split |
| `result_ref` | conventional report path |

Free beyond these.

**`state.nodes`**: object keyed by node id. The ledger entry is the single source of truth for a node; there is no per-node JSON file.

```json
"N1": {
  "status": "running",
  "updated_at": "2026-09-09T08:32:23Z",
  "parent_node_id": null,
  "title": "...",
  "idea_id": "...",
  "assignment": "...",
  "result_ref": "logs/workers/N1/w-001/result.md",
  "evidence_summary": "...",
  "next_action": "..."
}
```

| Field | Notes |
|---|---|
| `status` * | terminal when one of `completed`, `cancelled`, `failed`, `abandoned`, `accepted`, `rejected` (the work terminal set from `skills/research-loop/SKILL.md`). Any other lowercase word means the node is live |
| `updated_at` * | |
| `parent_node_id` * for branches | parent node id; `null` or absent for roots |
| `title`, `idea_id`, `assignment`, `result_ref`, `evidence_summary`, `next_action`, `metrics` | conventional; readers show them when present |

Free beyond these.

**`state.work`**: object keyed by work id. Minimum shape from `skills/research-loop/references/checkpointing.md` plus the owning node.

```json
"N1-w-001": {
  "status": "running",
  "agent_thread_id": "<agent id or name used to resume>",
  "result_ref": "logs/workers/N1/N1-w-001/result.md",
  "node": "N1"
}
```

| Field | Notes |
|---|---|
| `status` * | same terminal set as nodes; other lowercase words are nonterminal |
| `agent_thread_id` * | |
| `result_ref` * | report path |
| `node` * | owning node id, or `null` for run-wide work such as rankings |

Free beyond these (ranking fields `ranking_id`, `cohort_node_ids`, `top_n`, `selected_node_ids`, revision `revision_plan_ref`, `authority`, `next_action`, `closed_at`).

**`state.tasks`**: reserved for CLI-driven tasks. Skills leave it `{}`.

**`state.resources`** and **`state.resource_queue`**: free. When `ai-scientist resource acquire|release|run` is used, the CLI writes `resources.leases` and the queue buckets `pending`, `released`, `completed`, and the research-to-review gate checks them. Readers show these sections raw.

**`state.selection`**

| Field | Notes |
|---|---|
| `status` * | `pending`, `final` |
| `selected_node` * | node id with terminal status `accepted`, or `null` |

Free beyond these (`outcome`, `verified_by`, `result_ref`).

### 3.4 `journal.jsonl`

One JSON object per line, append-only. Shape is fixed by `core.state.append_journal_event`; skills write the same shape by hand.

```json
{"event_type": "state_transition", "timestamp": "2026-09-09T05:34:56Z", "run_id": "<run-id>", "transition_id": "tr-20260909053456-dispatch", "node_id": "N2", "details": {"command": "research-loop-checkpoint", "changed_sections": ["nodes", "work"], "note": "N2 dispatched"}}
```

| Field | Notes |
|---|---|
| `event_type` * | one of `state_transition`, `api_call`, `resource_event`, `subagent_event`, `critic_event`, `handoff`, `validation`, `selection`, `setup`, `dependency`, `workspace`, `note`, `finding` |
| `timestamp` * | |
| `run_id` * | |
| `details` * | free object; checkpoints carry `command`, `changed_sections`, `note` |
| `transition_id` | required for `state_transition` |
| `node_id` | set when the record concerns one node; this is how readers build a node's history |
| `subagent_id`, `resource_id`, `before_hash`, `after_hash` | optional, CLI-defined |

Bootstrap writes `event_type: setup`. Readers skip lines that fail to parse.

### 3.5 `config.md`

Immutable research run configuration: YAML frontmatter followed by free Markdown that restates the frozen contract and each idea's identity. Machines read only the frontmatter.

```yaml
---
run_id: <run-id>
target_repository: /abs/path/to/target-repo
contract_path: contract_gdsc_2p10.json
idea_batch: .ai-scientist/runs/<ideation-run-id>/ideas.json
primary_metric: mean_fold_rmse_ln_ic50
primary_metric_direction: lower_is_better
success_threshold: 2.10
active_node_cap: 4
ranking_top_n: 3
python_env: uv run python
---
```

| Field | Notes |
|---|---|
| `run_id` * | |
| `contract_path` * | relative to the target repository, or absolute |
| `idea_batch` * | path to the ideation `ideas.json`, or a single idea file |
| `primary_metric` * | short token |
| `success_threshold` * | number |
| `primary_metric_direction`, `active_node_cap`, `ranking_top_n`, `python_env`, `target_repository` | conventional |

Free beyond these.

### 3.6 `ideas.json`

```json
{
  "run_id": "<ideation-run-id>",
  "ideas": [
    {"id": "transfer-decoupling-diagnostic", "title": "...", "idea_file": "ideas/transfer-decoupling-diagnostic.md", "pilot_report": "logs/pilots/transfer-decoupling-diagnostic/report.md"}
  ]
}
```

`ideas` * is a list; each entry has `id` *, `title` *, `idea_file` *. `pilot_report` and `run_id` are conventional. Paths are relative to the ideation run directory.

### 3.7 `selection.json`

Written once, only when the research outcome is `success`.

| Field | Notes |
|---|---|
| `run_id` * | |
| `status` * | `final` |
| `selected_node` * | node id |
| `acceptance_rationale` * | prose |
| `result`, `verification`, `primary_metric`, `success_threshold` | conventional |

Free beyond these.

### 3.8 `baseline/baseline.json`

Written by the baseline worker. Field list comes from `agents/ai-scientist-research-baseline-worker.md`: `status` *, `fixed_split_dir`, `split_manifest_ref`, `split_refs`, `repo_refs`, `baseline_score_refs`, readiness notes. Free beyond these. Readers show it raw.

### 3.9 `review/structured-review.json`

Written by the review skill. Required: `verdict` * with `decision` (`accept`, `revise`, `reject`, `negative-result`), plus `leakage` *, `split_integrity` *, `baseline_comparison` * each carrying `pass` and `summary`. `reject` and `negative-result` block the positive writeup; `negative-result` routes to `ai-scientist writeup negative-complete`. Free beyond these.

### 3.10 `writeup/`

CLI-owned. Skills call `ai-scientist writeup ...` and never hand-write these. Shapes live in `src/writeup/state.py`.

---

## 4. What the dashboard reads

| View | Files | Uses |
|---|---|---|
| overview | `active-run.json`; per run `loop-state.json` or `run.md`; `config.md` frontmatter; contract file; `ideas.json`; `contracts/*/research-contract.json` | run id, phase, `phase_status` (or `run.md` status line), `active`, `updated_at`, `run_outcome`, `blocked_reason`, `orchestrator.next_action`, `selection.selected_node`, `primary_metric`, `success_threshold`, contract goal, idea count, node count |
| run detail | above plus `journal.jsonl`, `selection.json`, `baseline/baseline.json`, `links`, `*.md` under run root and `logs/` | node ledger with depth from `parent_node_id`, work grouped by `node`, raw `resources`, `resource_queue`, `open_questions`, report list, journal tail |
| node detail | ledger entry, `work` entries whose `node` matches, journal records whose `node_id` matches, report files named by `result_ref` | node fields, ordered history, report contents |

The scanner never reads `nodes/<node-id>/workspace/`. Liveness is `status not in {completed, cancelled, failed, abandoned, accepted, rejected}`.

---

## 5. Reconciliation with the CLI

Places where the CLI or its JSON schemas disagree with this document and must move:

- `core.state.TERMINAL_PHASE_STATUSES`, `ALLOW_WITH_REASON_STATUSES`, and `blocked_manual_recovery` handling use `verifying`, `failed`, `blocked_on_user`, `blocked_manual_recovery`, and uppercase variants. Use the section 3.3 vocabulary.
- `core.state.NODE_UNRESOLVED_STATUSES` / `NODE_RESOLVED_STATUSES` define a node vocabulary this document does not have. Replace with the terminal-set test.
- `validation.run.check_config` loads `config.json`. It must parse `config.md` frontmatter.
- The campaign validator requires `state.idea_batch` and `state.learning_notes.path`. Both come from `config.md` and `links`.
- `research.workflow` writes `learning_notes_ref` as `learning-notes.jsonl`. The file is `learning-notes.md`.
- `schemas/config.schema.json` and `schemas/node.schema.json` describe files this document removes. Delete them.
- `schemas/active-run.schema.json` uses `target_repo`; this document uses `target_repository`.
- `schemas/loop-state.schema.json`, `schemas/selection.schema.json`, `schemas/journal.schema.json` carry field lists beyond this document. Reduce to the required keys here.
- Nothing under `src/` loads `schemas/*.json`. Once aligned, `ai-scientist validate run` should load them.
