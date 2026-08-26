---
name: research-loop
description: >
  Runs the canonical orchestrator-led AI Scientist research loop with worker-owned nodes, resource leases, native agents, and durable continuation.
  Use only when the user explicitly invokes research-loop; never auto-select it.
---

<GreenField_Rule>
Do not consider backward compatibility.
Ignore legacy code/libraries.
DO NOT read or learn behavior from existing run artifacts.
Each run is a independent campaign, and previous runs may include artifacts created from legacy or deprecated rules.
</GreenField_Rule>

# Research Loop

<Big_Picture>
This is an orchestrator-led, durable research campaign.
Bootstrap a new run or resume `.ai-scientist/runs/<run-id>/`; the artifacts, not conversation memory, are the source of truth.
The orchestrator chooses and records research actions.
Dedicated workers own implementation and experiments in isolated node workspaces.
The loop continues while justified runnable work remains and ends only under `Terminal_Conditions`.
</Big_Picture>

<Startup>
For a new run, call `$research-loop-preflight`, then `$research-loop-bootstrap`.
They freeze `config.md`, including the idea batch, Python environment, research contract, resource policy, and available agent types.
Do not repeat them when resuming.
Choose a stable `<run-id>` and do not rename it.

Read `config.md`, `loop-state.json`, `journal.jsonl`, and referenced artifacts before acting.
`selection.json` exists only for a successful selection.
Keep logs under `.ai-scientist/runs/<run-id>/logs/` and node workspaces under `.ai-scientist/runs/<run-id>/nodes/<node-id>/workspace/`, unless config says otherwise.
</Startup>

<Run_State>
Use stable IDs for nodes and work.
Store worker reports under `logs/workers/<node-id>/<worker-id>/result.md`, baseline reports under `logs/baseline/<work-id>/result.md`, ranker reports under `logs/rankings/<ranking-id>/result.md`, and revision reports under
`logs/revisions/<node-id>/<revision-id>/result.md`.

`$research-loop-checkpoint` is durable resume memory, not a workflow engine or scientific judgment.
Keep patches small and link reports rather than copying them.
Mark requirements and actions by authority: `binding_contract`, `binding_amendment`, `current_plan`, `advisory`, or `superseded`.
A checkpoint never promotes a plan or recommendation into a binding requirement.
On resume, re-evaluate nonbinding open items against current evidence and supersede or explicitly abandon stale work.

Use terminal work statuses `completed`, `cancelled`, `failed`, `abandoned`, `accepted`, and `rejected`; use a specific nonterminal status while work is planned, running, blocked, waiting, or preparing an experiment.
Keep enough state to recover the owning node/work, current status, evidence refs, resource lease, and next action.
Every work item must become terminal or be explicitly abandoned before a terminal run outcome.

Keep `discovery-notes.md` as a concise, evidence-linked campaign wiki.
Add only transferable findings: what worked or failed, data/evaluation traps, and branch-worthy bottlenecks.
The orchestrator decides what enters it.
</Run_State>

<Non_Negotiable_Invariants>
- The orchestrator assigns, integrates, prioritizes, and records; it never implements node work itself.
- Workers own node execution.
  A node has its own worker, workspace, evidence trail, and resource records.
  Initial ideas each receive a node worker.
- The frozen config, state, journal, and selection artifact are authoritative; linked reports are evidence, and chat memory is not evidence.
- Checkpoint every durable transition: assignment, meaningful worker return, resource release/completion, ranking or revision decision, branch, acceptance, abandonment, and terminal transition.
  Use `$research-loop-checkpoint` and [checkpointing.md](references/checkpointing.md).
- Never wait while independent justified work is runnable.
  Idle capacity does not justify inventing work.
</Non_Negotiable_Invariants>

<Research_Contract>
`config.md` must contain the frozen contract and each idea's stable identity: title, core hypothesis, mechanism, source reference, and prior evidence.
If the contract is missing, stop and ask the user for it.

Only contract fields and explicit user-approved amendments are binding.
Suggested evaluations, controls, thresholds, advance/kill gates, implementation details, and resource estimates are advisory planning context; revise them as evidence requires without changing idea identity.
Do not promote general scientific norms into binding requirements.
Apply reproducibility, provenance, leakage, robustness, ablation, and mechanism checks only when the contract requires them or they are necessary to interpret a contract-scored claim.

Pass the contract to workers and revision workers, and its evaluation goal to the ranker.
A useful report, partial implementation, weaker metric, or negative result is never a successful outcome unless it satisfies `success_criteria`.
</Research_Contract>

<Main_Loop>
Repeat:

1. Reconstruct current state from durable artifacts.
2. Harvest finished worker work and released resource jobs.
3. Evaluate the active portfolio and transferable evidence.
4. Choose the highest-value runnable action: continue, diagnose, revise, branch, rank, experiment, abandon, or finalize.
5. Dispatch it to the appropriate native agent or release it to its worker.
6. Persist the resulting durable state transition.

Before deliberately waiting, sweep for other runnable work.
Follow `Terminal_Conditions`, not a presumed successful result.
If a baseline is required for fixed splits or comparable scoring, dispatch it first or in parallel where dependency-safe, then share its authoritative manifest with the relevant node workers.
</Main_Loop>

<Action_Policy>
Classify candidate work before assigning it:

- `Enhance`: same mechanism, implementation fix, bounded ablation, or depth on a promising node.
- `Revise`: bounded architecture, objective, preprocessing, training, or experiment change that preserves the node's direction.
- `Branch`: a distinct architecture, mechanism, or hypothesis needing its own evidence trail.
- `Diagnose`: data insight, slice/error analysis, ablation, baseline comparison, or validation that identifies a bottleneck or selects a direction.
- `Experiment`: implemented experimental work.
- `Rank`: scarce follow-up allocation among a comparable completed cohort.
- `Finalize`: acceptance audit or a justified terminal outcome.

Portfolio balance is a scientific policy, not a quota.
Prefer the contract-relevant action with the strongest evidence; when choosing another same-direction tweak over a branch or diagnostic, record the rationale.
Keep capacity for the best current node and required validation without fragmenting the portfolio.
A clean rerun or direct mechanical repair belongs with the node worker; reserve revision workers for diagnosis and redesigned scientific work.
</Action_Policy>

<Progress_Portfolio_And_Stagnation>
## Progress

Weak early metrics, distance from the acceptance threshold, and node-level rejection are evidence, not campaign halt conditions.
Implement and evaluate runnable initial nodes before declaring the campaign nonviable.
A failed node must leave a failure decomposition, mechanism evidence, or justified next hypothesis.

## Portfolio

Maintain an exploration–exploitation portfolio within the configurable active-node cap.
Unless config overrides it, reserve three roles: one exploitation branch from the strongest validated node, one adjacent branch replacing a diagnosed failed subsystem, and one exploratory branch with a substantially different
representation, objective, training procedure, data source, or clean-sheet architecture.
The ranker may remove weak or redundant nodes but must preserve a scientifically distinct exploration slot.
Rank it on the primary score plus causal mechanism evidence, useful slice behavior, orthogonal errors, or a newly localized bottleneck.

## Plateau

Orient the declared primary metric so larger is better.
With comparable split, evaluator, and budget, declare a plateau when four consecutive completed nodes fail to improve the best score by at least `max(metric_noise, 0.01 * abs(T-B))`, where `B` is the comparable baseline and `T` the contract
success threshold; use one standard error for `metric_noise` when repeated runs exist, otherwise zero unless the contract defines a noise floor.
Confirm the plateau when the same dominant failure decomposition appears in at least two of those nodes or their architectures differ only by minor edits.

## Structural Exploration

On a plateau, structurally explore: replace or reorganize major trainable pathways, jointly retrain upstream modules, train from scratch, change the learning objective, or add a contract-compatible auxiliary dataset.
Do not answer it with another post-hoc module.

For every tried node, call `$architecture-tree` and measure its distance from its direct parent as the minimum number of canonical tree add, remove, or replace edits.
On a plateau, the next exploratory branch must have distance at least `max(3, 2 * median(previous_four_parent_distances))` from its selected parent.
It must change a representation, fusion, training, supervision, or data pathway; predictor-only changes and post-hoc modules do not qualify.
Record the parent, edit script, distance, target failure decomposition, and architecture-level hypothesis.
Prefer an evidence-backed parent that has not yet produced a child before expanding a lineage again; this is a priority, not a ban on a second justified child.

## Branch Design

Scientific ancestry does not freeze parent parameters.
Each branch plan states whether it trains from scratch, copies and unfreezes the parent, partially freezes it with a scientific reason, reuses only data/code, or uses the parent only as an evaluation comparator.
Prefer coherent end-to-end architectures over patches: every revision plan states one architecture-level hypothesis, how its modules implement it jointly, possible bypass paths, and why it can learn without parent predictions or post-hoc
correction.
</Progress_Portfolio_And_Stagnation>

<Agent_Routing>
Use native agents after verifying the role is available.
Pass only dynamic assignment context; do not read or paste prompt files into assignments.

- Baseline: `ai-scientist-research-baseline-worker` when the contract needs a frozen split or missing comparable baseline evidence.
- Node: `ai-scientist-research-worker` for each initial or branched node.
- Ranker: `ai-scientist-research-ranker` for a comparable completed cohort.
- Revision: `ai-scientist-research-revision-worker` for open-ended failure analysis or scientific redesign.
  It uses `revision-brainstorm`; use `data-insight-revision` when fresh data/model/benchmark diagnosis is needed.

For a new node, record its seed idea, frozen contract, resource policy, workspace, expected result path, relevant baseline refs, and current evidence.
The first node-worker return is an ordered, amendable execution todo list; review it, then resume the same worker to execute useful todos sequentially.
Workers return at a resource-heavy boundary, decision-worthy result, blocker, direction-changing finding, or planned-work completion.
Resume the same node worker when practical.
Record agent type, assignment/result refs, worker id, status, evidence summary, remaining todos, and next action in the checkpoint.

The ranker receives a cohort, requested top `N`, target/current best result, and direct evidence refs.
It never receives worker todos, ranking prose, report-length signals, or accumulated selection counts as prestige signals.
Ranker prose is not worker feedback: follow-up workers receive measured evidence and their own assignment context instead.
</Agent_Routing>

<Resource_Scheduling>
The orchestrator owns the durable resource queue; workers execute heavy jobs.
At every scheduler sweep, harvest released jobs, release pending jobs that fit the frozen capacity policy, and continue other runnable work.
Never block the orchestrator on a running experiment.
Before manipulating heavy work, read [resource-runs.md](references/resource-runs.md).
Record enough command, allocation, output, and release evidence to distinguish scientific failure from resource or environment failure.

Scheduling is work-conserving: a long-running (more than 10 minutes) or resource-waiting node cannot starve another runnable node.
At every polling boundary inspect all active lanes, dispatch actionable work, and allocate available resources.
A requested multi-GPU allocation is not a blocker when the job runs correctly on fewer devices.
Use a real sleeping process between polls; for jobs expected to exceed an hour, poll about every 10–15 minutes, never exceeding 15 minutes, then poll all active lanes.
Resource waits, long runtime, and weak scores are not terminal failures.
</Resource_Scheduling>

<Branch_And_Rank>
A branch is a new normal node with its own worker, workspace, and evidence trail.
It may come from any evidence-backed parent, not only the champion.
Create one only for a distinct mechanism or hypothesis with a credible route to the binding criteria and within the active-node cap.
Keep bounded changes in the same node.
Record parent, rationale, and source evidence.

The ranker allocates scarce follow-up slots among a comparable completed cohort; default to `N = 3` unless the active-node cap or frozen resource policy requires fewer slots.
It is not a reviewer, validator, acceptance gate, or source of worker instructions.
Its selection grants follow-up eligibility only.
Read [branching-policy.md](references/branching-policy.md) or [ranking-policy.md](references/ranking-policy.md) when performing those decisions.
</Branch_And_Rank>

<Research_Implementation_And_Evaluation>
Build only what the experiment requires.
Reuse existing utilities and native framework features; avoid speculative abstractions, generalized policy engines, permission systems, sandboxes, and critic-generated guardrail infrastructure.
Use direct code/data inspection and minimal focused checks for leakage and scientific integrity.

Rank with one declared comparable primary metric.
Training losses and inner metrics are diagnostics unless the contract makes them binding.
Freeze candidate predictions before reading evaluation labels or comparator predictions.
An entity claimed as held out is excluded from every fitted component—including auxiliary pretraining and learned preprocessing—according to the contract.
Cheap fixed screens may precede full evaluation; promote a node when it improves the primary score or supplies strong, reproducible mechanism evidence for a subsequent architecture.
</Research_Implementation_And_Evaluation>

<Terminal_Conditions>
A run terminates with exactly one outcome:

- `success`: one outcome satisfies the binding positive criteria;
- `exhausted`: no justified runnable work remains, or the frozen resource budget is exhausted without success;
- `cancelled`: the user explicitly cancels the run;
- `blocked`: an unresolved binding dependency prevents further work.

Before any terminal transition, harvest/retire outstanding work, drain or explicitly abandon pending and released queue items, and release active leases.
Do not call a failed experiment `exhausted` while a contract-relevant diagnostic, revision, branch, or rerun remains justified and fits the frozen policy.
Do not continue after an `exhausted` decision merely because capacity is idle.
For `success`, write `selection.json` with the accepted node, evidence refs, and acceptance rationale after a completion audit verifies the binding positive criteria.
For every outcome, checkpoint the audit, reason, terminal `phase_status`, and handoff evidence.
Mark the goal `complete` for `success`, `exhausted`, or `cancelled`; for `blocked`, use `update_goal` with `status: blocked` only when its blocking rule is satisfied.
Do not create an accepted selection for `exhausted`, `cancelled`, or `blocked`.
</Terminal_Conditions>

<References>
- [checkpointing.md](references/checkpointing.md): durable state schemas.
- [resource-runs.md](references/resource-runs.md): queue and lease handling.
- [ranking-policy.md](references/ranking-policy.md): cohort allocation.
- [branching-policy.md](references/branching-policy.md): branch semantics.
</References>
