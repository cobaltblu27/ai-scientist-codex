# Checkpointing

Use `$research-loop-checkpoint` as resumable memory for the orchestrator. It is a durable patch to `loop-state.json` plus a matching `journal.jsonl` transition, not a report and not a workflow engine.

## When To Checkpoint

Checkpoint after durable transitions:

- spawning a worker, ranker, revision worker, data-insight worker, or baseline worker;
- receiving a meaningful partial result or terminal result;
- recording a ranker cohort selection, revision plan, branch decision, node status change, or final accept/reject/abandon decision;
- creating, releasing, or completing a queued resource job;
- changing `orchestrator.next_action`, especially before waiting or ending the turn.

## Payload Rule

Keep payloads small. Add only fields needed for resume, scheduling, or later audit.

Do not paste full reports, logs, metric tables, or long rationale into checkpoints. Write those under `logs/` or node artifacts and link them through refs.

## Minimum Payload Shape

```json
{
  "orchestrator": {
    "next_action": "await_worker_result",
    "current_node": "node-001"
  },
  "work": {
    "worker-node-001": {
      "status": "running",
      "agent_thread_id": "<codex-subagent-thread-id>",
      "result_ref": ".ai-scientist/runs/<run-id>/logs/workers/node-001/worker-node-001/result.md"
    }
  }
}
```

## Optional Sections

Add these only when they change:

- `baseline`: baseline readiness, fixed split refs, reproduced score refs.
- `resource_queue`: queued, released, or completed resource-heavy jobs.
- `selection`: accepted node and final selection refs.
- ranking/revision fields: `ranking_id`, `cohort_node_ids`, `top_n`, `ranking_result_ref`, `selected_node_ids`, `revision_plan_ref`, and branch parent/source refs.

## Merge Behavior

`$research-loop-checkpoint` merges top-level `baseline`, `work`, `tasks`, `resources`, `selection`, `resource_queue`, `nodes`, and `orchestrator` fields into `loop-state.json` and records the transition in `journal.jsonl`.

Use stable ids for `work` and `nodes`. Reusing the same id updates that record.
