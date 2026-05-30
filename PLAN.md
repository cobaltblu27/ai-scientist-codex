# AI Scientist Continuation State Plan

## Goal

Use the Ralph persistence pattern for the AI Scientist plugin so ideation and
research-loop phases cannot be treated as complete before their phase criteria
are satisfied. The implementation should keep durable, auditable state for
reflection progress, loop iterations, experiment nodes, buggy nodes, validation
evidence, and phase handoffs.

This should stay scoped to `.ai-scientist/` artifacts rather than reusing
`.omx/` state directly.

## Standalone Codex Constraint

This plan must work when only the AI Scientist Codex plugin is installed. It
must not depend on `oh-my-codex`, OMX commands, `.omx/` state files, or OMX hook
runtime code.

Allowed dependencies are:

- Files bundled in `plugins/ai-scientist/`.
- Target-repository artifacts under `.ai-scientist/`.
- Python standard library code in the plugin scripts.
- Codex host hook support and native Codex subagents. Research orchestration
  itself runs in the current Codex session, not through nested Codex subprocesses.

The validator-driven continuation model is standalone but does not, by itself,
prevent a Codex turn from ending. Because hard Stop blocking is critical, the
standalone AI Scientist implementation must include an AI Scientist-owned
project-local Stop-hook setup path using Codex host hook support. It must not
depend on OMX.

## Ralph Pattern To Reuse

Ralph works because it combines three pieces:

1. Active workflow state.
2. Machine-readable completion audit evidence.
3. A Stop gate that blocks ending while state is active or completion evidence is
   missing.

For AI Scientist, the same pattern should become:

```text
phase starts
  -> write active phase state
  -> run loop steps
  -> persist every cursor, node, failure, and decision
  -> validator checks phase-specific criteria
  -> if criteria are incomplete, keep active=true and continue
  -> if criteria pass, write completion_audit and approved handoff journal entry
  -> only then mark active=false / terminal phase
```

## Continuation State Artifact

Add one canonical continuation-state artifact per run:

```text
.ai-scientist/runs/<run-id>/loop-state.json
```

This file is the resumable cursor and continuation-gate source of truth.
It is one member of the compact run artifact model defined below; it is not the
only canonical run file. Other compact canonical files such as `config.json`,
`journal.jsonl`, `selection.json`, and per-node `node.json` hold contracts,
audit history, ranking, and node evidence.

## Ideation State

Ideation state should track idea and reflection progress explicitly:

```json
{
  "active": true,
  "phase": "ideation",
  "phase_status": "running",
  "run_outcome": null,
  "state": {
    "current_idea_index": 4,
    "current_reflection_round": 2,
    "num_ideas_required": 10,
    "num_reflections_required": 5,
    "finalized_count": 3,
    "skipped_count": 0,
    "s2_query_count": 17,
    "idea_states": {
      "idea-001": {
        "status": "finalized",
        "reflection_count": 5,
        "finalization_decision": "finalize"
      },
      "idea-004": {
        "status": "reflecting",
        "reflection_round": 2,
        "last_agent_log": ".ai-scientist/logs/<run-id>/agents/idea-004-02-reflection.json"
      }
    }
  },
  "completion_audit": null
}
```

Ideation completion should be blocked unless:

- The requested number of ideas has been attempted.
- Each non-skipped idea has completed the required reflection/finalization logic.
- Skipped ideas have explicit reasons.
- `ideas.json` contains finalized ideas.
- `ideation-run.json`, agent logs, journal API-call entries, and handoff
  evidence exist.
- `validate_run.py --gate ideation_to_research` passes.
- `completion_audit.passed` is true and includes checklist plus verification
  evidence.

## Plugin-First Ideation Loop Architecture

The AI Scientist Codex plugin should not expose the original AI-Scientist-v2
workflow as "write a markdown file, then run a Python program." The user-facing
interface is a Codex skill command with an inline research topic:

```text
> $ideation <research topic>
> $ai-scientist:ideation <research topic>
```

The skill should treat all text after the command as the research topic. Topic
markdown files may remain an optional import/compatibility path, but they must
not be required for the normal plugin workflow. Internally, the skill can pass
the inline topic to the orchestrator as `--prompt`, or through stdin, but the
Python script remains an implementation detail of the plugin.

The original AI-Scientist-v2 ideation script uses an action loop:

```text
for each idea:
  for each reflection round:
    ask the model for exactly one action
    if action == SearchSemanticScholar:
      run Semantic Scholar search
      store tool results
      feed results into the next reflection prompt
    if action == FinalizeIdea:
      parse final idea JSON
      append it to the idea archive
      stop this idea loop
```

The Codex plugin should preserve this architecture, but make the implicit
criteria deterministic and stop-hook-visible:

```text
inline research topic
  -> initialize .ai-scientist active run
  -> create idea cursor
  -> Codex agent proposes next ACTION
  -> Python executes SearchSemanticScholar or validates FinalizeIdea
  -> write action, arguments, results, and reflection state
  -> reject premature finalization before literature search
  -> repeat until finalize / skip / failure / reflection budget exhausted
  -> validate ideation_to_research gate
  -> clear active run only after validator success
```

Required action response contract:

```json
{
  "action": "SearchSemanticScholar",
  "arguments": {
    "query": "..."
  },
  "thoughts": "brief reflection rationale"
}
```

or:

```json
{
  "action": "FinalizeIdea",
  "arguments": {
    "idea": {
      "Name": "...",
      "Title": "...",
      "Short Hypothesis": "...",
      "Related Work": "...",
      "Abstract": "...",
      "Experiments": "...",
      "Risk Factors and Limitations": "..."
    }
  },
  "thoughts": "brief finalization rationale"
}
```

The plugin should store both the upstream-style idea object and the normalized
AI Scientist plugin object. The upstream-style object preserves compatibility
with AI-Scientist-v2 concepts; the normalized object supports existing gates:

```text
upstream fields:
  Name, Title, Short Hypothesis, Related Work, Abstract, Experiments,
  Risk Factors and Limitations

normalized fields:
  id, title, hypothesis, novelty_rationale, related_work, required_data,
  expected_metric, experiments, risks, minimum_evidence,
  semantic_scholar_queries
```

Semantic Scholar should be run by the plugin orchestrator and logged to
`.ai-scientist/runs/<run-id>/journal.jsonl` as API-call entries. Unlike the current strict
implementation, `S2_API_KEY` should not be mandatory for default ideation,
because AI-Scientist-v2 allows unauthenticated Semantic Scholar access with
lower rate limits. In strict authenticated-search mode, missing `S2_API_KEY`
should fail fast before the run starts. In default mode, unauthenticated use
should be recorded in the journal.

Required ideation phase statuses:

```text
generating
searching_literature
reflecting
finalizing
validating
complete
failed
blocked_on_user
cancelled
```

Required per-idea state:

```json
{
  "id": "idea-004",
  "status": "searching_literature",
  "round": 2,
  "last_action": "SearchSemanticScholar",
  "literature_search_count": 1,
  "reflection_count": 2,
  "last_tool_results_path": ".ai-scientist/logs/<run-id>/semantic-scholar-cache/<key>.json",
  "message_history_path": ".ai-scientist/logs/<run-id>/agents/idea-004-history.json",
  "finalization_attempted": false,
  "last_agent_log": ".ai-scientist/logs/<run-id>/agents/idea-004-02-action.json"
}
```

An idea can be finalized only when:

- At least one Semantic Scholar search has completed or returned an auditable
  no-results record.
- At least one reflection round has been recorded.
- The final idea includes non-empty related-work or novelty rationale.
- The final idea can be normalized into the plugin schema.

If the agent emits `FinalizeIdea` before those criteria are met, the orchestrator
should reject that action, record
`finalization_rejected_missing_literature_search` or another specific reason,
feed the reason back into the next reflection prompt, and keep the Stop hook
blocking the run.

The Stop hook should use the phase and per-idea state to produce continuation
messages with the exact cursor:

```text
AI Scientist ideation is still active.
Run: <run-id>
Idea: idea-004
Round: 2/5
Status: searching_literature
Missing criterion: literature search evidence before finalization
Continue the ideation action loop before ending the session.
```

## Research Loop State

## Research Loop Continuous Orchestration

The research loop must use the current Codex session as the continuous
orchestration agent. There is no Python orchestrator that launches Codex, and no
nested `codex exec` process tree. Python is limited to deterministic helper
work: state transitions, validation, hook decisions, workspace setup, dependency
planning/install helpers, usage probes, artifact checks, and export helpers.

The loop shape is:

```text
current Codex session is the research orchestrator
  -> install/check the AI Scientist Stop hook
  -> initialize active-run.json and loop-state.json
  -> call deterministic state helper before each major action
  -> spawn native Codex subagents only for bounded side work
  -> integrate subagent artifacts in the main session
  -> run validators and benchmark commands directly
  -> finalize research only after selection finalize, completion_audit, and
     research_to_review pass
```

The Stop hook is the persistence mechanism. If the main orchestration agent tries
to end while research is active, the hook must return `decision: "block"` with a
state-derived continuation message. If research is marked terminal without a
passing machine-readable completion audit, the hook must reopen the phase as
`verifying` and block Stop again.

Subagents are workers, not orchestrators. They may implement a node, inspect
workspace setup, critique evidence, validate leakage/split integrity, or score
selection, but they do not decide global loop completion and they do not mutate
loop state by hand. The main orchestration agent reads their artifacts, decides
the next loop action, and records state through the deterministic helper.

Research state should model both the orchestration cursor and experiment nodes
as durable state machines:

```json
{
  "active": true,
  "phase": "research",
  "phase_status": "node_running",
  "run_outcome": null,
  "state": {
    "orchestrator": {
      "role": "main_codex_session",
      "iteration": 7,
      "next_action": "node_work",
      "next_action_details": {
        "verb": "repair_node",
        "reason": "node-004 has a reproducible shape mismatch"
      },
      "current_node": "node-004",
      "last_checkpoint_at": "2026-05-26T00:00:00Z",
      "last_stop_block_reason": null
    },
    "workspace_plan_status": "complete",
    "dependency_plan_status": "frozen",
    "baseline_status": "complete",
    "selected_node": null,
    "node_queue": ["node-004", "node-005"],
    "nodes": {
      "node-003": {
        "status": "buggy",
        "attempt": 2,
        "failure_signature": "shape mismatch in trainer",
        "last_command": "uv run pytest ...",
        "last_error_path": ".ai-scientist/runs/<run-id>/nodes/node-003/error.log",
        "workspace_path": ".ai-scientist/runs/<run-id>/nodes/node-003/workspace",
        "next_action": "repair"
      },
      "node-004": {
        "status": "running",
        "hypothesis": "..."
      }
    },
    "selection": {
      "status": "pending",
      "selected_node": null
    }
  },
  "completion_audit": null
}
```

Node statuses should be finite and explicit:

```text
planned -> implementing -> running -> buggy -> repairing
                              \-> candidate -> validating -> accepted
                              \-> invalid
                              \-> rejected
```

A buggy node should record:

- Failure signature.
- Command and exit code.
- Error log path.
- Attempted fix count.
- Retryability.
- Parent node or hypothesis.
- Next action: `repair`, `fork`, `reject`, or `block`.

Research completion should be blocked unless:

- Baseline metrics and command log exist.
- Every accepted node has metrics, command log, split integrity evidence,
  leakage check evidence, result summary, and mode deliverables.
- Buggy nodes are repaired, rejected with reason, or preserved as failed-attempt
  evidence.
- The selected accepted node beats baseline when the strictness mode requires it.
- `validate_run.py --gate research_to_review` passes.
- Approved handoff journal entry exists.
- `completion_audit.passed` is true and includes checklist plus verification
  evidence.

## State Module

Add a single deep module for state transitions and completion criteria:

```text
plugins/ai-scientist/scripts/ai_scientist_state.py
```

Suggested interface:

```text
start_phase(run_id, phase, criteria)
record_node_step(...)
mark_buggy_node(...)
checkpoint_orchestrator(...)
set_next_action(...)
evaluate_completion(run_id, phase) -> {complete, reason}
reopen_for_verification(run_id, reason)
complete_phase(run_id, completion_audit)
```

This keeps criteria and state transitions local instead of scattering them across
skill markdown, validator checks, and ad hoc JSON writes.

Research-loop state mutation must also have a CLI surface so the orchestration
agent and subagents do not hand-edit `loop-state.json`. The CLI should be a thin
wrapper around `ai_scientist_state.py`, for example:

```text
ai_scientist_state_cli.py research start
ai_scientist_state_cli.py research checkpoint
ai_scientist_state_cli.py research set-next-action
ai_scientist_state_cli.py node transition
ai_scientist_state_cli.py node mark-buggy
ai_scientist_state_cli.py research complete
ai_scientist_state_cli.py research cancel
```

Each command should validate allowed transitions, atomically write state and
audit, emit a JSON result envelope, and fail fast on malformed input. Direct JSON
edits are reserved for tests/fixtures only.

Helper CLI decisions:

- Helper CLI is one script with subcommands, for example
  `plugins/ai-scientist/scripts/ai_scientist_state_cli.py`.
- Helper CLI is primarily an agent/control-plane helper, not a polished user
  product command.
- Helper CLI always emits JSON on stdout, including failures.
- Helper CLI exits nonzero on failure.
- Inline JSON arguments are the primary interface for agent ergonomics.
- Optional input JSON files are allowed for large or awkward payloads.
- Helper logs normalized payloads into journals/resource logs, so audit does not
  depend on original input files.
- Every official state-changing helper mutation must have a matching
  `journal.jsonl` event before the helper reports success.
- Transaction mechanics are Python-helper-owned, not agent-owned. Agents choose
  semantic transitions and invoke helper commands; helpers own locks, hashes,
  journal appends, state writes, verification, and recovery checks.
- State-changing helper commands use a journal-first transition protocol:
  acquire the run lock, read state and `before_hash`, build normalized payload
  with `transition_id`, append a `journal.jsonl` event with before/after hashes,
  atomically replace `loop-state.json` with `last_transition_id`, then re-read
  and verify state/journal before returning success.
- If journal append succeeds but state write fails, recovery may reapply the
  transition only when `before_hash` still matches.
- If state contains a transition missing from `journal.jsonl`, normal helpers
  refuse mutation until explicit manual recovery.
- If the journal append fails, the helper exits nonzero before reporting success.
- State transitions are strict by default.
- `--force` is available only for manual recovery and requires
  `--allow-manual-recovery` plus `--recovery-reason`.
- Manual recovery is allowed only after the run is first moved into a blocked
  recovery state such as `phase_status="blocked_manual_recovery"` with reason.
- Normal active runs refuse `--force`/manual recovery to avoid comparability
  drift while workers/resources are active.
- Helpers that detect state/audit mismatch, duplicate orchestrator, corrupted
  lock, or unrecoverable lease inconsistency should block the run for manual
  recovery before accepting recovery commands.
- Forced transitions are noisy, logged with before/after state hash, and never
  suggested by Stop hook messages.
- Forced recovery does not automatically fail a run, but it must be disclosed
  and reviewed.
- Scientist/researcher completion requires reviewer-agent classification that
  forced recovery was non-material or clearly disclosed as a limitation.

## Validator Changes

Extend `plugins/ai-scientist/scripts/validate_run.py` to read
`loop-state.json` for phase gates.

For `ideation_to_research`, fail if ideation state is active, incomplete, or
missing completion audit evidence.

For `research_to_review`, fail if research state is active, has unresolved node
states, lacks selected-node evidence, or is missing completion audit evidence.

Completion audit should be machine-readable, following the Ralph pattern:

```json
{
  "passed": true,
  "prompt_to_artifact_checklist": [
    "Requested 10 ideas -> .ai-scientist/ideas/ideas.json contains 10 finalized ideas"
  ],
  "verification_evidence": [
    "validate_run.py <target> --gate ideation_to_research --run-id <run-id> exited 0"
  ]
}
```

## Stop-Gate Integration

Implement in two levels.

### Level 1: Validator-Only

Require skills and scripts to consult `loop-state.json` and refuse phase handoff
when completion criteria are incomplete. This improves resumability and prevents
validating incomplete phases, but it still depends on the assistant following the
workflow instructions.

This level is fully standalone with only `ai-scientist-codex` installed. It
requires no hook runtime and no other plugin.

### Level 2: Ralph-Style Stop Hook

Hard Stop blocking is critical behavior. It requires a real Codex lifecycle
Stop hook installed for the project. Skill instructions and validators alone
cannot prevent an assistant turn from ending.

The current plugin manifest only exposes skills. Therefore, installing the AI
Scientist plugin by itself is not enough to guarantee Stop blocking unless the
plugin also ships and registers its own hook surface.

Required standalone pieces:

- `plugins/ai-scientist/scripts/ai_scientist_stop_hook.py`
  - Reads the Codex Stop hook JSON payload from stdin.
  - Resolves the target repository from the hook cwd/payload.
  - Reads `.ai-scientist/active-run.json` or an equivalent current-run pointer.
  - Reads `.ai-scientist/runs/<run-id>/loop-state.json`.
  - Emits exactly one valid JSON object to stdout.
  - Emits no ordinary logs on stdout.
- A setup/installer command, for example
  `plugins/ai-scientist/scripts/install_codex_hooks.py`.
  - Enables Codex hooks in the local/project Codex config when supported.
  - Registers the Stop hook command in `.codex/hooks.json`.
  - Does not call `omx` and does not import `oh-my-codex`.
  - Uses only files bundled in `plugins/ai-scientist/` plus Codex-owned config
    files.
- A current-run pointer:
  - `.ai-scientist/active-run.json` records `run_id`, `phase`, `updated_at`, and
    optional Codex session/thread identifiers when available.
  - The hook should prefer this pointer over scanning all runs, so stale old runs
    do not block unrelated sessions.
- A cancellation/escape contract:
  - User-requested cancellation must write terminal state such as
    `active=false`, `phase_status="cancelled"`, or `run_outcome="blocked_on_user"`.
  - The Stop hook must pass terminal or explicitly cancelled states.
- A completion audit contract:
  - If `loop-state.active=true`, block Stop.
  - If the phase is terminal but `completion_audit` is missing or not passing,
    reopen the phase as `verifying` and block Stop.
  - If `completion_audit.passed=true` with checklist and verification evidence,
    allow Stop only after required validation/handoff evidence is present, unless
    the run is an explicit cancellation or blocked terminal outcome.

Native Stop hook behavior should be:

```text
read .ai-scientist/runs/<run-id>/loop-state.json
if active=true:
  decision=block
  systemMessage="AI Scientist <phase> is still active..."
if phase is terminal but completion_audit is missing:
  reopen phase as verifying
  decision=block
```

This gives the hard "do not end the session yet" behavior Ralph has. Do not
import OMX code, call `omx`, or require `oh-my-codex` for this layer.

Minimum verification for this layer:

- Unit test: active `loop-state.json` returns `decision: "block"`.
- Unit test: terminal state with missing completion audit reopens as
  `verifying` and returns `decision: "block"`.
- Unit test: terminal state with passing completion audit allows Stop.
- Smoke test: install hook config in a temporary repo and invoke the hook with a
  representative Codex Stop payload.
- Runtime test, when available: launch Codex with hooks enabled, create an active
  AI Scientist run, attempt to end the turn, and confirm the hook injects the
  continuation message.

## Implementation Order

1. Update the ideation skill interface so inline prompt invocation is the
   canonical plugin path; markdown topic files are optional compatibility input.
2. Add `loop-state.json` schema.
3. Add `ai_scientist_state.py` with pure state transition helpers and ideation
   completion checks for reflection, literature search, and finalization.
4. Update `ideation_orchestrator.py` from fixed proposal/search/reflection steps
   to the AI-Scientist-v2-style action loop.
5. Keep `active-run.json` present through `validating`; clear it only after
   `validate_run.py --gate ideation_to_research` succeeds.
6. Extend `validate_run.py` to enforce ideation completion audit and normalized
   plus upstream-style idea evidence.
7. Add research-loop state contract and node state helpers.
8. Extend `validate_run.py` to enforce research-loop completion audit and node
   resolution.
9. Update skill instructions to reference `loop-state.json` and completion audit
   requirements.
10. Add `active-run.json` current-run pointer handling.
11. Add AI Scientist-owned Stop-hook script and hook installer without OMX.
12. Add action-loop, completion-state, Stop-hook, and temporary-repo hook smoke
    tests.

## Recommendation

Implement `loop-state.json` and validator enforcement first, then immediately add
the AI Scientist-owned Stop hook and installer. Hard Stop blocking is not
guaranteed until the hook is registered in Codex and the smoke test proves an
active AI Scientist run returns `decision: "block"` on Stop.

## Resolved Decision Log

This section is the durable source of truth for decisions resolved in the
planning interview. Keep it updated before continuing the interview so context
compaction does not erase prior answers.

### Global Boundaries

- AI Scientist must remain standalone. It must not depend on `oh-my-codex`, OMX
  commands, `.omx/` state, or OMX hook runtime code.
- Reusing Ralph means reusing the pattern, not the dependency: active state,
  machine-readable completion audit, and a Stop hook that blocks premature
  session end.
- All AI Scientist artifacts live under `.ai-scientist/` in the target project.
- The project-local Stop hook is critical behavior, not a nice-to-have.
- Hook readers must be cheap and deterministic. They read explicit state and do
  not infer progress by scanning arbitrary artifacts.
- State mutation should be helper-command-driven. Agents should not hand-edit
  loop-state JSON during normal execution.
- Direct JSON edits are acceptable only in tests, fixtures, or explicit manual
  recovery.
- This is a Codex-native vibe-research framework, not a fully deterministic
  pipeline.
- Prefer natural-language agent work where judgment is needed.
- Use strict JSON only for state/contract surfaces that prevent real failure
  modes: Stop continuation, resource scheduling, comparability, selection, and
  validation gates.
- Avoid proliferating small JSON contract files that force agents to spend
  tokens reading/writing bureaucracy instead of doing research.

### Compact Artifact Model

- v1 should minimize canonical files.
- Core canonical files are:
  - `.ai-scientist/active-run.json`
  - `.ai-scientist/runs/<run-id>/loop-state.json`
  - `.ai-scientist/runs/<run-id>/config.json`
  - `.ai-scientist/runs/<run-id>/journal.jsonl`
  - `.ai-scientist/runs/<run-id>/selection.json`
- `loop-state.json` is mutable progress and Stop-hook state.
- `config.json` is frozen run configuration and contracts, including workspace
  plan, dependency plan, benchmark contract, resource config, strictness mode,
  seed policy, and selection weights.
- `journal.jsonl` is the append-only audit stream for orchestration decisions,
  API calls, Stop-hook events, resource events, handoff events, and notable
  validations.
- `journal.jsonl` uses a small fixed top-level `event_type` set with free-form
  `details`: `state_transition`, `api_call`, `stop_hook`, `resource_event`,
  `subagent_event`, `handoff`, `validation`, `selection`, `setup`,
  `dependency`, `workspace`, and `note`.
- Journal events include `event_type`, `timestamp`, `run_id`, optional
  `transition_id`, optional `node_id`, optional `subagent_id`, optional
  `resource_id`, and free-form `details`.
- `selection.json` is kept separate because ranking/final selection is a
  substantial artifact.
- `resources.json` should not exist in v1 unless real concurrent mutation pain
  forces it. Keep resource queue under `loop-state.json["state"]["resources"]`
  with helper locking.
- `orchestrator-lock.json` should not exist in v1; keep lock/owner fields under
  `loop-state.json["state"]["orchestrator_lock"]`.
- `orchestration-journal.jsonl`, `api-ledger.jsonl`,
  `stop-hook-events.jsonl`, and `handoff.jsonl` should be folded into
  `journal.jsonl` in v1.
- `run-status.json` is optional/generated status snapshot, not a core source of
  truth.
- Per-node canonical file is `nodes/<node-id>/node.json`.
- `node.json` should hold node status, metrics summary, split/leakage summary,
  result summary, mode deliverables, worker reports, trials, and relevant
  evidence pointers.
- Node workers may write their own `nodes/<node-id>/node.json` inside their
  assigned node boundary.
- Worker-written `node.json` content is evidence until reviewed. It is not
  global run state and does not by itself satisfy Stop-hook completion.
- Workers must not mutate `loop-state.json`, `active-run.json`,
  `selection.json`, `config.json`, or other nodes' `node.json` during normal
  execution.
- The main orchestration agent owns `loop-state.json` transitions, integrates
  or rejects worker output, and may amend `node.json` with reviewed official
  status/evidence.
- Official node status lives in `loop-state.json`.
- Workers may propose an outcome with `recommendation.status` inside their own
  `node.json`, but that is not official state.
- During integration, the orchestrator/helper sets official node status in
  `loop-state.json` and mirrors that reviewed value into `node.json.status`.
- Validators fail if reviewed `node.json.status` disagrees with the official
  `loop-state.json` node status.
- `node.json` should keep only gate-critical fields structured. For reviewed
  nodes, required structured fields are `node_id`, `status`,
  `benchmark_contract_version`, `metrics_ref` or `metrics`,
  `split_integrity.pass`, `leakage_check.pass`, `result_summary`,
  `mode_deliverables`, `trials`, and evidence/log refs.
- Rich research reasoning, implementation notes, failed alternatives, and
  reviewer-style commentary may be natural-language prose inside `node.json`
  or `journal.jsonl`; v1 should not split those into additional JSON contracts.
- Validators should check structured gate fields, evidence references, and
  state transitions only.
- Runtime artifact validation should be implemented with Python standard
  library helper code, not a required `jsonschema` or other third-party runtime
  dependency.
- JSON Schema files may remain as contract documentation and test fixtures, but
  helper scripts and validators are the runtime source of truth.
- Keep separate per-node files only for large/raw artifacts such as command
  logs, patches, workspace, and benchmark-produced metrics if the benchmark
  writes them directly.

### Current Architecture Pivot

- Research-loop must not use a Python orchestrator that launches Codex.
- The current Codex session is the continuous research orchestration agent.
- Python scripts are deterministic helpers only: state transitions, validation,
  hook decisions, workspace setup helpers, dependency planning/install helpers,
  usage probes, artifact checks, and export helpers.
- Native Codex subagents are allowed only for bounded worker tasks.
- Subagents are workers, not loop owners. The main orchestration agent decides
  global next action, integrates artifacts, and records official state.
- The Stop hook keeps the main orchestration agent alive until research criteria
  are terminal and audited.
- The research loop should have a CLI state mutation surface wrapping
  `ai_scientist_state.py`.
- Research v1 should keep existing `loop-state.json["state"]` as the source of
  truth, adding orchestration fields inside it rather than redesigning the
  top-level schema.
- Research v1 keeps current research fields directly under
  `loop-state.json["state"]`, including `baseline_status`, `selected_node`, and
  `nodes`.
- Do not introduce a nested `state.research.nodes` object in v1.
- Add adjacent fields such as `orchestrator`, `orchestrator_lock`,
  `subagents`, `resources`, and `selection`.

### Hook And State

- `.ai-scientist/active-run.json` is the current-run pointer for the Stop hook.
- The Stop hook should prefer `active-run.json` over scanning old runs.
- `loop-state.json` is the phase gate and resumable cursor.
- If `loop-state.active=true`, Stop returns `decision: "block"`.
- If a phase is terminal but `completion_audit` is missing or not passing, the
  hook reopens the phase as `verifying` and blocks Stop.
- If `completion_audit.passed=true` and includes checklist plus verification
  evidence, Stop may allow session end only after required validation/handoff
  evidence is present, unless the run is an explicit cancellation or blocked
  terminal outcome.
- Hook failures fail closed with a block decision.
- User cancellation must write explicit terminal state such as `cancelled`,
  `blocked_on_user`, or equivalent terminal outcome with reason.
- Stop hook output must be a single valid JSON object on stdout.
- Stop-hook events should be logged to
  `.ai-scientist/runs/<run-id>/journal.jsonl`.
- Completion audit is machine-readable and requires:
  `passed: true`, non-empty `prompt_to_artifact_checklist`, and non-empty
  `verification_evidence`.
- Agent helper CLI uses the current working directory as the target repository.
- Agent helper CLI has no normal `--target-repo` override in v1.
- Agent helper CLI infers the current run from `.ai-scientist/active-run.json`.
- Normal helper calls do not require `--run-id`.
- Explicit run id is reserved for recovery/test paths behind manual recovery
  controls.
- Only `research start` creates `.ai-scientist/active-run.json`.
- Normal helper commands require an existing active run.
- Manual recovery may repoint active-run only with explicit recovery flags.
- `research complete` does not clear active-run immediately. It writes terminal
  research state and changes active-run status to `validating`.
- Active-run is cleared only after `validate_run.py --gate research_to_review`
  passes and an approved handoff journal entry exists.
- If validation fails, research remains active/validating and must be repaired
  or reopened.

### Subagent Ledger

- Research-loop needs a standalone subagent ledger for spawned work promises.
- For v1, the subagent ledger lives inside
  `loop-state.json["state"]["subagents"]`, not a separate file.
- Stop hook trusts explicit subagent status in loop state only.
- Stop hook does not inspect worker reports or artifact files to infer whether a
  subagent is integrated.
- Non-terminal subagent statuses block completion.
- Terminal subagent statuses are only explicit states such as `integrated`,
  `rejected_with_reason`, or `abandoned_with_reason`.
- Main orchestration agent integrates or rejects subagent output and records the
  official state transition.
- Subagent lifecycle statuses are: `planned`, `running`,
  `blocked_on_resource`, `completed_unintegrated`, `failed_unreviewed`,
  `integrated`, `rejected_with_reason`, and `abandoned_with_reason`.
- `blocked_on_resource` is non-terminal. It means the worker could not execute
  required resource-gated work and needs orchestration later.
- `planned` blocks Stop only when explicitly recorded before spawning; vague
  future intent must not create blocking planned subagents.
- Workers may request/queue resources, but only the main orchestration agent runs
  official resource-gated commands by default.
- A worker may run official resource-gated commands only when its subagent ledger
  entry explicitly sets `resource_run_allowed: true` for that bounded command.
- Workers may run CPU-only bounded smoke tests without `resource run`.
- Worker smoke tests may include unit tests, import probes, syntax/type checks,
  and tiny CPU smoke commands.
- Worker smoke tests do not create official benchmark evidence.
- Worker smoke-test commands and results are logged in the relevant
  `nodes/<node-id>/node.json`.
- Workers may self-debug locally within wall-time/resource/progress bounds.
- There is no hard default local repair-attempt count.
- Local repair stops when the same failure signature repeats without a new
  hypothesis, when a resource lease is needed, when an unapproved dependency is
  needed, when benchmark/split/metric contract would be affected, or when the
  configured wall/time budget is hit.
- Worker result sections include repair attempts, failures, patches, and final
  recommendation inside `node.json`.
- The main orchestration agent still records official node transitions after
  reviewing worker-written `node.json` and bounded work output.
- Stale `running` subagents can be marked `failed_unreviewed` through helper
  after stale thread/session evidence is detected.
- Stale subagents are not auto-terminal; the orchestrator must review artifacts
  and choose retry, abandon, or reject.
- Subagent ledger includes minimal timestamp fields such as `updated_at`,
  `last_seen_at`, and `heartbeat_source`.
- Continuous worker heartbeats are not required in v1; orchestrator polling or
  received worker output may update `last_seen_at`.

### Resource Queue And Command Execution

- Parallel node implementation is allowed across different node workspaces.
- Parallelism is not allowed within the same node workspace in v1.
- A node may have only one active writer for code edits and `node.json` updates
  at a time.
- Multiple agents may inspect the same node read-only, but any code mutation or
  `node.json` mutation must go through the single active node worker or the main
  orchestrator during integration.
- Parallelism is limited by explicit resource scheduling, not by architecture.
- GPU-heavy training/evaluation commands must use the resource queue.
- The resource queue lives in explicit run state and is mutated only through
  atomic helper commands.
- Queue mutation uses lock files under `.ai-scientist/runs/<run-id>/locks/` plus
  atomic JSON writes.
- Resource leases are scoped to concrete commands/trials, not whole nodes.
- A lease includes owner, optional pid, node id, trial id, command id,
  resource kind, device assignment, `expires_at`, and `heartbeat_at`.
- Workers should not wait indefinitely for GPU leases.
- If no lease is available, helper returns queued/blocked; worker records
  `blocked_on_resource` in its subagent ledger entry and relevant `node.json`
  notes, then exits.
- Main orchestration agent resumes or respawns work when resource becomes
  available.
- No preemption in v1. Priority only affects queue order before lease
  acquisition.
- FIFO greedy scheduling is enough for v1.
- Scheduler grants queued requests in `queued_at` order but may greedily pack a
  later smaller request if the first request cannot currently fit.
- FIFO greedy scheduling has a starvation guard for blocking official requests.
  If a request is skipped at least 3 times or waits at least 60 minutes, the
  scheduler stops packing smaller later jobs ahead of it and waits for capacity.
- Exploratory nonblocking requests do not get starvation protection by default.
- Queued resource requests are immutable. If a request needs different
  `gpu_count`, `vram_mb`, or capacity hints, cancel/supersede it with reason and
  create a new request linked by `supersedes_request_id`.
- Missing VRAM estimate defaults to full-device lease.
- Multiple concurrent GPU leases are allowed when device capacity permits.
- Multiple GPUs are supported through a frozen device list in run config/state.
- Setup detects GPU devices/VRAM and freezes them into run config.
- Scheduler can perform live sanity checks, for example with `nvidia-smi`.
- If live check materially disagrees with frozen config, log and fail fast or
  queue conservatively rather than overcommitting.
- Config may restrict GPUs using an explicit allowlist and capacity caps.
- Existing `CUDA_VISIBLE_DEVICES` should be respected by default.
- Resource helper returns execution env such as `CUDA_VISIBLE_DEVICES` and
  `AI_SCIENTIST_GPU_LEASE_ID`.
- All official benchmark and final-validation commands go through `resource run`
  as the audit wrapper.
- `resource run` acquires a GPU lease only when the command requests GPU
  resources. CPU-only official commands still use `resource run` for command
  spec hashing, cwd/env capture, logs, exit code, metrics refs, and provenance.
- For GPU-backed commands, `resource run` acquires a lease, sets env, runs the
  command, captures logs, and releases the lease in a finally path.
- Manual acquire/release is allowed but stale lease expiry is only recovery, not
  normal flow.
- `resource run` writes raw command evidence: command log, stdout/stderr,
  command metadata, exit code, start/end times, lease id, and effective
  `CUDA_VISIBLE_DEVICES`.
- Orchestrator writes semantic node evidence into `nodes/<node-id>/node.json`,
  including metrics summary, split/leakage summaries, result summary, mode
  deliverables, and official node transitions.
- Command specs are structured and argv-array by default.
- Command spec supports cwd, argv, env, timeout, stdin/stdout/stderr paths,
  expected output paths, post-run metric parser command, and resource hints.
- `shell: true` is allowed only when setup marks the repo as requiring shell
  entrypoints, and each shell command must include `shell_reason`.
- `shell: true` command specs are high-scrutiny and must be logged.
- Command specs must remain flexible enough for real repos while staying
  auditable.
- Resolve cwd and all declared paths before execution.
- Cwd must be under the node workspace unless explicitly allowed by frozen
  benchmark contract.
- Output/log paths must be under the node artifact directory or approved output
  paths.
- Writes to shared read-only data/env/generated paths are blocked.
- Benchmark command schema and allowed env keys freeze after baseline.
- Env keys affecting split, metric, seed, data path, or benchmark contract are
  protected and compared against baseline.
- Raw command logs are required before accepting any `metrics.json`.
- Metric parser can only read declared raw logs/output files and write the
  declared metrics path.
- Every command spec is hashed and stored before execution.
- `resource run` logs effective env, cwd, argv, lease, and exit code.
- Validator checks command spec hash, command log, metrics, split integrity,
  leakage evidence, benchmark contract version, and raw-log-to-metrics
  provenance.
- Low VRAM estimates are warnings or require config override; missing estimates
  reserve a full device.
- Resource queue affects top-level `phase_status` only when it is the current
  research-loop blocker. If other work can continue, resource waits remain under
  `loop-state.json["state"]["resources"]` while `phase_status` stays focused on
  the active loop state.
- Resource queue state lives in `loop-state.json["state"]["resources"]` in v1.
- `loop-state.json["state"]["resources"]` is the source of truth for resource
  queues and leases.
- The resources object is versioned and contains per-kind resource blocks under
  `resource_kinds`.
- v1 enforces GPU scheduling only. CPU/RAM hints may be logged for audit and
  future use but are not scheduled resources.
- GPU device information is detected/frozen per run and can differ by machine.
- Defaults may describe the local RTX 3070 environment, but schema supports
  arbitrary GPU names, counts, ids, and VRAM.
- GPU records store both physical/detected identity and effective visible CUDA
  identity when known.
- Scheduling enforces both `vram_schedulable_mb` and
  `max_concurrent_leases` per device.
- Default on this RTX 3070 is conservative full-device behavior unless config
  allows packing.
- Stop hook reads resource state from `loop-state.json`, not a separate resource
  file in v1.
- If a future `resources.json` is introduced for concurrency pressure, it must
  be explicitly referenced and treated as authoritative only after that schema
  migration.
- Active resource leases block research completion unless explicitly
  released/expired/abandoned through helper logic with log evidence.
- Queued official resource requests block research completion unless cancelled,
  superseded, or resolved with reason.
- `blocked_on_resource` subagents block research completion unless integrated,
  rejected, or abandoned with reason.
- Resource requests include `blocking` and `purpose`.
- Only blocking/official queued resource requests block completion.
- Official benchmark, final validation, multi-seed, and resource-backed
  leakage/split checks default `blocking: true`.
- Exploratory sweeps default `blocking: false` unless promoted by the
  orchestrator.
- When a node transitions to a terminal rejected/abandoned state, the same helper
  transition should cancel queued resource requests tied to that node and log the
  cancellation.
- Node rejection is refused while active leases for that node exist unless an
  explicit lease action is taken.
- The helper does not automatically kill active resource processes during normal
  node rejection.
- Leases created by `resource run` record PID/process metadata when available,
  including process group id.
- Manually acquired leases may omit PID and therefore have weaker recovery
  semantics.
- `resource run` starts commands in a new process group/session on POSIX when
  supported, so future cancellation can target the command tree.
- v1 supports stale-lease detection/expiry/logging only. Graceful cancellation is
  future work.
- If a resource process is still alive, default behavior is to wait or report a
  blocker rather than auto-cancel.
- Hard kill is destructive and requires explicit configured mode/approval; it is
  not default v1 behavior.
- A provisional good-enough accepted node does not automatically cancel all
  exploratory resource jobs.
- Provisional good-enough status reduces priority and raises the justification
  threshold for new exploratory resource requests.
- If resource pressure is high, low-priority non-blocking exploratory requests
  may be paused/cancelled with log evidence.
- If usage is near warning/cap, scheduling shifts toward required final
  validation and selection work.
- Active non-blocking leases are allowed to finish by default.

### Ideation Decisions

- Normal plugin interface is inline prompt invocation, for example
  `$ai-scientist:ideation <research topic>`.
- Markdown topic files are optional compatibility input, not required.
- Ideation preserves the original AI-Scientist-v2 action-loop concept:
  reflection asks for one action, either `SearchSemanticScholar` or
  `FinalizeIdea`.
- Semantic Scholar calls are run by plugin helper code and logged to
  `journal.jsonl` as API-call entries.
- `S2_API_KEY` is optional by default. Strict authenticated-search mode may fail
  fast when the key is missing.
- Ideation writes one canonical plugin idea object. Upstream-style fields may be
  accepted as input aliases for normalization, but the persisted `ideas.json`
  contract should not keep separate `upstream` and `normalized` wrappers.
- Premature `FinalizeIdea` is rejected and the same idea continues reflection.
- Rejected ideas continue the loop. They are excluded from successful handoff,
  but if reflection budget is exhausted they remain in final JSON with
  `evaluation: "REJECTED"`.
- If all ideas fail and reflection is exhausted, successful research handoff
  requires at least one accepted idea. Otherwise ideation exits as exhausted with
  denied handoff.
- At least one plain `ACCEPTED` idea is required for default successful research
  handoff.
- `ACCEPTED_WITHOUT_REFERENCE` ideas are kept and scored but are manual-selection
  only by default.
- A dedicated ranking agent runs after idea generation.
- Ranking scores all ideas, including rejected and accepted-without-reference
  ideas.
- Ranking sorts by overall score, with raw score table evidence including
  citation support, novelty, and venue/journal/conference strength.
- Ranking score components are stored in idea JSON.
- Ranking should preserve original order when scores tie.
- Ranking errors are logged; malformed entries are removed rather than silently
  accepted.
- Ideation writes a run-local `config.json`; arbitrary override filenames are
  not supported.
- Config uses deep merge semantics for project defaults and run-local values.
- Config includes venue-impact or equivalent venue scoring data as a field in
  `config.json`.
- Default venue/impact contribution should be balanced lower than raw citation
  and recency strength; it is used for selection support, not as the only sort
  key.

### Ideation Loop V1 Implementation Status

Current code has only partially reached the desired architecture. It uses the
same compact artifact direction as research-loop v1, but the main loop is still
Python-driven and must be replaced.

- Normal input is an inline prompt through `$ai-scientist:ideation <topic>` or
  the orchestrator `--prompt` implementation detail.
- The existing Python orchestrator preserves the action-loop shape, but it still
  owns `for idea` / `for reflection round` loops and can launch nested
  `codex exec`. This is not the final v1 architecture.
- Semantic Scholar calls are executed by plugin helper code and logged to
  `.ai-scientist/runs/<run-id>/journal.jsonl` as `event_type: "api_call"`.
- Handoff and validation evidence are logged to `journal.jsonl`; new compact
  ideation runs no longer create `api-ledger.jsonl`, `handoff.jsonl`,
  `stop-hook-events.jsonl`, or `journal.json`.
- Run-local `config.json` carries dependency/config context. A separate
  `dependency-plan.json` is legacy fallback only.
- `FinalizeIdea` before literature evidence is rejected with a specific reason
  and the same idea continues until the reflection budget is exhausted.
- `ideas.json` keeps valid idea objects in generation order. Rejected ideas are
  retained with `evaluation: "REJECTED"`; plain `ACCEPTED` ideas are required
  for default research handoff; `ACCEPTED_WITHOUT_REFERENCE` remains
  manual-selection only by default.
- A dedicated ranking agent scores all valid ideas and assigns dense ranks only
  to plain `ACCEPTED` ideas.
- `validate_run.py --gate ideation_to_research` now checks compact config,
  `journal.jsonl` API-call evidence, journal handoff evidence, accepted ranked
  ideas, and loop completion.

### Agent-Driven Ideation Loop Redesign

The final ideation loop must follow the research-loop architecture: the current
Codex session is the long-running orchestrator, and the Stop hook prevents it
from ending until the ideation criteria are met. Python must not own the
reflection loop and must not spawn nested Codex sessions.

Accepted redesign decisions from the interview:

- The old Python ideation loop is retired. No backward compatibility is needed.
  Delete the Python loop path rather than preserving a runnable legacy
  orchestrator.
- Normal ideation starts through a deterministic state helper command such as
  `ai_scientist_state_cli.py ideation start --prompt "<topic>" --run-id <id>
  --strictness-mode <mode>`.
- `ideation start` is state management only: create `active-run.json`,
  `loop-state.json`, run-local `config.json`, initial `journal.jsonl`, and an
  orchestrator cursor. It must not generate ideas, call Codex, rank ideas, or
  run reflection loops.
- Python helper responsibilities are deterministic only: state transitions,
  Semantic Scholar calls, idea normalization, finalization gate checks, critic
  verdict recording, ranking artifact recording, validation, handoff, and
  journal writes.
- The main Codex session decides each loop action. It uses helper commands such
  as `ideation resume`, `ideation set-next-action`,
  `idea search-semantic-scholar`, `idea critic-record`, `idea finalize`,
  `idea reject`, `ideation rank-finalize`, `ideation complete`, and
  `ideation exhaust`.
- The helper is the source of truth for `next_action`. After every
  state-changing command it recomputes the cursor from `loop-state.json`,
  `ideas.json`, and `journal.jsonl`. Arbitrary agent-written
  `ideation set-next-action` is removed or kept only as a debug/admin escape
  hatch so the Stop hook cannot be bypassed by stale cursor text.
- The ideation Stop hook is mostly read-only. It may append a lightweight
  `stop_blocked` journal event for audit, but it must not advance slots, create
  drafts, run S2, rank, mark ideas terminal, or complete the loop. Its job is to
  recompute the required action and block session end until helper-recorded
  progress satisfies the criteria.
- Ideation Stop hook allows ending only for `COMPLETED`,
  `COMPLETED_BUDGET_EXHAUSTED`, `EXHAUSTED_NO_CANDIDATE`, or `CANCELLED`.
  `EXHAUSTED_NO_CANDIDATE` is terminal but not valid for research handoff.
- Native Codex subagents are coordinated with durable intent records, not
  Python spawning. Before spawning a generator/critic/ranker, the orchestrator
  records an intent with role, idea id when applicable, draft version/hash when
  applicable, status, and timestamps. Completion records the subagent output and
  clears the waiting state. This gives the Stop hook a durable
  `waiting_for_subagent_result` cursor.
- If a subagent intent is pending and no result has been recorded, Stop hook
  blocks with `next_action: record_subagent_result` and includes the pending
  intent id, role, and idea id. It does not infer failure or auto-cancel; the
  orchestrator must record completion or explicitly cancel the intent.
- Subagent output commands default to inline JSON arguments. Optional
  `--path logs/...json` input is allowed for oversized outputs, and the helper
  normalizes either form into canonical run files/state.
- Generator subagents may return free structured output, but the orchestrator
  converts it to the canonical plugin idea schema before calling `idea draft`.
  The helper validates and stores the canonical object; it does not infer
  missing research semantics or rewrite the idea.
- Mode differences are presets in global plugin configuration, not hardcoded
  branches scattered through code. Users can tune global defaults.
- `ideation start` deep-merges plugin defaults plus `.ai-scientist/config.json`
  overrides and freezes the effective preset into run-local
  `runs/<run-id>/config.json`; resume/finalize/rank read the frozen run config.
- If no ideation mode is specified, use the plugin-wide default from
  `.ai-scientist/config.json`; if absent, default to `scientist`. Mode is frozen
  once the run starts.
- Presets control S2 requirements, novelty requirements, missing-reference
  behavior, critic prompt, critic thresholds, ranking focus, and scoring
  weights.
- For `scientist` and `researcher`, S2/literature evidence and novelty rationale
  are required before plain `ACCEPTED`.
- For `balanced`, missing S2 may produce `ACCEPTED_WITHOUT_REFERENCE`.
- For `builder` and `engineer`, S2 is optional and missing references should not
  penalize the idea. S2 is a tool for architecture/performance inspiration, not
  a gate.
- `builder` and `engineer` critic prompts focus on whether the approach is
  likely to work and improve performance. `scientist`/`researcher` critic
  prompts focus more on novelty, ablation, and publishable evidence.
- Every idea requires a critic verdict before it can become plain `ACCEPTED`,
  regardless of mode.
- Critic prompt text lives in the frozen mode preset. The critic schema is fixed
  across modes, while thresholds and interpretation are mode-specific.
- Critic verdict schema:
  `verdict`, `score`, `strengths`, `weaknesses`, `required_revisions`,
  `mode_specific_assessment`, and `risk_flags`.
- Add a first-class `critic_event` journal event type. Full critic output may be
  stored under `logs/<run-id>/critics/<idea-id>-<round>.json`; source-of-truth
  gate fields live in `loop-state.json`.
- `idea finalize` accepts a canonical idea JSON from the orchestrator, validates
  it deterministically, and either records `ACCEPTED`,
  `ACCEPTED_WITHOUT_REFERENCE`, `REJECTED`, or returns a structured refusal with
  the next action.
- Canonical idea archive remains `ideas.json` as an array because ranking and
  validation need the full list. Per-action history remains in `journal.jsonl`.
- `ACCEPT` critic verdict can become plain `ACCEPTED` only if deterministic mode
  gates pass. `ACCEPT_WITHOUT_REFERENCE` can become
  `ACCEPTED_WITHOUT_REFERENCE` when the mode allows it. `REVISE` blocks
  finalization and returns required revisions. `REJECT` records rejection when
  the orchestrator explicitly rejects or the reflection budget is exhausted.
- After a critic returns `REVISE`, the orchestrator may either revise the same
  idea thread with `idea revise-start --idea-id ...` or explicitly abandon it
  with `idea reject --idea-id ... --reason abandoned_after_revise`, then resume
  to start/retry the slot. Hidden replacement is not allowed.
- Search can happen before or after critic. Critic receives current idea plus
  search evidence when available. If critic requests reference checking, helper
  records the next action as `search_semantic_scholar`.
- The orchestrator, not Python, invokes critic and ranking agents. The helper
  only records their outputs and enforces deterministic gates.
- Prompt templates live in frozen run `config.json` mode presets. The
  orchestrator reads the template and fills simple placeholders from current
  state. The helper validates required templates exist at start, but does not
  author critic/ranking prompts.
- Helper records idea drafts before criticism/finalization. Each `idea draft`
  increments `draft_version`, writes `logs/<run-id>/drafts/<idea-id>-vNN.json`,
  and stores helper-computed `idea_hash` in loop state.
- Critic verdicts are tied to the reviewed draft by `draft_version` and
  helper-computed `idea_hash`. `idea finalize` requires the latest critic
  verdict to match the latest draft; otherwise it returns
  `critic_stale_for_current_idea`.
- Critic agents are short-lived. Spawn a fresh critic for each revised draft,
  but include the previous verdict, required revisions, and a concise change
  summary in the new critic prompt so continuity is preserved without reusing a
  long critic context.
- `idea finalize --idea-id <id>` finalizes the latest recorded draft by default,
  rather than requiring the orchestrator to pass the whole idea JSON again.
- Multiple drafts per idea are allowed. Older drafts stay as audit history, but
  only the latest draft can be finalized unless restored as a new latest draft.
- Semantic Scholar evidence attaches to both `idea_id` and the current
  `draft_version` when available. Finalization may use any valid evidence for
  the same idea thread by default.
- Reflection budget counts meaningful per-idea actions: draft, search,
  critic-record, explicit reject, failed finalize that returns a next action,
  and successful finalize. Passive resume, validation, and Stop-hook checks do
  not count.
- Budget-exhausted ideas are not silently auto-rejected. The helper exposes
  `idea exhaust --idea-id ...`; Stop hook blocks until the orchestrator records
  a terminal reason.
- Ideation tracks both attempted slots and successful handoff threshold:
  `num_ideas_required` defaults to 10 attempted idea slots, while
  `min_candidates_required` defaults to 1 researchable candidate under the
  frozen mode config.
- Asking for "10 ideas" does not imply 10 accepted ideas by default. Ranking
  still ranks all accepted ideas; users can explicitly raise
  `min_candidates_required`. Producing N researchable candidates can become a
  separate pipeline/setting later.
- Successful completion requires no pending subagent intent, no active
  unterminated idea draft, attempted slots reaching `num_ideas_required` unless
  early stop is explicitly configured, at least one researchable candidate under
  the frozen mode config, finalized ranking, a valid selected candidate, and a
  passing `ideation_to_research` validator. Ideation produces a research-ready
  handoff only; it does not start the research loop by default.
- Terminal ideation statuses are `COMPLETED`,
  `COMPLETED_BUDGET_EXHAUSTED`, `EXHAUSTED_NO_CANDIDATE`, and `CANCELLED`.
  `COMPLETED_BUDGET_EXHAUSTED` means budget exhausted but at least one
  researchable candidate exists, so ranking and handoff are still required.
  `EXHAUSTED_NO_CANDIDATE` means budget exhausted with no researchable
  candidate; Stop hook allows ending, but `ideation_to_research` fails.
- `EXHAUSTED_NO_CANDIDATE` writes a compact final summary of attempted ideas,
  rejection reasons, critic failure patterns, S2 failures if any, and why no
  candidate was researchable. It writes no research handoff.
- If any researchable candidate exists, ranking is required before ending even
  when budget is exhausted. If there are zero candidates, exhausted summary can
  end the loop without ranking.
- `ideation cancel --reason ...` is supported in v1. It sets `CANCELLED`, marks
  pending intents cancelled, writes a journal event, and allows Stop hook exit
  without deleting artifacts or producing a valid handoff.
- Idea slots are created lazily. `ideation start` records
  `num_ideas_required`, and `ideation resume` returns `start_next_idea` when no
  active idea exists and attempted slots remain.
- Helper assigns sequential idea ids by default; manual ids are only for
  recovery/tests.
- Mode presets include `idea_generation_prompt_template`,
  `critic_prompt_template`, and `ranking_prompt_template`.
- The helper validates required templates exist in the frozen run config at
  `ideation start`.
- Mode presets define required canonical idea fields and mode-specific guidance.
  The helper enforces structural fields lightly, while semantic concerns such as
  abusive tuning, cherry-picking, and research-vs-engineering suitability are
  left to critic/ranking agents and later research validation.
- Hyperparameter sweeps, ensembling, training tricks, and pragmatic tuning are
  allowed in all modes. Scientist/researcher prompts warn against abusive
  tuning/cherry-picking and ask for fair comparison/ablation; builder/engineer
  prompts can treat pragmatic tuning as a valid main idea.
- `ideation complete` requires ranking to have run even if only one idea is
  accepted.
- `rank-finalize` accepts one structured ranking payload covering every terminal
  valid idea, with score components, rationale, risk flags, and selected idea.
  Only plain `ACCEPTED` ideas receive dense ranks. Rejected and
  accepted-without-reference ideas receive scores but `rank: null`.
- Ranking includes all terminal non-malformed ideas by default. Plain
  `ACCEPTED` ideas are dense-ranked. `ACCEPTED_WITHOUT_REFERENCE` receives score
  and rationale, and can be manually selected only when the frozen run config
  allows selection without references.
- Ideation produces multiple ranked researchable candidates. `selected_idea_id`
  is the default candidate, but later research start consumes exactly one idea
  per research run and may select another candidate explicitly with
  `--idea-id`. Research start freezes the selected canonical idea, ranking
  rationale, mode config snapshot, and evidence summary into the research run so
  later edits to the ideation run do not mutate started research.
- `ideation_to_research` means "safe for research to consume," not "start
  research." Starting research remains a separate explicit user action.
- `ACCEPTED_WITHOUT_REFERENCE` can be a researchable selected candidate only
  when frozen config allows selection without references. Defaults:
  scientist/researcher false; builder/engineer true; balanced true with a
  handoff warning.
- `ideation resume` defaults to compact JSON. `ideation resume --prompt` prints
  a concise orchestration instruction block derived from frozen config and the
  current cursor for the main Codex orchestrator.
- Idea generation, substantive revision, critic, and ranking prompts specify
  model/effort from mode presets. For v1, `gpt-5.5` with `xhigh` is explicitly
  specified for all substantive idea-generation agents, but helper commands do
  not fail solely on missing model metadata.
- The orchestrator must spawn a separate idea-generation subagent for each
  substantive idea draft/revision; it should not draft ideas itself.
- V1 uses one idea-generation subagent per idea slot rather than batch
  generation.
- Failed generator output retries the same slot. A failed generation attempt
  counts as a loop iteration, but v1 has no separate hard retry cap beyond the
  reflection/iteration budget.
- Delete the Python-owned ideation orchestration path. Deterministic pure
  functions from the old implementation may be reused only if moved into helper
  modules. There is no compatibility wrapper, nested `codex exec`, or
  Python-owned reflection loop.
- Agent-driven ideation logic lives in a dedicated `ideation_state.py` module,
  with thin command wiring in `ai_scientist_state_cli.py`. Tests target
  `ideation_state.py` directly where practical.

### Workspace And Source Control

- Research-loop v1 requires a Git repository.
- Clean source worktree is required before research start, ignoring
  `.ai-scientist/`.
- The target source tree outside `.ai-scientist/` is not mutated during the
  loop.
- All mutable research work happens under `.ai-scientist/runs/<run-id>/`.
- Per-node workspaces are copy-based, not git worktrees.
- Node workspaces live under
  `.ai-scientist/runs/<run-id>/nodes/<node-id>/workspace/`.
- Baseline source lives at
  `.ai-scientist/runs/<run-id>/baseline-workspace/`.
- Workspace setup happens before dependency planning.
- Setup agent creates a frozen workspace plan inside
  `.ai-scientist/runs/<run-id>/config.json` after clean check.
- If a reusable workspace plan exists in project `.ai-scientist/config.json`,
  reuse it as input; otherwise generate once per run and freeze the resolved
  plan in run `config.json`.
- Workspace setup auto-approves only after strict validation.
- Unsafe or incomplete workspace plans fail fast with logs.
- Essential configs are copied.
- Caches and generated outputs are ignored.
- Symlink criteria is "large but needed", not hiddenness or path name.
- Large shared data/env paths are linked read-only.
- Source directories containing code are copied even if large; setup decides
  symlinks by inspecting project structure.
- Research agents may access allowed environment/config files read-only.
- `bwrap` is required when shared/heavy paths are mounted read-only.
- Missing `bwrap` is a hard blocker when the plan requires read-only binds.
- Do not bwrap Codex CLI/subagents by default; use bwrap for
  orchestrator-controlled commands that need read-only shared paths.
- Validator ignores full workspace contents and checks metadata/artifacts.
- `patch.diff` compares node workspace to instrumented baseline workspace,
  excluding shared data/env/cache/output paths according to
  `config.json["workspace"]`.

### Dependencies And Environment

- Dependency planning is separate from workspace setup.
- Dependency planner inspects selected idea, benchmark command, source/workspace
  tree, import probes, and likely implementation architecture.
- Dependency planning/approval happens during setup before research starts.
- Default dependency mode is `frozen`.
- In `frozen` mode, after approved setup and successful baseline, the
  environment is frozen.
- In non-yolo/frozen mode, agents should not ask for dependencies mid-loop. They
  must work with what they have.
- If an unapproved dependency appears in frozen mode, reject the node and
  continue.
- `yolo` mode permits agents to install packages into run-local env/layer
  without approval.
- There is no mid-loop human approval by default.
- Optional mode may allow extra mid-loop dependency install, but it is not the
  default and should not pause the loop unless explicitly configured.
- Approved installs are automatic after initial user approval.
- Use run-local env/layer; source env is read-only.
- Avoid full env copy where practical, but run-local env is acceptable.
- Conda/system-level dependency needs fail fast in v1.
- Dependency confidence levels are enum-like fields in the dependency section of
  run `config.json`.
- Import probes are run for high-confidence and lightweight maybe-confidence
  packages.
- Maybe-confidence packages with failed size estimation are still installable.
- Package size threshold default is 50 MB full install footprint including
  dependencies.
- Network is allowed for package size estimation when configured.

### Baseline, Benchmark, Metrics

- `benchmark_command` is the frozen entrypoint/evaluation command, not a frozen
  hyperparameter set.
- Benchmark command must preserve dataset/split/metric/output contract.
- Benchmark command should be flexible enough for node-local config/code to
  express hyperparameter tuning and method variation.
- Nodes may edit node-local config files consumed by the frozen benchmark
  command.
- Setup may create a benchmark adapter if the target repo lacks a flexible
  enough entrypoint.
- Benchmark adapter is created in the run-local instrumented baseline workspace,
  not the source repo.
- Benchmark adapter is part of the instrumented baseline.
- Node patches are compared against instrumented baseline including the adapter.
- Node workers may not edit the benchmark adapter directly by default.
- Workers may request adapter extensions in their `node.json` recommendation or
  a journal entry. Use a separate request file only for large payloads that do
  not fit cleanly in those compact artifacts.
- Main orchestrator owns adapter extensions.
- Approved adapter extension changes the benchmark contract version.
- Adapter contract changes require baseline rerun.
- Nodes using older benchmark contract versions remain historical attempts and
  are not comparable for final selection unless rerun.
- Adapter extensions after any accepted node exists are rejected by default.
- Exception after accepted nodes only when the current benchmark contract is
  proven invalid; then previous accepted nodes become non-comparable and must be
  rerun under the new contract.
- Baseline run happens before experiment changes.
- Baseline uses copied/instrumented baseline workspace, approved env, and frozen
  benchmark command.
- Baseline writes command log and `metrics.json`.
- Any baseline failure becomes `blocked_on_user`; research loop starts only
  after successful baseline.
- Environment and mode freeze after baseline succeeds.
- Metrics extraction supports direct `$AI_SCIENTIST_METRICS_PATH` JSON and a
  deterministic parser from stdout/logs.
- Setup may add a small instrumentation patch before baseline in run-local
  baseline workspace only.
- Nodes start from instrumented baseline.
- Experiment nodes can change files used by benchmark command, but not the
  command/metric/split contract.
- Trial seeds and paths should be passed via environment variables first.

### Node Tree And Trials

- Research loop uses an idea-level tree.
- One node is one research direction/approach.
- Repairs, debugging, hyperparameter tries, ablations, and seed validation are
  trials inside the same node, not child nodes.
- Child/branch nodes are only for idea-level different approaches/refinements or
  new directions.
- Node statuses include `planned`, `implementing`, `running`, `buggy`,
  `repairing`, `candidate`, `validating`, `accepted`, `invalid`, and `rejected`.
- Baseline-beating but lacking required mode evidence stays `candidate`.
- Accepted means eligible for selection, not necessarily best.
- Scientist mode cannot finish with only candidates.
- Buggy nodes record failure signature, command, exit code, error path,
  attempted fix count, retryability, parent/hypothesis, and next action.
- Node trials can live under `trials/<trial-id>/` artifacts/logs.
- `node.json.trials` is a flat list, not nested by purpose/phase.
- Each trial record includes `trial_id`, `purpose`, `status`, `command_ref`,
  `metrics_ref` or `metrics`, `resource_lease_id`, `seed`, `started_at`,
  `ended_at`, `benchmark_contract_version`, and short `notes`.
- Trial `purpose` values include `smoke`, `benchmark`, `ablation`, `sweep`,
  `multiseed`, `leakage_check`, `split_check`, and `manual_probe`.
- Trials use same code workspace with isolated output dirs.
- Fresh per-trial workspace is used only if output isolation cannot be
  guaranteed.

### Strategist And Branching

- Strategist agent is separate from implementation/repair agents.
- Strategist proposes a small ranked queue, executed serially.
- Queue is regenerated after every completed node.
- Queue item types include `new_approach`, `refinement`, `ablation`,
  `seed_validation`, and `stop_and_select`.
- Strategist gets mode goals and required deliverables.
- Ordinary branching should not expose exact scoring weights to strategist to
  avoid overfitting.
- Implementation agents inspect prior work through journal summaries/results by
  default.
- If explicitly branching from a prior node, the branch starts from that node's
  workspace/patch.
- Mode is fixed once the loop starts rolling.
- Default mode is `scientist`.
- Bugginess is not treated as idea failure by itself.
- Buggy node evidence is preserved.
- Main orchestration agent and strategist decide case by case whether to repair,
  branch, defer, or reject a buggy node.
- Repair-vs-branch decisions must be logged with rationale.
- Strategist is invoked for buggy nodes only when the repair path is no longer
  obvious.
- Stop hook must not invent strategy. It only points to recorded
  `orchestrator.next_action`; if that is missing or stale, it blocks with a state
  repair/checkpoint instruction.
- `orchestrator.next_action` uses a small stable lane enum:
  `setup`, `baseline`, `node_work`, `resource_wait`, `integration`,
  `validation`, `strategy`, `selection`, `completion`, and `blocked`.
- `next_action_details.verb` is free-form in v1, with required non-empty
  `reason`.
- Helper validates the lane, details object shape, required reason, and
  referenced node/subagent ids when provided.
- Free-form verbs are provisional and should be revisited if they become messy.
- Active research with missing `orchestrator.next_action` blocks Stop.
- Every `next_action` update appends to
  `.ai-scientist/runs/<run-id>/journal.jsonl`.
- The same helper call that updates `next_action` writes the journal entry so
  state and audit trail do not drift.
- Resume is first-class and expected.
- Active run can resume from any Codex session in the same project.
- State, not session identity, controls continuation.
- Session ownership changes are logged, not treated as suspicious by default.
- If duplicate live orchestration is detected, block/recover to avoid split
  brain.
- `research resume` explicitly checkpoints ownership, inspects active state,
  detects stale subagents/resources, and writes a resume journal event.
- If state is coherent, `research resume` smoothly continues from the recorded
  checkpoint and `orchestrator.next_action` without asking the user.
- `research resume` may infer a narrow safe set of next actions, such as
  integration for completed/failed unintegrated subagents, resource wait for
  blocking official resource requests, validation for validating phase, or
  selection when accepted nodes exist without final selection.
- If state is ambiguous or corrupted, `research resume` blocks with structured
  recovery options rather than guessing.
- `research resume` automatically expires stale resource leases only when
  process-gone evidence is strong.
- Safe stale lease expiry requires `resource run` ownership, recorded
  PID/process group, verified process absence, and resource log entry.
- Leases with unknown PID or unverifiable process state are reported as blockers
  rather than auto-expired.
- `research resume` cancels queued requests tied to rejected/abandoned nodes or
  superseded requests with log evidence.
- `research resume` does not cancel queued requests merely because they are old.
- Duplicate live orchestration is detected through advisory
  `loop-state.json["state"]["orchestrator_lock"]`.
- `orchestrator_lock` records owner session, optional pid, acquired time,
  heartbeat time, and status.
- `research resume` acquires or refreshes the orchestrator lock.
- If a fresh lock belongs to a different owner, resume fails with
  `duplicate_orchestrator`.
- If the lock is stale, the new session may take over and logs the takeover.
- Default orchestrator lock stale threshold is 30 minutes, configurable.
- Orchestrator refreshes lock heartbeat around major actions such as resume,
  subagent spawn/completion, resource run boundaries, and finalization.
- Stop hook does not mutate orchestrator lock.

### Strictness Modes

- Strictness mode is research direction/claim type, not simply effort level.
- `scientist` should try to preserve the initial idea as the main claim, while
  allowing aligned refinement.
- `researcher` may drift toward emergent contribution with novelty refresh.
- `balanced` requires practical/research middle ground and lightweight
  ablation/sensitivity.
- `engineer` and `builder` prioritize practical performance and do not require
  novelty by default.
- Mode deliverables are config-driven defaults frozen into run config.
- Validator enforces structural requirements and thresholds; nuanced scientific
  judgment lives in review/artifacts.
- `scientist` requires at least one accepted node plus ablation evidence for the
  same approach.
- `researcher` requires ablation/mechanism evidence and novelty refresh by
  default.
- `balanced` requires lightweight ablation/sensitivity evidence.
- `engineer` and `builder` have optional ablation unless configured.
- No mode permits leakage, split manipulation, or deceptive scoring.

### Seeds And Sweeps

- Split/data seed is separate from training/model seed.
- Split seed is fixed for all modes.
- Setup may infer/freeze split seed/policy; ambiguity blocks before baseline.
- Normal exploration uses one fixed configurable training seed, default `0`.
- Multi-seed validation runs only at end-stage, not during normal branching.
- `scientist` and `researcher` multi-seed final validation default true.
- Multi-seed final validation runs only on plausible final candidates within a
  configurable selection-score band, default 5 points.
- Multi-seed baseline runs first.
- Candidate multi-seed runs only if baseline multi-seed succeeds.
- Seed `0` exploration trial can be reused if benchmark/env/split/output/metric
  contract matches.
- Otherwise the seed-0 trial is rerun.
- Multi-seed acceptance requires mean improvement over paired baseline and no
  severe regression seed.
- Severe regression default is 5 percent relative worse than paired baseline,
  configurable.
- Minimum mean improvement default is 0.
- Final selection/evidence decides practical value beyond minimum improvement.
- A barely positive mean but weak evidence candidate may be accepted if
  structural criteria pass, then ranked low.
- Sane hyperparameter sweeps are allowed inside a node.
- Seed picking must not abuse train/test split or cherry-pick easier splits.

### Integrity And Leakage

- Split integrity evidence must show baseline and node use the same split.
- Split seed is fixed.
- No test labels may be used in training.
- Split files/configs must not be changed across comparable runs.
- Deterministic integrity checks are optional behind
  `research.require_deterministic_integrity_checks`.
- Default deterministic integrity check flag is false for all modes.
- If the flag is false, agents are not instructed to create deterministic
  checks.
- If checks exist anyway, run and log them.
- Optional check failure can override agent evidence and block/reject a node.
- Split/leakage evidence is produced by a separate validator/critic agent, not
  by the implementation agent.
- Leakage/split validator runs on candidate/best nodes.
- Agent-written evidence is allowed with explicit limitations when
  deterministic checks are absent.

### Novelty

- Novelty refresh is late-stage only, not a branching input.
- Novelty refresh is required for scientist/researcher candidate acceptance by
  default.
- Novelty refresh runs once near the end after final candidate(s), as
  double-check/positioning gate.
- It checks duplicate/prior art, related work, and claim positioning.
- If novelty refresh fails, log clearly.
- Selection/claim agent decides whether to try next candidate, continue
  branching if budget remains, reframe allowed-mode claim, or exhaust.
- Mode remains fixed; no auto-downgrade.
- Node failing novelty is not accepted for scientist/researcher.
- Practical evidence can still be retained.
- Use review-style numeric scores rather than verbose enums.
- Novelty scores include `novelty_score`, `positioning_score`,
  `evidence_score`, and `overall_research_claim_score`.
- Component scores use 0-10 scale.
- Default novelty threshold: scientist >= 8, researcher >= 6, plus no duplicate.
- Scientist requires novelty score itself to meet threshold.
- Researcher can pass with lower novelty if overall strong and not duplicate.
- Novelty agent sees claim, method, results, ablation evidence, and related
  papers, not full code by default.
- Novelty refresh uses the Semantic Scholar client plus `journal.jsonl` API-call
  entries and cache pattern.
- Balanced does not run novelty refresh by default.
- Builder/engineer selection artifacts state novelty was not evaluated.
- Novelty refresh does not influence branching by default, to avoid anchoring
  emergent novelty too early.

### Selection And Scoring

- If budget ends with at least one accepted node, research succeeds by selecting
  the best accepted node.
- If no accepted node exists, research exhausts with denied handoff, exit 0, and
  retained candidate evidence.
- Final selection uses mode-specific `selection_score`, not raw benchmark only.
- `metrics.json.score` remains benchmark performance.
- `selection_score` lives in `selection.json`.
- Dedicated selection agent produces a score table.
- Agent fills judgment components and rationales.
- Python/helper computes weighted final score deterministically.
- Selection weights are mode-specific config defaults frozen in run config.
- Selection agent cannot override weights.
- Benchmark performance component is deterministic from metrics.
- Robustness component is deterministic from multi-seed stats.
- Novelty component for scientist/researcher comes from novelty refresh.
- Ablation strength and implementation quality are scored by selection agent.
- Component scores are 0-10.
- Final `selection_score` is 0-100.
- Selection table includes raw component scores and weighted score for every
  accepted node.
- Final selected node is stored in `loop-state.json` and `selection.json`.
- `selection.json` ranks accepted nodes and separately summarizes candidates and
  rejections.
- `selection.json` is the detailed source of truth for selection/ranking.
- `loop-state.json["state"]["selection"]` stores only a minimal gate summary and
  `selection_ref`.
- `run-status.json` is a user-facing status snapshot derived from canonical
  state, not a source of truth.
- Helpers may update `run-status.json` after canonical transitions.
- Validators cross-check canonical files rather than trusting `run-status.json`
  alone.
- Interim selection runs after every new accepted node.
- Interim selection uses the same frozen weights and score formula as final
  selection, but may mark late-stage evidence as provisional/missing.
- Interim selection is stored in the same `selection.json` as final selection,
  with `selection_status: "interim"`, `provisional: true`, and history entries.
- Final selection updates the same file with `selection_status: "final"` and
  `provisional: false`.
- A provisional good-enough node can shift strategy toward final validation but
  cannot complete research while required final evidence is missing.
- `selection finalize` is a validated helper transition after accepted nodes and
  required final evidence are ready.
- Selection agent writes candidate/report content into `selection.json`; the
  main orchestration agent reviews it.
- Helper finalizes official selected node into `selection.json`,
  `loop-state.json`, optional `run-status.json` snapshot, and `journal.jsonl`.
- Helper recomputes deterministic weighted scores from component scores and
  frozen weights.
- Deterministic `selection_score` is the default sort key and audit filter, not
  an absolute replacement for research judgment.
- Orchestrator may manually select a lower-scoring accepted node with structured
  rationale.
- Manual selection override is allowed for all modes, with stricter scrutiny for
  engineer/builder when overriding substantially better performance.
- Manual override must record default top node, selected node, score delta, and
  rationale discussing the score tradeoff.
- Manual override can select only accepted nodes.
- Candidate nodes cannot be selected by finalization until missing evidence is
  completed and the node transitions to accepted.
- Final selection must rank every accepted node from loop state.
- If any accepted node is missing from `selection.json.ranked_nodes`,
  finalization fails.
- Manual override review is required when score delta exceeds a configurable
  threshold, default 5 selection-score points.
- Scientist mode also requires reviewer signoff when manual override changes the
  claimed contribution or methodology, regardless of score delta.
- Scientist mode may select lower benchmark score if novelty/evidence/methodology
  is stronger.
- Builder/engineer exclude novelty from score by default; performance and
  reliability dominate.
- Balanced includes novelty lightly but does not run novelty refresh by default.
- `good_enough_score_threshold` default is 75.
- At usage cap, accepted node with selection score >= 75 finalizes; otherwise
  state blocks for resume.

### Usage And Budgets

- Primary loop cap is Codex app-server usage, not node count.
- Use experimental app-server rate-limit API if available:
  `account/rateLimits/read`.
- Rate-limit response includes `usedPercent`, `windowDurationMins`, and
  `resetsAt`.
- Usage polling is done by helper/orchestrator-side code, not inside prompts.
- Usage polling should not consume LLM tokens.
- Polling cadence default is 10 minutes.
- Poll usage at setup, baseline, final selection, and before new strategist
  round/node if last check is older than 10 minutes.
- Do not increase polling after 85 percent.
- 85 percent is warning only; log and optionally make strategist conservative.
- Usage cap threshold default is 95 percent.
- Capped mode fails fast if app-server API is unavailable.
- `no_limit_host_cap` bypasses the host cap with a warning but still logs usage
  if available.
- At >= 95 percent, finalize if accepted good-enough node exists.
- At >= 95 percent without good-enough accepted node, write
  `blocked_on_usage_limit` with `resetsAt` and allow Stop.
- Resume after reset is user/Codex-invoked, not a background job.
- Checkpoint before every LLM/subagent call through deterministic state helper.
- Hard host limit may prevent cleanup; last checkpoint is recovery source.
- Usage cap does not stop benchmark commands; benchmark runtime is governed
  separately by timeout/wall/GPU budgets.
- Secondary caps may include max trials, repair attempts, wall time, and GPU.

### Export To Branch

- Export-to-branch is v1 scope.
- Branch from current target `HEAD`.
- Clean worktree required unless explicit override.
- Branch name is autogenerated.
- Commit is automatic.
- Commit includes only experiment code changes, not `.ai-scientist/` artifacts.
- Export defaults to accepted/selected nodes only.
- Rejected/buggy export is manual override only if supported.
- Export-to-branch does not require `research_to_review` passed, but unvalidated
  exports are labeled.
- Applies experiment changes only by default, not setup instrumentation.
- Refuse export if selected patch touches shared read-only data/env/generated
  paths.
- Patch is relative to instrumented baseline workspace.
- If the selected node depends on a benchmark adapter added to the instrumented
  baseline, export includes adapter changes by default only when they are
  required to run the selected experiment in the target repo and do not alter the
  benchmark/split/metric contract after final validation.
- Export separates or clearly labels experiment changes and required adapter
  changes. If adapter changes were orchestration-only, exclude them.
- If adapter changes altered the benchmark contract and the selected node was
  not revalidated under that contract version, refuse export.

### Already-Decided Implementation Surfaces

These are not open design questions; they are implementation tasks that encode
the resolved behavior.

- Helper CLI is one script with strict subcommands for run control, including
  `research start`, `research resume`, `research checkpoint`,
  `research set-next-action`, `research complete`, `research cancel`, node
  transitions, subagent ledger updates, resource queue/run helpers, and
  `selection finalize`.
- Validator gates are decided: fail on active/incomplete phases, unresolved node
  states, unresolved blocking subagents/resources, missing baseline evidence,
  missing accepted-node evidence, missing split/leakage evidence, missing mode
  deliverables, missing selected-node evidence, benchmark contract mismatch, or
  missing/passing-false completion audit.
- Stop-hook decision behavior is decided: read `active-run.json` and
  `loop-state.json`, fail closed on hook errors, block while active, reopen
  terminal-without-audit phases as `verifying`, pass explicit cancellation or
  blocked terminal outcomes, and allow normal Stop only after passing completion
  audit and required validation/handoff evidence.
- Node acceptance behavior is decided through strictness mode, fixed split
  policy, leakage/split checks, benchmark evidence, mode deliverables, optional
  multi-seed final validation, novelty refresh where required, and final
  selection scoring.

### V1 Cutline

The v1 target is the hard part: a Codex-native improvement loop that actually
continues, improves, accepts a good node, and exits only when criteria are met.

V1 required scope:

- Current Codex session can act as the continuous research orchestrator.
- Project-local Stop hook prevents premature ending while research is active.
- `loop-state.json` plus `journal.jsonl` preserve enough state to resume.
- Baseline can be run and recorded.
- One or more node workspaces can be created and improved.
- Node worker evidence can be recorded in compact `node.json`.
- Orchestrator can decide continue, repair, branch, accept, reject, select, or
  block.
- Accepted node can be selected.
- Loop exits only when accepted/selected node exists and completion audit plus
  required validation/handoff evidence pass.
- Validator checks the minimal compact artifacts needed for that loop.
- Tests prove Stop hook blocks, resume works, and exit is allowed only after an
  accepted selected node.
- Implementation order prioritizes the smallest runnable research loop first.
  Docs, schemas, and advanced helpers should be updated only as needed to prove
  the loop works, then tightened afterward.

Simple v1 novelty enforcement stays in scope for modes that require it:

- Scientist/researcher require late-stage novelty refresh before final
  acceptance.
- Orchestrator may perform and record the novelty review directly in v1.
- Semantic Scholar evidence and review-style novelty scores are recorded in
  `journal.jsonl`, `node.json`, or `selection.json`.
- Validator checks required novelty fields for modes that require them.
- A more polished standalone novelty automation subsystem is v1.1.

V1.1/future scope includes sophisticated multi-GPU packing, full dependency
installer automation, full workspace symlink/bwrap automation, advanced adapter
extension workflows, advanced stale lease recovery, export polish, and
rate-limit integration if unavailable during v1 implementation.

### Current Implementation Plan

The implementation target is a smallest useful research loop, not the full
future framework. The v1 loop must be able to start or resume a research run,
keep Codex from ending through the Stop hook, execute audited commands, record
node evidence, select an accepted node, validate the phase gate, and then allow
normal Stop only after validation and handoff evidence exist.

Implemented in the current code path:

- Compact run state exists under `.ai-scientist/runs/<run-id>/` with
  `loop-state.json`, `config.json`, `journal.jsonl`, `selection.json`, and
  per-node `nodes/<node-id>/node.json`.
- `ai_scientist_state.py` owns run locking, state hashing, transition ids,
  journal events, Stop-hook decisions, compact node validation, and
  validation/handoff release evidence checks.
- `ai_scientist_state_cli.py` provides the v1 helper surface for research
  start/resume/checkpoint/set-next-action/complete/cancel, node transitions,
  subagent updates, workspace initialization, `resource run`,
  `selection finalize`, validation recording, and handoff recording.
- `validate_run.py --gate research_to_review` validates compact artifacts,
  accepted selected nodes, ranking coverage, unresolved node/subagent/resource
  blockers, baseline comparison, novelty evidence for scientist/researcher
  modes, and completion audit.
- Stop-hook events are logged to `journal.jsonl`; old standalone
  `stop-hook-events` are no longer the active v1 contract.
- Stale active schemas for removed v1 research artifacts have been quarantined
  under `schemas/deprecated/`.

Completed v1 closure work:

- Active JSON Schema documentation now mirrors the compact v1 contracts for
  journal, config, loop state, node evidence, and selection. Schemas remain
  documentation/test fixtures, not runtime dependencies.
- Focused tests cover coherent `research resume`, missing-cursor resume block,
  stale dead-PID lock recovery, workspace initialization, node workspace copy,
  `resource run` trial evidence, minimal GPU lease/release behavior,
  novelty-required validation failure, candidate not selectable,
  state/journal mismatch blocking, accepted selected-node validation, and
  Stop-hook release evidence.
- The full plugin test suite passes after schema/doc updates.
- Research-loop skill docs, artifact-contract docs, and README describe the
  compact v1 loop and the helper CLI instead of a Python Codex orchestrator or
  old multi-file research ledgers.

Explicitly deferred to v1.1/future:

- Sophisticated multi-GPU packing, advanced resource queue recovery, bwrap
  read-only data automation, full dependency install automation, export polish,
  advanced adapter workflows, and Codex rate-limit integration.

### Implementation Sequence

Build v1 in vertical slices. Each slice should leave the plugin in a runnable or
testable state.

1. Compact state and audit foundation.
   - Implement Python stdlib validators for `active-run.json`,
     `loop-state.json`, `config.json`, `journal.jsonl`, `selection.json`, and
     `node.json`.
   - Implement run locking, state hashing, transition ids, journal-first helper
     mutation, and mismatch/manual-recovery blocking.
   - Move Stop-hook logging from old separate event files into `journal.jsonl`.
   - Remove or quarantine stale active schemas for removed v1 artifacts.

2. Helper CLI and Stop-hook loop gate.
   - Add the agent-facing helper CLI for `research start`, `research resume`,
     `research checkpoint`, `research set-next-action`, node transitions,
     subagent status updates, `selection finalize`, `research complete`, and
     `research cancel`.
   - Make every helper response JSON and every mutation journaled.
   - Update Stop-hook decisions to read `active-run.json` and `loop-state.json`,
     block active research, reopen terminal-without-audit as `verifying`, and
     continue from recorded `orchestrator.next_action`.
   - Add tests for active block, validating block, cancellation allow, and
     accepted-selected completion allow.

3. Minimal workspace, baseline, and command execution.
   - Implement copy-based baseline workspace and node workspace creation under
     `.ai-scientist/runs/<run-id>/`.
   - Freeze the minimal workspace/benchmark/dependency contract in `config.json`.
   - Implement `resource run` as the official command audit wrapper for both
     CPU and GPU commands; GPU lease is conditional.
   - Capture command spec hash, cwd/env, stdout/stderr, exit code, metrics refs,
     and raw-log-to-metrics provenance.

4. Node lifecycle and validation.
   - Implement `node.json` writer/validator for flat trials, evidence refs,
     split/leakage pass fields, result summary, mode deliverables, and worker
     recommendation.
   - Keep official node status in `loop-state.json`; mirror reviewed status into
     `node.json`.
   - Rewrite `validate_run.py --gate research_to_review` around compact
     artifacts and unresolved subagent/resource checks.
   - Add fixtures for accepted, candidate, rejected, buggy, and mismatched node
     status cases.

5. Resume and orchestration ergonomics.
   - Implement smooth `research resume`: coherent state continues from
     `orchestrator.next_action`; stale lock/resource cleanup happens only for
     narrow deterministic cases; ambiguous/corrupted state blocks with recovery
     options.
   - Ensure Stop-hook continuation messages name the next action without
     inventing strategy.
   - Add tests for stale lock takeover, coherent resume, ambiguous resume block,
     and journal/state mismatch block.

6. Selection and v1 exit.
   - Implement minimal `selection.json` finalization over accepted nodes.
   - Enforce accepted-selected node plus completion audit plus validation/handoff
     evidence before normal Stop is allowed.
   - Add simple v1 novelty evidence enforcement for scientist/researcher modes;
     orchestrator-recorded novelty review is acceptable in v1.
   - Add tests for candidate-not-selectable, accepted-selected completion, missing
     novelty evidence in required modes, and manual selection rationale.

7. Documentation and skill alignment.
   - Update research-loop skill instructions, artifact contract, and README to
     describe the compact v1 loop.
   - Remove remaining references to Python-orchestrated nested Codex execution or
     old multi-file research contracts.
   - Keep advanced resource packing, full dependency install automation,
     advanced adapter workflows, export polish, and rate-limit integration as
     v1.1/future items until the core loop works.

## Writeup Stage Implementation Plan

### Dependency Check

The current repository dependency surface is not sufficient for the requested final-paper writeup:

- `pyproject.toml` and `uv.lock` currently declare only `pytest`.
- The local conda `base` environment has `matplotlib`, `numpy`, `seaborn`, and `Pillow`, but the plugin cannot rely on conda `base` for target runs.
- No TeX/PDF tool is currently available on PATH: `pdflatex`, `bibtex`, `latexmk`, `tectonic`, `pandoc`, `xelatex`, and `lualatex` are missing.

Therefore v1 writeup should declare plotting dependencies and fail fast on missing Python or TeX dependencies. If any required dependency is missing, the helper must stop immediately, report the exact missing package or executable, and ask the user to install it. It must not auto-install dependencies, switch Python environments, use fallback libraries, or silently downgrade a positive launch writeup to Markdown-only.

### Goal

Implement writeup as a Codex-native, Stop-hook-enforced phase after review. The current Codex session owns the writing loop. Python helpers only gather evidence, manage state, generate deterministic fallback figures, validate report manifests, compile LaTeX, and record audit/handoff events.

The positive writeup output must include:

- `.ai-scientist/runs/<run-id>/writeup/report.md`
- `.ai-scientist/runs/<run-id>/writeup/latex/template.tex`
- `.ai-scientist/runs/<run-id>/writeup/report.pdf`
- At least one final-paper figure backed by validated run artifacts.
- A manifest linking all claims, figures, metrics, limitations, and disclosure text to evidence artifacts.

Negative, rejected, or verifier-blocked runs may produce a summary, but they must not claim launch readiness.

### Implementation Changes

Add plugin-owned writeup helpers:

- `plugins/ai-scientist/scripts/writeup_state.py`
- `writeup` subcommands in `plugins/ai-scientist/scripts/ai_scientist_state_cli.py`

Initial CLI surface:

```text
writeup doctor --run-id <run-id>
writeup start --run-id <run-id> [--page-limit N] [--require-pdf]
writeup resume --run-id <run-id> --prompt
writeup collect-figures --run-id <run-id>
writeup plot-start --run-id <run-id>
writeup plot-complete --run-id <run-id> [--path <payload.json>]
writeup record --run-id <run-id> --markdown <path> --latex <path>
writeup compile --run-id <run-id>
writeup audit-start --run-id <run-id>
writeup audit-complete --run-id <run-id>
writeup complete --run-id <run-id> --path <completion-audit.json>
writeup negative-complete --run-id <run-id> --reason <reason>
```

`writeup start` must require the existing `review_to_writeup` gate evidence:

- Passing `validate_run.py --gate review_to_writeup`.
- Approved `review_to_writeup` handoff.
- `review/structured-review.json`.
- Config, selection, selected-node evidence, baseline metrics, command logs, split integrity evidence, leakage evidence, review verdict, and verifier decision.

Writeup state lives in the existing `loop-state.json` model with `phase: "writeup"`, `active: true`, `stop_policy: "block_until_completion_audit"`, and `state.orchestrator.next_action`.

### Figure Contract

Writeup must include figures in the final paper. Prefer existing validated figures if node evidence records them; otherwise generate deterministic summary figures from compact validated artifacts.

Required figure artifacts:

```text
.ai-scientist/runs/<run-id>/writeup/figures/figure-manifest.json
.ai-scientist/runs/<run-id>/writeup/figures/generated/*.png
```

Each figure manifest entry must include:

- `figure_id`
- `path`
- `caption`
- `source_artifacts`
- `source_metrics`
- `appears_in_markdown`
- `appears_in_latex`
- `generated_by`

Default deterministic figures:

- Baseline metric vs selected-node metric.
- Ranked accepted-node metrics when multiple accepted nodes exist.
- Confirmation or ablation trial series when available.

Plot generation should use declared project dependencies:

- Add `matplotlib`, `numpy`, and `Pillow` to `pyproject.toml`.
- Refresh `uv.lock`.
- Do not require `seaborn` for v1 unless a later implementation truly needs it.

Generated plotting code must not hallucinate data. It may only plot values present in `selection.json`, selected `node.json`, trial records, baseline metrics, or explicitly referenced metric artifacts.

### LaTeX And PDF Contract

Add a plugin-owned minimal LaTeX template rather than importing or copying AI-Scientist-v2 assets at runtime. The template should support figures with:

```text
\graphicspath{{../figures/generated/}{../figures/source/}}
```

`writeup compile` should:

- Require `pdflatex` and `bibtex`.
- Run the normal sequence: `pdflatex`, `bibtex`, `pdflatex`, `pdflatex`.
- Record stdout, stderr, exit codes, and generated PDF path in `writeup/logs/compile-*.json`.
- Fail fast if the TeX toolchain is unavailable, with a user-facing blocker that names the missing executable and asks the user to install it before continuing.

Because this machine currently lacks TeX tools, tests should use fake `pdflatex` and `bibtex` binaries for deterministic coverage.

### Validation And Stop Hook

Extend Stop-hook messaging for active writeup runs to report `state.orchestrator.next_action` just like research.

Extend `validate_run.py --gate launch` so positive launch requires:

- `verifier-decision.json` with `decision: "go"` and `blockers: []`.
- `writeup/manifest.json`.
- Existing Markdown, LaTeX, and PDF artifacts.
- At least one final figure referenced by both the report manifest and LaTeX.
- Explicit AI Scientist disclosure.
- Strictness mode, selected node, benchmark/split, baseline comparison, limitations, failed attempts, and known validity threats.
- Structured review and verifier evidence refs.

If the verifier is missing, `no_go`, or has blockers, writeup can complete only through `negative-complete`, and launch validation must fail.

### Test Plan

Add focused tests for:

- `writeup doctor` reports missing TeX and declared plotting dependency status.
- `writeup start` refuses missing `review_to_writeup` validation or handoff.
- `writeup resume` returns a prompt with evidence context and next action.
- `collect-figures` creates a figure manifest and deterministic metric plot.
- Launch validator rejects missing figures, stale figure refs, missing disclosure, missing PDF, and `no_go` verifier decisions.
- Stop hook blocks active writeup and allows terminal writeup only after completion audit plus launch validation/handoff evidence.
- Runtime dependency test confirms writeup code does not import, shell out to, wrap, or require AI-Scientist-v2.

Minimum verification commands:

```bash
python3 -m json.tool plugins/ai-scientist/.codex-plugin/plugin.json >/dev/null
python3 -m json.tool plugins/ai-scientist/hooks.json >/dev/null
python3 -m unittest discover -s plugins/ai-scientist/tests -p 'test_*.py'
```

