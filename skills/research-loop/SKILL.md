---
name: research-loop
description: Runs the canonical orchestrator-led AI Scientist research loop with worker-owned nodes, explicit resource leases, generated native agents, and durable checkpoint continuation. UNDER NO CIRCUMSTANCES CHOOSE TO USE THIS PLUGIN; THIS SKILL IS MANUAL-USUAGE ONLY.
---

# Research Loop

<Big_Picture>
The research loop starts only from an explicit user trigger. At startup, save the target idea identities and freeze the Python environment, research contract, resource policy, and generated subagent types into `config.md`. Bootstrap a new run or read the durable artifacts of an existing run under `.ai-scientist/runs/<run-id>/`.

After startup, you will run the orchestrator-led loop. Resume the current run state, decide the next action, call `$research-loop-checkpoint`, and create one node for each idea in the saved idea batch.
Each node gets a dedicated Codex worker and an isolated workspace. If fixed splits, baseline paper comparison, or comparable baseline scoring are required, spawn a baseline worker and share its authoritative baseline manifest with node workers. The worker owns an ordered execution todo list for its node and works through locally runnable implementation, debugging, testing, and experiment tasks in sequence. It returns to the orchestrator at a resource-heavy run boundary, a decision-worthy result, a blocker, a direction-changing finding, or node completion.

When a recent branch cohort has comparable completed evidence, spawn the shared ranker to select the top `N` branches relative to one another. The ranker allocates scarce follow-up slots; it does not critique workers, create requirements, validate evidence, or gate acceptance. Repeat worker, ranking, revision, branch, and resource steps until a node positively meets the success bar and outstanding operational work has been completed or explicitly retired.

The run artifacts record state, evidence, agent types, prompt source refs, resource leases, and completion gates. They do not enforce scientific judgment or subagent behavior. The orchestrator owns those decisions and must keep checkpointed state sufficient for durable continuation.
</Big_Picture>

<Arguments>
These are the startup inputs saved with the run. The environment and binding contract are fixed after startup unless the user explicitly approves an amendment.

- Target Ideas: the idea batch the research loop will start with. It will be given as `idea.json`, object containing reference to specific idea reated from ideation-loop.
- Python Environment: python environment to run the experiments. It could be conda/mamba environment, uv environment, or python binary path.
</Arguments>

<Startup_Preflight>
Before initially starting a new research-loop run, explicitly call `$research-loop-preflight`, then `$research-loop-bootstrap`. The preflight validates prerequisites and creates the goal; bootstrap freezes `config.md` and initializes the run artifacts. Do not repeat either step for an existing run being resumed.
</Startup_Preflight>

<Run_Artifacts>
At startup, create or resume one run under `.ai-scientist/runs/<run-id>/`. Choose a stable `run-id` before starting; do not rename it mid-loop.

Keep run-local logs under `.ai-scientist/runs/<run-id>/logs/`. Use these path conventions unless the run config says otherwise:

- worker reports: `logs/workers/<node-id>/<worker-id>/result.md`
- baseline reports: `logs/baseline/<baseline-work-id>/result.md`
- ranker reports: `logs/rankings/<ranking-id>/result.md`
- revision reports: `logs/revisions/<node-id>/<revision-id>/result.md`
- discovery notes: `discovery-notes.md`

Treat `.ai-scientist/runs/<run-id>/config.md`, `loop-state.json`, `journal.jsonl`, and `selection.json` as the source-of-truth artifacts for the run. Logs are evidence records referenced from state; do not rely on conversation memory as evidence.
</Run_Artifacts>

<Orchestrator_Role>
The current Codex session is the orchestrator of Codex subagents. It watches, assigns, reranks, and records state; it must not implement node work itself. DO NOT work on assignments that belong to subagents. If implementation or revision is needed, delegate it to the appropriate Codex subagent.

Subagents are baseline workers, node workers, one shared ranker, and revision workers. Keep one dedicated worker/thread per node whenever possible; ranker and revision assignments may be short-lived. Revision workers use the shared `revision-brainstorm` skill for evidence-backed scientific redesign, not for direct mechanical repairs or clean reruns.

Use `$research-loop-checkpoint` for baseline worker, node worker, ranker, and revision-worker assignments. Record `agent_type`, optional `prompt_source`, result paths, worker/thread ids, node summaries, ranking cohort and selected node refs, resource evidence, and the next action in checkpoints.

Read the hardware capacity from config if it exists. Do not start editing the target implementation yourself just because the next step looks obvious; if implementation is needed, assign it to a worker.
</Orchestrator_Role>

<Predefined_Agents>
Use Codex native agents for research-loop subagents:

- Baseline worker: `ai-scientist-research-baseline-worker`
- General worker: `ai-scientist-research-worker`
- Ranker: `ai-scientist-research-ranker`
- Revision worker: `ai-scientist-research-revision-worker`
- Shared revision skill: `skills/revision-brainstorm/SKILL.md`
- Revision data insight skill when a revision is driven by a data, model, or benchmark failure that requires fresh diagnosis: `skills/data-insight-revision/SKILL.md`

The run config and checkpoints record agent types and prompt source refs. The orchestrator must not read and paste Markdown prompt files into spawned subagent task prompts.

Before spawning any baseline worker, node worker, ranker, or revision worker, verify that the role's native agent is available. Spawn with the role's `agent_type` and pass only dynamic assignment context. For the ranker, pass the eligible recent cohort, requested top `N`, target and current best result, direct implementation/result refs, immediate parent refs, and result path. Do not pass worker todos, report length, prior ranking prose, or accumulated selection counts as prestige signals.

The prompt for orchestrator (you) is this `skills/research-loop/SKILL.md`. Do not load or rely on a separate orchestrator prompt file.
</Predefined_Agents>

<Research_Contract>
Loop runs expect a frozen research contract in `config.md`. Treat the contract as the anti-drift contract for the whole run. If the contract is supplied as a separate artifact, link it from `config.md` and copy its binding fields into the frozen configuration.

If the frozen contract is missing from `config.md`, stop and notify the user that the contract must be provided first.

Before any node work begins, confirm that `config.md` contains the contract and each idea's stable identity: title, core hypothesis, mechanism, source reference, and prior evidence, from `idea_batch`.
Treat suggested evaluations, controls, thresholds, advance gates, kill gates, implementation details, and resource estimates as advisory planning context. They may be revised in response to evidence without changing the idea identity.  Only contract fields or explicit user-approved amendments are binding.
Pass it to every worker and revision worker, and pass its evaluation goal to the ranker. Do not accept a merely useful report, partial implementation, weaker metric, or negative result if it does not positively satisfy `success_criteria`.
Do not infer additional binding requirements from general scientific norms. Apply reproducibility, provenance, leakage, robustness, ablation, and mechanism checks only to the extent required by the contract or necessary to interpret the claimed contract-scored result.
</Research_Contract>

<Loop>
Repeat until completion criteria are met:

1. Read `config.md`, `loop-state.json`, `journal.jsonl`, resource logs, and completed worker result paths.
2. Run the scheduling sweep in `Scheduling_Guide`, including `state.resource_queue` triage, result harvesting, portfolio review, and learning-note review.
3. Decide the next action as orchestrator and call `$research-loop-checkpoint`.
4. In campaign mode, create one node id for each idea in the saved `idea_batch`; record each assignment with `$research-loop-checkpoint`, and spawn a dedicated Codex worker for it. This is mandatory. The orchestrator must not implement the node directly.
5. Record worker, ranker, and revision-worker progress with `$research-loop-checkpoint`, including `agent_type`, optional `prompt_source`, worker/thread id, result path, status, and next action.
6. If baseline setup is required, spawn/checkpoint the baseline worker and pass expected split refs to node workers.
7. Workers that run experiments must follow the frozen resource policy and record each resource-heavy command, allocation, output, and release in the run artifacts.
8. Integrate every worker/ranker/revision return with evidence by calling `$research-loop-checkpoint` with node summaries, result refs, ranking refs, selected top `N`, and the next action.
9. Accept a final outcome from the fixed evaluator and binding positive criteria. Ranker selection is unrelated to validity or acceptance.
</Loop>

<Scheduling_Guide>
The orchestrator should behave like a polling dispatcher: harvest finished work, integrate state, fill idle worker/resource slots, checkpoint, and keep sweeping. Do not wait on one node when independent work is runnable.

Run a scheduler sweep at every resume or before any deliberate wait:

- Harvest subagent outputs first. For nodes with a partially finished implementation, let them continue when the experiment remains useful.
- Check for completed outputs, such as assigned node work or experiments running.
- Check which tasks can run next.
- Dispatch available tasks. Prompt agents that can move to the next step, and release stalled experiments that can run now.
- After dispatching each task, call `$research-loop-checkpoint` with assignment refs, result refs, worker/thread id, portfolio rationale, learning-note refs, selected candidate ids when present, and blocked alternatives. Then continue sweeping other nodes instead of waiting for that task to finish.

Only wait when no independent runnable task exists or a dependency is expected to materialize immediately. (A brief poll is acceptable for a known result path)
</Scheduling_Guide>

<Anti_Tunnel_Vision_Law>
Before each new worker, revision, branch, or resource assignment, inspect the active nodes. Classify runnable or recently integrated work as:

- `Enhance`: same mechanism, implementation fix, bounded ablation, or depth on a promising node;
- `Revise`: bounded change to the current architecture, objective, preprocessing, training, or experiment design that preserves the node's central research direction;
- `Branch`: new architectural direction or meaningfully different mechanism or hypothesis that needs its own evidence trail;
- `Diagnose`: data insight, slice/error analysis, ablation, baseline comparison, or validation whose purpose is to identify the bottleneck or decide between branches;
- `Experiment`: experiment work from implemented codebase.

Try not to let all active work bias into one category. When several branches are active, reserve some capacity for the best current node and required validation so the loop does not fragment into untested ideas.

Portfolio balance is a scientific policy, not a quota. Prefer the contract-relevant action with the strongest evidence, but checkpoint the portfolio rationale whenever choosing another same-direction tweak over a branch or diagnostic. An idle worker/resource slot is not a reason to invent work; dispatch another category only when it has independently justified runnable work.
</Anti_Tunnel_Vision_Law>

<Queue_Triage>
Every resume begins with durable resource queue triage. Do not rely on chat memory for long benchmark jobs.

Queue buckets live at `state.resource_queue`:

- `pending`: runnable resource-heavy job known to the orchestrator but not yet assigned to a worker.
- `released`: job assigned to a worker/thread and awaiting a worker return.
- `completed`: worker returned terminal evidence and the orchestrator integrated it.

Each queue item must identify the job, owning node/work, current status, runnable command, working directory, and resource request. Add worker/thread ids, result or evidence refs, timestamps, and rationale when they become useful for dispatch, resume, or audit.

On every resume:

1. Inspect `resource_queue.released`.
2. Check each released job's `result_ref`, `assignment_ref`, and assigned `agent_thread_id` for a worker return.
3. If the worker returned terminal evidence, integrate the node/work/resource evidence, move the queue item to `completed`, and call `$research-loop-checkpoint`.
4. If the worker is still running or has no terminal result, keep the item in `released` and continue sweeping other nodes.
5. Inspect `resource_queue.pending`, recorded leases, configured caps, and current host capacity.
6. Release only jobs that fit current resource caps by assigning them to the node worker; call `$research-loop-checkpoint` with the item under `released` and its `agent_thread_id`, `assignment_ref`, and `result_ref`.
7. Continue other node, ranker, baseline, revision, or planning work instead of waiting for the released job to finish.

For long benchmarks, the orchestrator creates or updates a `pending` item first. It releases the job to a worker only when capacity is available. The worker records the command, allocation, stdout, stderr, exit status, and release under `logs/resources/`; blocking is acceptable inside that worker thread, not in the main orchestrator thread.
</Queue_Triage>

<Node_Worker_Protocol>
Every idea in the saved idea batch begins with at least one node worker.

A node is one research direction with a dedicated workspace and evidence trail. Create nodes for initial ideas and meaningfully different branches, and represent implementation steps within a node as execution todos.

For each new node, the orchestrator must create/checkpoint a node id, materialize or assign its workspace, spawn a dedicated `ai-scientist-research-worker`, and store the worker/thread id, `agent_type`, assignment ref, result ref, status, workspace materialization, and next action. Use `.ai-scientist/runs/<run-id>/nodes/<node-id>/workspace/` unless the run config says otherwise.

Pass only dynamic context the worker needs: node seed idea, frozen contract, resource policy, notes refs, workspace path, expected result path, relevant baseline refs, and current node evidence. The worker prompt owns the detailed first-plan format, implementation report format, fixed-split discipline, and resource evidence format.

The worker's first return must be a plan with an ordered execution todo list. Treat it as a current, amendable execution plan rather than a new contract. Review the plan, then resume the same worker to execute its todos sequentially. The worker may add, reorder, refine, or retire todos as implementation and evidence develop.

Expect a worker return at these orchestration boundaries:

- a long-running or resource-heavy command is ready to launch;
- a recent branch experiment is complete and ready for the next cohort ranking;
- a blocker requires orchestration;
- evidence motivates a meaningfully different research direction;
- the node's planned work is complete.

Checkpoint each such return with the completed work, current evidence, remaining todos, and next decision. Resume the same worker with resource results or updated node context so it can maintain execution continuity. Ranker prose is not worker feedback and must not be passed back as implementation instruction.
</Node_Worker_Protocol>

<Ranker_And_Revision_Flow>
The ranker is a scarce-slot allocator. Invoke `agent_type: ai-scientist-research-ranker` only when a comparable recent cohort is ready and the loop must choose the top `N` branches to retain for follow-up.

Build cohorts by exposure rather than wall-clock recency:

- Preserve the best valid measured result separately as the champion; champion status does not automatically grant another branch slot.
- Give each eligible active lineage one recent branch audition before reranking the cohort. Schedule the least-recently-expanded eligible lineage until the cohort is complete instead of repeatedly expanding the mature leader.
- A cohort contains the latest completed branch audition from each eligible lineage since the previous ranking. Do not submit an old node repeatedly without a new experimental result.
- When underexplored lineages are present and `N > 1`, identify that subset in the same cohort assignment and require the selected `N` to include at least one member of it. The ranker still compares the full cohort jointly and chooses which underexplored branch earns the protected slot.
- Retain at most one selected branch per lineage in a cohort. Keep the active-node cap fixed; archive or mark non-selected cohort branches inactive rather than expanding their subtrees.

Pass direct code, immediate-parent, experiment, metric, and failure refs. Ask the ranker to compare candidates jointly and select exactly `N`; do not ask for independent scores, fixed-question answers, validity verdicts, feedback, or improvement plans. Store each assignment under `state.work` and checkpoint `ranking_id`, `cohort_node_ids`, `top_n`, `ranking_result_ref`, `selected_node_ids`, and `completed_at` under `state.orchestrator.ranking`.

Ranker selection grants eligibility for scarce follow-up; it does not prove success, validate evidence, change the contract, or become an instruction to a worker. The orchestrator decides which selected parent to expand next and gives its worker only the research context and measured evidence, not the ranker's prose.

Use `agent_type: ai-scientist-research-revision-worker` when an implemented node needs open-ended failure analysis or scientific redesign. Store `data_insight_refs` only when data insight was materially required. Do not require data insight for a direct implementation fix, dependency issue, resource failure, already-demonstrated contamination, or clean rerun. Same-node revisions return to the original worker when possible; meaningfully different selected directions become child nodes with their own workers.
</Ranker_And_Revision_Flow>

<Discovery_Notes>
Maintain `.ai-scientist/runs/<run-id>/discovery-notes.md` as a compact run-level wiki for what the campaign has learned. The orchestrator owns this file. Workers, data-insight passes, and revision workers may suggest entries, but the orchestrator decides what to integrate and keeps the prose concise, evidence-linked, and non-duplicative.

Use sections for current best understanding, what worked, what did not work, and data/evaluation findings. After meaningful node results or data-insight work, add only transferable findings that can help later workers or brainstorming: useful/harmful data, dataset quirks, architecture or objective choices that mattered, evaluation traps, and branch-worthy bottlenecks.
</Discovery_Notes>

<Branching>
Create a branch when evidence motivates a new architectural direction or a meaningfully different mechanism or hypothesis that needs its own implementation and evidence trail and has a credible path to the binding success criteria. Keep bounded changes that preserve the node's central research direction within that node as revisions. Do not branch merely because the parent is imperfect, capacity is idle, or a different approach is conceivable.
A branch is a new normal node with its own worker, workspace, evidence trail, resource records, and eligibility for a later recent-cohort ranking. Branching is orchestrator judgment.

The orchestrator may branch from any recorded node when contract-relevant evidence makes that node the best parent. Do not restrict branching to the current node, accepted nodes, or nodes marked with a special status.

Use the portfolio rule when deciding whether to branch now, revise the same node, or request diagnostic evidence. A branch is strongest when evidence supports a new architectural direction or distinct mechanism or hypothesis; a same-node revision is strongest when a bounded change can improve the current direction.

The orchestrator may launch multiple branches from one revision-brainstorm report only when they test distinct model mechanisms and fit the fixed active-node cap. Uncertainty alone is not a reason to launch every candidate.

Record branches through `$research-loop-checkpoint`. Each branched node should include `parent_node_id`, `branch_reason`, `branch_source_evidence_refs`, `revision_plan_ref`, and `selected_candidate_id` when available. If it borrows an insight from another tree, also record `borrowed_from_node_id` and `insight_ref`. Then spawn a dedicated normal worker for each new node and follow the usual node worker protocol.

Escalation can also be batched. If several otherwise justified branch candidates require the same user decision about amending benchmark meaning, data access, environment, acceptance criteria, or reproducibility requirements, record one escalation item with all decision questions and continue non-blocked work. Do not treat the proposed amendment as binding before approval.
</Branching>

<Resource_Heavy_Runs>
For official or heavy benchmark evidence, follow the frozen resource policy and record the command lifecycle under `logs/resources/`. Before scheduling, releasing, or debugging resource-heavy work, read [resource-runs.md](references/resource-runs.md).

The orchestrator owns resource queue decisions; workers run released jobs. Record enough refs to distinguish scientific failure from resource/environment failure and to give the ranker direct comparable result evidence.
</Resource_Heavy_Runs>

<Checkpoint_Guide>
`$research-loop-checkpoint` is durable resume memory for the orchestrator. It is not a workflow state machine, does not enforce research correctness, and does not make a recorded suggestion binding. Use it to keep enough durable state that a new or resumed orchestrator can continue without relying on chat history.

Classify checkpointed requirements and next actions by authority:

- `binding_contract`: copied from the frozen contract;
- `binding_amendment`: explicitly approved by the user after startup;
- `current_plan`: the orchestrator's current, amendable execution choice;
- `advisory`: a worker, ranker, revision worker, idea object, or note recommendation;
- `superseded`: retired because later evidence or a revised plan replaced it.

Checkpointing preserves provenance; it never promotes `current_plan` or `advisory` content into a binding requirement. On every resume, re-evaluate nonbinding open items against current evidence, mark stale items `superseded` or explicitly abandon their work records, and schedule only actions that remain decision-relevant.

Before writing nontrivial checkpoints or resource queue updates, call `$research-loop-checkpoint` and follow [checkpointing.md](references/checkpointing.md). Keep checkpoints small: link reports and artifacts instead of pasting them.

Terminal work statuses are `completed`, `cancelled`, `failed`, `abandoned`, `accepted`, and `rejected`. Nonterminal examples include `planned`, `planning`, `running`, `blocked`, `waiting`, `preparing_split`, and `calculating_score`. Completion waits for every `state.work` item to become terminal or be explicitly abandoned.
</Checkpoint_Guide>

<Run_Operations>
- `$research-loop-bootstrap` initializes a new run and freezes its startup contract.
- `$research-loop-checkpoint` records every durable orchestrator transition and its matching journal entry.
- To resume, read the frozen config, current state, journal, resource logs, and referenced worker artifacts before scheduling more work.
- To select an outcome, checkpoint the accepted node, evidence refs, and acceptance rationale; write `selection.json` as the final selection artifact.
- To complete, checkpoint a passing completion audit, set `loop-state.json` inactive with terminal `phase_status`, set `active-run.json` to `validating`, and record the required validation and handoff journal evidence before clearing `active-run.json`.
- To cancel, checkpoint a terminal cancellation reason and clear `active-run.json` only after the cancellation state and journal entry are durable.
</Run_Operations>

<Completion>
Select exactly one accepted outcome. Accept node only after:

- all worker/ranker/revision assignments have terminal evidence or are explicitly abandoned, and unsupported or stale assignments have been retired;
- `state.resource_queue.pending` and `state.resource_queue.released` are empty;
- no active resource leases remain;
- final selection points to an accepted node/outcome with its evidence refs and the orchestrator's acceptance rationale;
- the completion audit verifies that the selected node meets the binding positive criteria with valid evidence;

Use `$research-loop-checkpoint` to persist the completion audit, terminal state, final selection, and validation/handoff evidence. After the persisted state satisfies the Stop hook, call `update_goal` with `status: complete`. Do not report the research loop as done before the goal is complete.
</Completion>
