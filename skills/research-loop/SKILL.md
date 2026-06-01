---
name: research-loop
description: Execute a Codex-native, Stop-hook-enforced research loop from one selected idea, with auditable node workspaces, benchmark evidence, selection, and fail-closed phase gates.
---

# Research Loop

<Purpose>

Use this skill to turn one selected idea into one or more experiment nodes, run them against the target repository benchmark, and select a validated result. The current Codex session is the research orchestrator. Python helper commands persist state and audit evidence; they do not own the loop and must not spawn Codex.

</Purpose>

<Non_Negotiable_Rules>

- Mutate research state only through `ai-scientist` or the same deterministic helper APIs. Do not hand-edit `loop-state.json`, `active-run.json`, `selection.json`, or `node.json` during normal execution.
- Keep the project-local Stop hook installed and active. If Stop hook blocks, resume from the recorded cursor; do not bypass it.
- A research run consumes exactly one selected idea and one frozen target-venue bar. Ideation may produce multiple candidates, but each research run freezes one idea, strictness mode, target venue, and token budget threshold as input.
- Use copy-based per-node workspaces under `.ai-scientist/runs/<run-id>/nodes/<node-id>/workspace/`. Do not use git worktrees in v1.
- Do not mutate source files outside `.ai-scientist/` as part of the research loop. All experiment code changes happen in node workspaces.
- Official baseline, benchmark, and final-validation commands go through `resource run` so command specs, stdout/stderr, metrics, cwd, env, and resource events are auditable.
- No mode permits leakage, split manipulation, train/test contamination, deceptive scoring, hidden cherry-picking, or unlogged benchmark changes.
- In non-yolo dependency mode, do not request or install mid-loop dependencies. Work with the frozen environment or reject the node.
- Do not complete research while any node, subagent, or blocking resource remains unresolved.
- Every node critic must use the frozen critic runtime from `config.json`: `gpt-5.5` with `reasoning_effort: xhigh` unless the run config explicitly changes it. Record parent-side spawn metadata before completing the critic.
- The orchestrator does not repair scientific node evidence itself. `REVISE`, `buggy`, and `repairing` require worker-owned continuation until the node is accepted, rejected, invalid, or blocked by a real environment/resource/reproducibility/user-decision blocker.

</Non_Negotiable_Rules>

<Source_Of_Truth_Artifacts>

## Source-Of-Truth Artifacts

All run state lives under `.ai-scientist/`:

- `.ai-scientist/active-run.json`: current run pointer used by the Stop hook.
- `.ai-scientist/runs/<run-id>/config.json`: frozen mode, selected idea snapshot, dependency plan, workspace plan, benchmark contract, resource config, seed policy, and selection thresholds.
- `.ai-scientist/runs/<run-id>/loop-state.json`: active cursor, baseline status, official node statuses, subagent ledger, resource ledger, and selected node.
- `.ai-scientist/runs/<run-id>/journal.jsonl`: append-only audit stream.
- `.ai-scientist/runs/<run-id>/findings.jsonl` and `findings.md`: run-local finding memory for positive, negative, optimization, bug, drift, exhaustion, and transferable lessons.
- `.ai-scientist/runs/<run-id>/selection.json`: final ranked selection.
- `.ai-scientist/runs/<run-id>/baseline-workspace/`: copied baseline source.
- `.ai-scientist/runs/<run-id>/nodes/<node-id>/workspace/`: mutable node workspace.
- `.ai-scientist/runs/<run-id>/nodes/<node-id>/node.json`: official node evidence.
- `.ai-scientist/runs/<run-id>/nodes/<node-id>/trials/<trial-id>/`: command logs, stdout, stderr, and command specs from `resource run`.
- `.ai-scientist/runs/<run-id>/logs/pending/subagents/<subagent-id>.json`: assigned worker result payload path.
- `.ai-scientist/runs/<run-id>/logs/pending/nodes/<node-id>.json`: assigned node evidence payload path.
- `.ai-scientist/runs/<run-id>/logs/pending/critics/<critic-id>.json`: assigned critic result payload path.
- `.ai-scientist/runs/<run-id>/logs/pending/repairs/<repair-id>.json`: assigned worker repair result payload path.
- `.ai-scientist/runs/<run-id>/logs/critics/<critic-id>.json`: completed critic record, including required runtime and parent-side spawn metadata.
- `.ai-scientist/runs/<run-id>/logs/repairs/<repair-id>.json`: completed or continued worker repair record.

`run-status.json` may exist only as derived user-facing output. It is not source of truth.

</Source_Of_Truth_Artifacts>

<Python_Launcher>

## Python Launcher

Command examples use `python` for portability. Treat it as a placeholder for the
Python launcher provided by the target environment: `uv run python`,
`conda run -n <env> python`, `micromamba run -n <env> python`, `python3`, or an
absolute interpreter path.

Use the launcher that can import and run the plugin helper scripts and, for
official benchmark commands, can access the target project's runtime. Do not
assume this development server's `micromamba` layout exists on other machines.
If the target repo has `.venv`, `uv.lock`, `pyproject.toml`,
`environment.yml`, `conda` metadata, or project docs, follow that environment.
Do not silently switch Python launchers mid-run; if the right environment is
unclear and the command is required, ask or fail fast with a clear blocker.

</Python_Launcher>

<Strictness_Modes>

## Strictness Modes

Default mode is `scientist`. Mode is frozen once the research run starts.

### `scientist`: 
- maintain a publishable claim, strict split/leakage discipline, fixed split seeds, fair model seeds, multi-seed final confirmation, ablations, novelty evidence, and causal link between method and result. Valid accepted outcomes are `hypothesis_supported`, `hypothesis_failed_with_evidence`, or `rescue_finding_with_failed_hypothesis`.
### `researcher`:
- maintain a research hypothesis with meaningful ablation and reproducibility; limited pragmatic tuning is allowed after hypothesis validation. Valid accepted outcomes are the same research outcome types as scientist, with a lighter reproducibility bar.
### `balanced`: 
- beat baseline credibly, preserve split integrity, include lightweight ablation or sensitivity evidence.
### `engineer`: 
- optimize for strong credible score with transparent tuning. fixed benchmark/split, leakage checks, and selection/tuning logs are required; novelty is optional. A merely positive baseline delta is not enough if cheap bounded improvements remain.
### `hacker`:
- optimize for strong credible score with transparent tuning. fixed benchmark/split, leakage checks, and selection/tuning logs are required; novelty is optional. A merely positive baseline delta is not enough if cheap bounded improvements remain.
### `custom`:
- _tbd_ 

Fixed split seeds apply to all modes. Scientist/researcher should also avoid abusing training seeds; builder/engineer may use pragmatic tuning if it is logged and does not manipulate the split.

</Strictness_Modes>

<Dependency_And_Environment_Policy>

## Dependency And Environment Policy

Before research starts, inspect imports, benchmark entrypoint, likely experiment architecture, and missing dependencies. Store the frozen dependency plan in `config.json`.

Dependency statuses must be explicit:

- `approved`
- `rejected`
- `not_needed`

Default mode is frozen dependencies. In frozen mode, agents must not ask for mid-loop dependency installs; prompts should tell workers to work with the available environment. In yolo mode, agents may install packages, but every install must be local to the run when possible and logged.

If environment/package corruption, missing core dependencies, CUDA/toolchain changes, or reproducibility-affecting changes are needed, stop and escalate to the user.

</Dependency_And_Environment_Policy>

<Startup>

## Startup

Install/check the Stop hook:

```bash
ai-scientist hooks install --project-root <target-repo>
```

Start a research run:

```bash
ai-scientist \
  --target-repo <target-repo> \
  research start \
  --run-id <run-id> \
  --strictness-mode scientist \
  --selected-idea-id <accepted-idea-id-or-rank> \
  --target-venue-preset aaai_ijcai \
  --target-venue-name AAAI \
  --target-venue-notes '<optional venue bar notes>' \
  --token-budget-percent 95 \
  --json '<frozen config/state payload>'
```

Prefer `--path <payload.json>` over inline `--json` for nontrivial payloads. The payload should include any known selected idea snapshot, benchmark command, dependency plan, workspace plan, seed policy, and initial state overrides. If the selected idea came from ideation, copy the selected canonical idea, ranking rationale, mode config snapshot, and evidence summary into this research run. Later ideation edits must not mutate this research input.

Research subagent concurrency is frozen at run start under `research.concurrency.max_subagents`. Resolution order is `research start --max-subagents <n>`, then payload/project override, then Codex `~/.codex/config.toml` `[agents].max_threads`, then `6`. The frozen config records the source. The resume cursor reports `available_subagent_slots`, `suggested_subagent_count`, and `subagent_concurrency_source`; use that count as the upper bound for parallel node workers.

Research startup fails fast unless `--strictness-mode`, `--selected-idea-id`, `--target-venue-preset`, and `--token-budget-percent` are present and valid. The frozen target venue is stored under `config.json.research.target_venue`; pass it into all worker, critic, revision, and selection prompts. `workshop` and `domain_conference` can accept more incremental but honest work. `aaai_ijcai` and `top_ml` require stronger novelty, clearer mechanism, convincing ablations, reproducibility, and low tolerance for tuning-only improvements.

Research usage-cap policy is frozen at run start under `research.usage_cap`: enabled, warn before the user-specified cap, block new LLM/subagent work at `research.usage_cap.block_new_work_at_percent`, poll every 600 seconds, and read `limit_id: codex` from `codex app-server account/rateLimits/read`. `research start` performs the first usage check. `research resume` refreshes stale usage, includes `usage_cap` in `next_action_details`, and returns `next_action: blocked_on_usage_limit` when capped. Before starting strategist/node/critic/revision subagent work, run through the helper entrypoints so the cap is enforced and logged. Use `research usage-check --run-id <run-id> --force` for an explicit refresh. `research start --no-limit-host-cap` or `research.usage_cap.no_limit_host_cap: true` logs usage warnings without blocking; default mode fails closed if usage cannot be read.

Scientist/researcher runs must freeze a `research_contract` in `config.json` before work begins. It must state the primary hypothesis, success criteria, failure criteria, allowed rescue scope, kill criteria, metrics that matter, and non-negotiable comparisons. This contract is the standard critics use to distinguish supported hypotheses, solid negative results, and rescues from quiet claim narrowing.

</Startup>

<Resume_Cursor>

Resume:

```bash
ai-scientist \
  --target-repo <target-repo> \
  research resume --run-id <run-id>
```

The resume response returns `next_action` and `next_action_details`. Follow that cursor. To update cursor after completing a step:

```bash
ai-scientist \
  --target-repo <target-repo> \
  research set-next-action --run-id <run-id> --lane <lane> --reason "<reason>"
```

Use lanes such as `setup`, `dependency_plan`, `workspace`, `baseline`, `node_work`, `node_validation`, `selection`, `completion_audit`, or `handoff`.

</Resume_Cursor>

<Workspace_Setup>

## Workspace Setup

Initialize the baseline workspace:

```bash
ai-scientist \
  --target-repo <target-repo> \
  workspace init --run-id <run-id> --source <target-repo>
```

This creates `.ai-scientist/runs/<run-id>/baseline-workspace/`. Essential configs are copied. Caches/generated outputs are ignored. Large-but-needed resources may be linked read-only according to the frozen workspace plan. If a required large data file cannot be safely copied/linked, fail fast with logs.

</Workspace_Setup>

<Node_Workspace_Creation>

Create a node workspace:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node create-workspace --run-id <run-id> --node-id node-001 --reason "start first approach"
```

Each node is one research direction. Hyperparameter sweeps, ablations, and sane local debugging for that direction happen inside the same node. Child/new nodes are for meaningfully different approaches or follow-up ideas, not for minor parameter variants.

</Node_Workspace_Creation>

<Benchmark_Contract>

## Benchmark Contract

The benchmark command is the official entrypoint contract for baseline and node comparison. It should be flexible enough for node workspaces to tune internal implementation details, but comparable enough that baseline and node scores share the same metric semantics.

Official commands must be run with `resource run`:

```bash
ai-scientist \
  --target-repo <target-repo> \
  resource run \
  --run-id <run-id> \
  --node-id node-001 \
  --trial-id trial-001 \
  --purpose benchmark \
  --cwd <node-workspace> \
  --metrics-json '{"score": 0.73}' \
  --benchmark-contract-version v1 \
  --gpu \
  -- <benchmark command and args>
```

Use `--gpu` only when the command actually needs GPU. V1 helper uses a minimal GPU lease and sets `CUDA_VISIBLE_DEVICES=0`. CPU-only official commands should still use `resource run` without `--gpu` for audit evidence.

Worker/local smoke tests may run directly inside a node workspace, but official baseline, benchmark, final validation, and selected-node evidence must use `resource run`.

</Benchmark_Contract>

<Node_Lifecycle>

## Node Lifecycle

Official node statuses:

- `planning`: architecture plan or branch approach is being created; implementation has not started.
- `planned`: architecture/workspace/approach exists but implementation has not started.
- `implementing`: code changes are being made; a half-finished node stays here and is not scientific failure evidence.
- `running`: benchmark or substantial experiment is running.
- `buggy`: command failed or behavior is broken; failure signature required.
- `repairing`: active repair/debugging.
- `candidate`: meaningful progress, partial success, or promising evidence that still needs independent validation.
- `validating`: split/leakage/final checks are running.
- `accepted`: critic-approved final evidence that is eligible for selection.
- `invalid`: critic-confirmed evidence/trust failure.
- `rejected`: critic-confirmed not-worth-continuing or not-selected node; reason required.

Record transitions:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node transition \
  --run-id <run-id> \
  --node-id node-001 \
  --status implementing \
  --reason "implement selected idea"
```

For node work, first transition the node into an active status and capture the returned `result_path`. Give that path to the worker. The worker writes JSON only to that file. A later `node transition` with no `--json` reads the assigned path by default.

```bash
ai-scientist \
  --target-repo <target-repo> \
  node transition \
  --run-id <run-id> \
  --node-id node-001 \
  --status implementing \
  --reason "worker owns node-001 implementation"
```

After the worker writes the node evidence payload to `result_path`:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node transition \
  --run-id <run-id> \
  --node-id node-001 \
  --status candidate \
  --reason "meaningful progress ready for independent critic"
```

Use `--json` or `--path` only as explicit overrides. `planning`, `planned`, `implementing`, `candidate`, `buggy`, and `repairing` may branch into more work. Terminal states do not trigger further branching.

Accepted node evidence must include:

- `benchmark_contract_version`
- `metrics` or `metrics_ref`
- `split_integrity.pass: true`
- `leakage_check.pass: true`
- `result_summary`
- `mode_deliverables`
- at least one trial record
- for scientist/researcher, novelty evidence when required by validator/config

Accepted node outcome evidence must also include:

- `outcome_type`: `hypothesis_supported`, `hypothesis_failed_with_evidence`, `rescue_finding_with_failed_hypothesis`, or `practical_improvement`
- for scientist/researcher: `current_claim`, `claim_equivalence`, `contract_evidence`, and `paper_worthiness`
- for `hypothesis_failed_with_evidence`: `fundamental_failure_reason` and `contract_evidence.failure_criteria_met: true`
- for builder/engineer: `strong_model_evidence` with confirmation trials, tuning plateau or exhaustion, and `cheap_improvements_remaining: false`

Rejected/invalid nodes need a clear rejection reason or failure signature. A weak score from an incomplete implementation is not a rejection reason and must remain `implementing`, `buggy`, or `repairing`.

</Node_Lifecycle>

<Plan_First_Incremental_Implementation>

### Plan-First Incremental Implementation

For large codebase changes, do not hand a worker the whole research plan as one oversized implementation prompt. Start with an architecture plan, then implement bounded steps.

```bash
ai-scientist \
  --target-repo <target-repo> \
  node plan-start --run-id <run-id> --node-id node-001 --json '{"objective":"<node objective>"}'
```

The returned prompt asks the worker to write only an architecture plan to `result_path`. Complete it after the worker writes `architecture_plan.implementation_steps`:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node plan-complete --run-id <run-id> --plan-id <plan-id>
```

Then start one bounded implementation step at a time:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node step-start --run-id <run-id> --node-id node-001
```

After the worker writes the step payload, complete the step:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node step-complete --run-id <run-id> --step-id <step-id>
```

If `done_definition_met` is false, the helper keeps the node `implementing` and sets `orchestrator.next_action = node_implementation_step`; spawn/continue a worker with the next step instead of judging the node. Only when `done_definition_met: true`, `recommended_status: candidate`, and complete node evidence are present should the node move to `candidate` for critics.

If a worker identifies a meaningfully different approach before the current node is complete, do not directly branch. First finish reasonable same-node work or document why it is not applicable: debugging, hyperparameter tuning, layer/model variants within the same mechanism, expected ablations, and sanity checks. Then use the revision workflow below so a critic can decide whether the alternative is viable and paper-worthy under the frozen target venue bar.

</Plan_First_Incremental_Implementation>

<Findings_Memory>

## Findings Memory

Record useful findings whenever a node teaches something, even when the node fails or underperforms:

```bash
ai-scientist \
  --target-repo <target-repo> \
  finding record --run-id <run-id> --node-id node-001 --kind optimization --summary "dropout helped; wide layers failed" --transferable
```

Allowed kinds are `positive`, `negative`, `optimization`, `bug`, `drift`, `exhaustion`, and `transferable`. The helper writes both `findings.jsonl` and `findings.md`. Node planning prompts, implementation-step prompts, revision brainstorming prompts, and revision critic prompts include relevant findings so workers avoid known failed fixes and reuse transferable techniques.

</Findings_Memory>

<Revision_And_Branching>

## Revision And Branching

Revision means a different approach and therefore creates a new node only after critic approval. Repair, debugging, tuning, layer variants within the same mechanism, ablations, and local optimization remain same-node work.

Start revision brainstorming only after optimization proof or non-applicable proof exists:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node revision-start --run-id <run-id> --node-id node-001
```

If the node has not recorded `optimization_attempts` or `optimization_not_applicable_reason`, `revision-start` fails fast. The returned prompt requires optimization attempts/metrics, useful findings, why the current direction is insufficient, and one to three alternatives with venue fit, anti-metric-hacking, and anti-claim-drift rationale.

After the worker writes the revision payload:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node revision-complete --run-id <run-id> --revision-id <revision-id>
```

Then start and complete a revision critic:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node revision-critic-start --run-id <run-id> --revision-id <revision-id>

ai-scientist \
  --target-repo <target-repo> \
  node revision-critic-complete --run-id <run-id> --critic-id <critic-id>
```

Revision critic verdicts:

- `CONTINUE_NODE`: block branch creation; continue same-direction implementation/tuning/ablation work.
- `BRANCH`: approve one to three alternatives for child nodes.
- `STOP_DRIFTED`: stop the lineage because continued branching is below the venue bar, metric hacking, or claim drift.
- `STOP_EXHAUSTED`: stop the lineage because the goal appears fundamentally unachievable under current evidence.

Only a `BRANCH` verdict allows child creation:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node branch --run-id <run-id> --from-node node-001 --node-id node-002 --revision-id <revision-id> --alternative-id alt-001
```

There is no fixed branch-depth limit. Deeper branching is allowed while critics still find the lineage viable and paper-worthy for the frozen venue bar. Stop lineages that are mostly incremental hacks, drifted claims, or exhausted under the current evidence.

</Revision_And_Branching>

<Node_Critics>

## Node Critics

Terminal node states are critic-gated. Direct `node transition --status accepted|invalid|rejected` is refused. The helper commands only prepare paths, validate JSON, persist state, and apply the critic verdict; the orchestrator still spawns the actual Codex critic subagent.

Start a critic after node evidence is in `candidate` or `validating`:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node critic-start --run-id <run-id> --node-id node-001
```

Scientist/researcher require two critic roles: `evidence_auditor` and `claim_critic`. Builder/engineer require `performance_auditor`. Use `--role <role>` when starting a specific role, otherwise the helper chooses the first missing required role.

`critic-start` returns `required_model`, `required_reasoning_effort`, `critic_role`, `rubric_snapshot`, `evidence_fingerprint`, `prompt`, and `result_path`. Spawn the critic with the returned runtime, then record parent-side spawn metadata:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node critic-spawn-record \
  --run-id <run-id> \
  --critic-id <critic-id> \
  --agent-id <agent-id> \
  --model gpt-5.5 \
  --reasoning-effort xhigh
```

Give the returned `prompt` and `result_path` to the fresh critic. The critic writes JSON only to `result_path`:

```json
{
  "verdict": "ACCEPT",
  "mode": "engineer",
  "critic_role": "performance_auditor",
  "score": 84,
  "rationale": "Final evidence is complete and reproducible.",
  "acceptance_checks": {
    "metric_contract_valid": true,
    "split_integrity_valid": true,
    "leakage_check_valid": true,
    "all_trials_accounted_for": true,
    "claim_matches_evidence": true,
    "mode_specific_bar_met": true,
    "cheap_improvements_remaining": false
  },
  "missed_opportunity_scan": {
    "searched": ["hyperparameters", "data cleaning", "architecture", "training schedule", "evaluation bugs"],
    "actionable_improvements": [],
    "why_remaining_ideas_are_not_worth_running": "No cheap bounded improvement remains under the frozen budget."
  },
  "strengths": ["clean split evidence"],
  "weaknesses": ["limited ablations"],
  "required_revisions": [],
  "risk_flags": []
}
```

Complete the critic:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node critic-complete --run-id <run-id> --critic-id <critic-id>
```

Verdict mapping:

- `ACCEPT` -> `accepted`
- `REVISE` -> `repairing` plus a worker repair assignment
- `INVALID` -> `invalid`
- `REJECT` -> `rejected`

Small progress or partial success must be `REVISE`/`repairing`, not `ACCEPT`. Critic completion fails if node evidence changed after `critic-start`, required runtime metadata is missing/wrong, required acceptance checks are missing, `cheap_improvements_remaining` is true, or actionable improvements are listed.

In scientist/researcher mode, `claim_critic` must explicitly answer whether the original hypothesis is supported, failed with evidence, or an approved rescue. A narrowed but useful claim is not a success unless the selected `outcome_type` says it is a rescue or failed-hypothesis result. `hypothesis_failed_with_evidence` is valid only for fundamental failure under the frozen contract; routine optimization failure, incomplete implementation, or evidence that a different approach may work must be `REVISE` or a branched node.

</Node_Critics>

<Bug_And_Revision_Repair>

## Bug And Revision Repair

Let node workers debug themselves when practical; waiting for the orchestrator on every error burns tokens. There is no hard repair-attempt limit. The orchestrator should intervene when the same failure repeats without new information, when the worker requests a decision, or when an environment/reproducibility blocker appears.

Buggy node records should include:

- failure signature
- command
- exit code
- error path/log path
- retryability
- next action

Do not complete research with any node in `planning`, `buggy`, `repairing`, `candidate`, `planned`, `implementing`, `running`, or `validating`.

When a critic returns `REVISE`, the helper creates a repair assignment and sets `orchestrator.next_action = node_repair`. Spawn or continue a worker for that node and pass the repair `result_path`, required revisions, critic ref, failed command/trial logs, and node workspace path. The worker edits only the node workspace unless explicitly authorized.

Repair payload:

```json
{
  "repair_id": "repair-node-001-001",
  "node_id": "node-001",
  "files_changed": [],
  "commands_run": [],
  "fixed_revisions": [],
  "remaining_required_revisions": [],
  "remaining_risks": [],
  "recommended_status": "candidate"
}
```

Complete repair:

```bash
ai-scientist \
  --target-repo <target-repo> \
  node repair-complete --run-id <run-id> --repair-id <repair-id>
```

If required revisions remain and no real blocker is recorded, the helper creates a follow-up repair assignment and keeps the node in `repairing`. `node transition --status candidate` is refused until the open repair has a completed worker payload. After repair, run official evidence through `resource run`, transition back to `candidate`, and start a fresh xhigh critic.

</Bug_And_Revision_Repair>

<Subagents>

## Subagents

Use native Codex subagents only for bounded, auditable work. Subagents are workers, not loop owners. The main orchestrator owns state transitions and final decisions.

Good subagent tasks:

- repo/benchmark mapping
- setup/workspace planning
- implementing one node in one node workspace
- debugging one node
- split/leakage validation
- scientific critique
- final selection review

Parallelism is allowed across different nodes up to frozen `research.concurrency.max_subagents`. Do not run multiple workers mutating the same node workspace at once. If GPU is needed, queue GPU-backed work through `resource run` and avoid oversubscribing VRAM.

Usage-cap enforcement blocks `subagent update --status planned|running`, `node critic-start`, revision critic work, and active node transitions (`planning`, `implementing`, `running`, `validating`, `repairing`) at or above the frozen `block_new_work_at_percent` Codex usage threshold. Benchmark/resource commands are not blocked, so already-started evidence collection can finish and be recorded. If a final selected accepted node already satisfies the configured good-enough threshold, completion and handoff work may continue; the cap is never a substitute for accepted critic-approved evidence.

When spawning a worker, include:

- exact node id and workspace path
- allowed write scope
- benchmark command/contract
- strictness mode
- selected idea summary
- dependency policy
- instruction that the worker is not alone in the codebase, must not revert others' edits, and must adapt to existing changes
- required final output: files changed, commands run, metrics, failure signature if failed, and recommended node status

Record subagent status. The first update returns `result_path`; give that path to the worker and require JSON-only output there:

```bash
ai-scientist \
  --target-repo <target-repo> \
  subagent update \
  --run-id <run-id> \
  --subagent-id worker-node-001 \
  --node-id node-001 \
  --status running
```

After the worker writes its result payload to `result_path`:

```bash
ai-scientist \
  --target-repo <target-repo> \
  subagent update \
  --run-id <run-id> \
  --subagent-id worker-node-001 \
  --status completed_unintegrated
```

Use `--json` or `--path` only as explicit overrides.

Allowed subagent statuses:

- `planned`
- `running`
- `blocked_on_resource`
- `completed_unintegrated`
- `failed_unreviewed`
- `integrated`
- `rejected_with_reason`
- `abandoned_with_reason`

Before completion, every subagent must be terminal: `integrated`, `rejected_with_reason`, or `abandoned_with_reason`.

</Subagents>

<Selection>

## Selection

After one or more accepted nodes exist, run final selection manually as orchestrator or spawn a short-lived selection/review agent. Scores help, but the orchestrator may make the final judgment by reading node evidence.

Selection payload:

```json
{
  "selected_node": "node-001",
  "outcome_type": "practical_improvement",
  "metric_key": "score",
  "metric_direction": "maximize",
  "baseline_metric": 0.5,
  "selected_metric": 0.73,
  "ranked_nodes": [
    {
      "node_id": "node-001",
      "score": 82,
      "rationale": "Best validated result with clean split and acceptable ablation"
    }
  ],
  "rationale": "Why this node is selected",
  "manual_override": null
}
```

Record selection:

```bash
ai-scientist \
  --target-repo <target-repo> \
  selection finalize --run-id <run-id> --json '<selection JSON>'
```

Prefer `--path <selection.json>` over inline `--json` for selection payloads.

`selection finalize` requires the selected node to be accepted in `loop-state.json` with a fresh `ACCEPT` critic verdict, and all accepted nodes to appear in `ranked_nodes`.

For scientist/researcher, selecting `hypothesis_failed_with_evidence` is a valid successful research-loop ending only when the frozen contract failure criteria are satisfied, the node has a `fundamental_failure_reason`, `contract_evidence.fundamental_failure_not_implementation_failure: true`, `alternative_approaches_considered`, and the `claim_critic` marks `fundamental_failure: true`. Routine failed tuning, inconclusive tests, incomplete code, or a weak implementation do not qualify; branch a new node when another approach may work.

</Selection>

<Completion_And_Handoff>

## Completion And Handoff

Before completion:

1. Baseline is complete.
2. All subagents are terminal.
3. Blocking resources are resolved.
4. Every node is terminal: `accepted`, `invalid`, or `rejected`; no `planning`/`implementing`/partial node may be treated as final evidence.
5. Every terminal node has a fresh critic ref matching its terminal verdict.
6. No critic is pending.
7. Selected node exists and is `accepted` with a fresh `ACCEPT` critic verdict.
8. `selection.json` is final and matches `loop-state.json`.
9. Node evidence satisfies `ai-scientist validate run <target-repo> --gate research_to_review`.

Complete research with a passing audit:

```bash
ai-scientist \
  --target-repo <target-repo> \
  research complete --run-id <run-id> --path .ai-scientist/runs/<run-id>/logs/completion-audit.json
```

Then run validator:

```bash
ai-scientist validate run \
  <target-repo> --gate research_to_review --run-id <run-id>
```

Record validation:

```bash
ai-scientist \
  --target-repo <target-repo> \
  validation record --run-id <run-id> --gate research_to_review --exit-code 0 --command "ai-scientist validate run <target-repo> --gate research_to_review --run-id <run-id>"
```

Record approved handoff:

```bash
ai-scientist \
  --target-repo <target-repo> \
  handoff record --run-id <run-id> --gate research_to_review --exit-code 0 --approved --reason "research evidence ready for review"
```

Stop hook should allow ending only after completion, validation record, and approved handoff record exist.

</Completion_And_Handoff>

<Cancellation>

Cancel only when explicitly requested or impossible to continue:

```bash
ai-scientist \
  --target-repo <target-repo> \
  research cancel --run-id <run-id> --reason "<reason>"
```

</Cancellation>

<Final_Response>

## Final Response

Report:

- run id and strictness mode
- selected idea id/input summary
- baseline score and selected node score
- selected node id and why it was selected
- split/leakage status
- ablation/reproducibility evidence appropriate to mode
- validator command and result
- handoff status
- artifact paths for `config.json`, `loop-state.json`, `selection.json`, selected `node.json`, and important trial logs

Do not claim review/writeup has started unless the user explicitly asks for the next phase.

</Final_Response>
