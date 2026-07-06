# Checkpointing

Use `research checkpoint` as resumable memory for the orchestrator. It is a durable patch to `loop-state.json`, not a report and not a workflow engine.

## When To Checkpoint

Checkpoint after durable transitions:

- spawning a worker, critic, revision worker, data-insight worker, or baseline worker;
- receiving a meaningful partial result or terminal result;
- recording a critic verdict, revision plan, branch decision, node status change, or final accept/reject/abandon decision;
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
    "current_node": "node-001",
    "reason": "worker-node-001 is running the assigned bounded piece"
  },
  "work": {
    "worker-node-001": {
      "kind": "worker",
      "node_id": "node-001",
      "status": "running",
      "agent_thread_id": "<codex-subagent-thread-id>",
      "agent_type": "ai-scientist-research-worker",
      "prompt_source": "prompts/research-loop/worker.md",
      "assignment_ref": ".ai-scientist/runs/<run-id>/logs/workers/node-001/worker-node-001/assignment.json",
      "result_ref": ".ai-scientist/runs/<run-id>/logs/workers/node-001/worker-node-001/result.md"
    }
  },
  "nodes": {
    "node-001": {
      "status": "running",
      "worker_id": "worker-node-001",
      "summary": "latest durable one-paragraph state",
      "evidence_refs": []
    }
  }
}
```

## Optional Sections

Add these only when they change:

- `baseline`: baseline readiness, fixed split refs, reproduced score refs.
- `resource_queue`: queued, released, or completed jobs when not using `resource run` directly.
- `selection`: accepted node and final selection refs.
- node critic/revision fields: `critic_ref`, `critic_verdict`, `revision_plan_ref`, `revision_critic_ref`, branch parent/source refs.

## Merge Behavior

`research checkpoint` merges top-level `baseline`, `work`, `tasks`, `resources`, `selection`, `resource_queue`, `nodes`, and `orchestrator` fields into `loop-state.json`.

Use stable ids for `work` and `nodes`. Reusing the same id updates that record.
