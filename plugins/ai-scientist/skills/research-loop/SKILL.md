---
name: research-loop
description: Execute a Codex-native, Stop-hook-enforced research loop from one selected idea, with auditable node workspaces, benchmark evidence, selection, and fail-closed phase gates.
---

# Research Loop

Use this skill to turn one selected idea into one or more experiment nodes, run them against the target repository benchmark, and select a validated result. The current Codex session is the research orchestrator. Python helper commands persist state and audit evidence; they do not own the loop and must not spawn Codex.

## Non-Negotiable Rules

1. Do not run a Python orchestrator, nested `codex exec`, or any process that owns the research loop.
2. Mutate research state only through `plugins/ai-scientist/scripts/ai_scientist_state_cli.py` or the same deterministic helper APIs. Do not hand-edit `loop-state.json`, `active-run.json`, `selection.json`, or `node.json` during normal execution.
3. Keep the project-local Stop hook installed and active. If Stop hook blocks, resume from the recorded cursor; do not bypass it.
4. A research run consumes exactly one selected idea. Ideation may produce multiple candidates, but each research run freezes one idea as input.
5. Use copy-based per-node workspaces under `.ai-scientist/runs/<run-id>/nodes/<node-id>/workspace/`. Do not use git worktrees in v1.
6. Do not mutate source files outside `.ai-scientist/` as part of the research loop. All experiment code changes happen in node workspaces.
7. Official baseline, benchmark, and final-validation commands go through `resource run` so command specs, stdout/stderr, metrics, cwd, env, and resource events are auditable.
8. No mode permits leakage, split manipulation, train/test contamination, deceptive scoring, hidden cherry-picking, or unlogged benchmark changes.
9. In non-yolo dependency mode, do not request or install mid-loop dependencies. Work with the frozen environment or reject the node.
10. Do not complete research while any node, subagent, or blocking resource remains unresolved.

## Source-Of-Truth Artifacts

All run state lives under `.ai-scientist/`:

- `.ai-scientist/active-run.json`: current run pointer used by the Stop hook.
- `.ai-scientist/runs/<run-id>/config.json`: frozen mode, selected idea snapshot, dependency plan, workspace plan, benchmark contract, resource config, seed policy, and selection thresholds.
- `.ai-scientist/runs/<run-id>/loop-state.json`: active cursor, baseline status, official node statuses, subagent ledger, resource ledger, and selected node.
- `.ai-scientist/runs/<run-id>/journal.jsonl`: append-only audit stream.
- `.ai-scientist/runs/<run-id>/selection.json`: final ranked selection.
- `.ai-scientist/runs/<run-id>/baseline-workspace/`: copied baseline source.
- `.ai-scientist/runs/<run-id>/nodes/<node-id>/workspace/`: mutable node workspace.
- `.ai-scientist/runs/<run-id>/nodes/<node-id>/node.json`: official node evidence.
- `.ai-scientist/runs/<run-id>/nodes/<node-id>/trials/<trial-id>/`: command logs, stdout, stderr, and command specs from `resource run`.
- `.ai-scientist/runs/<run-id>/logs/pending/subagents/<subagent-id>.json`: assigned worker result payload path.
- `.ai-scientist/runs/<run-id>/logs/pending/nodes/<node-id>.json`: assigned node evidence payload path.

`run-status.json` may exist only as derived user-facing output. It is not source of truth.

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

## Strictness Modes

Default mode is `scientist`. Mode is frozen once the research run starts.

- `scientist`: maintain a publishable claim, strict split/leakage discipline, fixed split seeds, fair model seeds, multi-seed final confirmation, ablations, novelty evidence, and causal link between method and result.
- `researcher`: maintain a research hypothesis with meaningful ablation and reproducibility; limited pragmatic tuning is allowed after hypothesis validation.
- `balanced`: beat baseline credibly, preserve split integrity, include lightweight ablation or sensitivity evidence.
- `builder`: optimize for practical held-out performance with transparent tuning and leakage checks; novelty is optional.
- `engineer`: optimize for strong credible score, fixed benchmark/split, leakage checks, and selection/tuning log; novelty is optional.

Fixed split seeds apply to all modes. Scientist/researcher should also avoid abusing training seeds; builder/engineer may use pragmatic tuning if it is logged and does not manipulate the split.

## Dependency And Environment Policy

Before research starts, inspect imports, benchmark entrypoint, likely experiment architecture, and missing dependencies. Store the frozen dependency plan in `config.json`.

Dependency statuses must be explicit:

- `approved`
- `rejected`
- `not_needed`

Default mode is frozen dependencies. In frozen mode, agents must not ask for mid-loop dependency installs; prompts should tell workers to work with the available environment. In yolo mode, agents may install packages, but every install must be local to the run when possible and logged.

If environment/package corruption, missing core dependencies, CUDA/toolchain changes, or reproducibility-affecting changes are needed, stop and escalate to the user.

## Startup

Install/check the Stop hook:

```bash
python plugins/ai-scientist/scripts/install_codex_hooks.py --project-root <target-repo>
```

Start a research run:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  research start \
  --run-id <run-id> \
  --strictness-mode scientist \
  --json '<frozen config/state payload>'
```

Prefer `--path <payload.json>` over inline `--json` for nontrivial payloads. The payload should include any known selected idea snapshot, benchmark command, dependency plan, workspace plan, seed policy, and initial state overrides. If the selected idea came from ideation, copy the selected canonical idea, ranking rationale, mode config snapshot, and evidence summary into this research run. Later ideation edits must not mutate this research input.

Research subagent concurrency is frozen at run start under `research.concurrency.max_subagents`. Resolution order is `research start --max-subagents <n>`, then payload/project override, then Codex `~/.codex/config.toml` `[agents].max_threads`, then `6`. The frozen config records the source. The resume cursor reports `available_subagent_slots`, `suggested_subagent_count`, and `subagent_concurrency_source`; use that count as the upper bound for parallel node workers.

Resume:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  research resume --run-id <run-id>
```

The resume response returns `next_action` and `next_action_details`. Follow that cursor. To update cursor after completing a step:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  research set-next-action --run-id <run-id> --lane <lane> --reason "<reason>"
```

Use lanes such as `setup`, `dependency_plan`, `workspace`, `baseline`, `node_work`, `node_validation`, `selection`, `completion_audit`, or `handoff`.

## Workspace Setup

Initialize the baseline workspace:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  workspace init --run-id <run-id> --source <target-repo>
```

This creates `.ai-scientist/runs/<run-id>/baseline-workspace/`. Essential configs are copied. Caches/generated outputs are ignored. Large-but-needed resources may be linked read-only according to the frozen workspace plan. If a required large data file cannot be safely copied/linked, fail fast with logs.

Create a node workspace:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  node create-workspace --run-id <run-id> --node-id node-001 --reason "start first approach"
```

Each node is one research direction. Hyperparameter sweeps, ablations, and sane local debugging for that direction happen inside the same node. Child/new nodes are for meaningfully different approaches or follow-up ideas, not for minor parameter variants.

## Benchmark Contract

The benchmark command is the official entrypoint contract for baseline and node comparison. It should be flexible enough for node workspaces to tune internal implementation details, but comparable enough that baseline and node scores share the same metric semantics.

Official commands must be run with `resource run`:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
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

## Node Lifecycle

Official node statuses:

- `planned`: workspace/approach exists but implementation has not started.
- `implementing`: code changes are being made.
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
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  node transition \
  --run-id <run-id> \
  --node-id node-001 \
  --status implementing \
  --reason "implement selected idea"
```

For node work, first transition the node into an active status and capture the returned `result_path`. Give that path to the worker. The worker writes JSON only to that file. A later `node transition` with no `--json` reads the assigned path by default.

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  node transition \
  --run-id <run-id> \
  --node-id node-001 \
  --status implementing \
  --reason "worker owns node-001 implementation"
```

After the worker writes the node evidence payload to `result_path`:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  node transition \
  --run-id <run-id> \
  --node-id node-001 \
  --status candidate \
  --reason "meaningful progress ready for independent critic"
```

Use `--json` or `--path` only as explicit overrides. `candidate`, `buggy`, and `repairing` may branch into more work. Terminal states do not trigger further branching.

Accepted node evidence must include:

- `benchmark_contract_version`
- `metrics` or `metrics_ref`
- `split_integrity.pass: true`
- `leakage_check.pass: true`
- `result_summary`
- `mode_deliverables`
- at least one trial record
- for scientist/researcher, novelty evidence when required by validator/config

Rejected/invalid nodes need a clear rejection reason or failure signature.

## Node Critics

Terminal node states are critic-gated. Direct `node transition --status accepted|invalid|rejected` is refused. The helper commands only prepare paths, validate JSON, persist state, and apply the critic verdict; the orchestrator still spawns the actual Codex critic subagent.

Start a critic after node evidence is in `candidate` or `validating`:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  node critic-start --run-id <run-id> --node-id node-001
```

Give the returned `prompt` and `result_path` to a fresh critic. The critic writes JSON only to `result_path`:

```json
{
  "verdict": "ACCEPT",
  "score": 84,
  "rationale": "Final evidence is complete and reproducible.",
  "strengths": ["clean split evidence"],
  "weaknesses": ["limited ablations"],
  "required_revisions": [],
  "risk_flags": []
}
```

Complete the critic:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  node critic-complete --run-id <run-id> --critic-id <critic-id>
```

Verdict mapping:

- `ACCEPT` -> `accepted`
- `REVISE` -> `candidate`
- `INVALID` -> `invalid`
- `REJECT` -> `rejected`

Small progress or partial success must be `REVISE`/`candidate`, not `ACCEPT`. Critic completion fails if node evidence changed after `critic-start`.

## Bug Repair

Let node workers debug themselves when practical; waiting for the orchestrator on every error burns tokens. There is no hard repair-attempt limit. The orchestrator should intervene when the same failure repeats without new information, when the worker requests a decision, or when an environment/reproducibility blocker appears.

Buggy node records should include:

- failure signature
- command
- exit code
- error path/log path
- retryability
- next action

Do not complete research with any node in `buggy`, `repairing`, `candidate`, `planned`, `implementing`, `running`, or `validating`.

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
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  subagent update \
  --run-id <run-id> \
  --subagent-id worker-node-001 \
  --node-id node-001 \
  --status running
```

After the worker writes its result payload to `result_path`:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
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

## Selection

After one or more accepted nodes exist, run final selection manually as orchestrator or spawn a short-lived selection/review agent. Scores help, but the orchestrator may make the final judgment by reading node evidence.

Selection payload:

```json
{
  "selected_node": "node-001",
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
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  selection finalize --run-id <run-id> --json '<selection JSON>'
```

Prefer `--path <selection.json>` over inline `--json` for selection payloads.

`selection finalize` requires the selected node to be accepted in `loop-state.json` with a fresh `ACCEPT` critic verdict, and all accepted nodes to appear in `ranked_nodes`.

## Completion And Handoff

Before completion:

1. Baseline is complete.
2. All subagents are terminal.
3. Blocking resources are resolved.
4. Every node is terminal: `accepted`, `invalid`, or `rejected`.
5. Every terminal node has a fresh critic ref matching its terminal verdict.
6. No critic is pending.
7. Selected node exists and is `accepted` with a fresh `ACCEPT` critic verdict.
8. `selection.json` is final and matches `loop-state.json`.
9. Node evidence satisfies `validate_run.py --gate research_to_review`.

Complete research with a passing audit:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  research complete --run-id <run-id> --path .ai-scientist/runs/<run-id>/logs/completion-audit.json
```

Then run validator:

```bash
python plugins/ai-scientist/scripts/validate_run.py \
  <target-repo> --gate research_to_review --run-id <run-id>
```

Record validation:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  validation record --run-id <run-id> --gate research_to_review --exit-code 0 --command "validate_run.py <target-repo> --gate research_to_review --run-id <run-id>"
```

Record approved handoff:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  handoff record --run-id <run-id> --gate research_to_review --exit-code 0 --approved --reason "research evidence ready for review"
```

Stop hook should allow ending only after completion, validation record, and approved handoff record exist.

Cancel only when explicitly requested or impossible to continue:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  research cancel --run-id <run-id> --reason "<reason>"
```

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
