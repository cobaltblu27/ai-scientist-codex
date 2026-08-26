---
name: research-loop-checkpoint
description: Persists a research-loop orchestration transition into loop-state.json and journal.jsonl so the run can resume and the Stop hook can enforce continuation. Use only when explicitly called by the research-loop orchestrator.
---

# Research Loop Checkpoint

<Purpose>
Record the smallest durable state patch needed for a resumed research-loop orchestrator. Preserve the existing `loop-state.json` and `journal.jsonl` contract; do not treat a checkpoint as scientific acceptance or a workflow transition by itself.
</Purpose>

<Workflow>
1. Read `.ai-scientist/runs/<run-id>/loop-state.json` and the latest `journal.jsonl` entry. Never checkpoint from conversation memory alone.
2. Build a small patch containing only changed fields. Use stable IDs. Valid patch sections are `baseline`, `work`, `tasks`, `resources`, `selection`, `resource_queue`, `nodes`, and `orchestrator`.
3. Preserve authority labels when recording requirements: `binding_contract`, `binding_amendment`, `current_plan`, `advisory`, or `superseded`.
4. Apply the patch using the existing merge rules:
   - shallow-merge object sections;
   - merge resource queues by stable job ID while preserving `pending`, `released`, and `completed` buckets;
   - merge each node by stable node ID and set its `updated_at`;
   - merge `orchestrator` and update `last_checkpoint_at`;
   - set a fresh `last_transition_id` such as `tr-<unique-id>`.
5. Append one valid JSONL journal record before writing the state:

```json
{
  "event_type": "state_transition",
  "timestamp": "<UTC timestamp>",
  "run_id": "<run-id>",
  "transition_id": "<same transition id as state>",
  "details": {
    "command": "research-loop-checkpoint",
    "changed_sections": ["orchestrator", "work"]
  }
}
```

6. Write the complete updated `loop-state.json` and verify that it parses and contains the same `last_transition_id` as the journal record.
7. Return the checkpoint path, transition ID, changed sections, and next action. Do not paste full reports into the checkpoint.

</Workflow>

<Safety>
Only the main orchestrator writes checkpoints. Workers return evidence and suggested patches; they do not overwrite shared state. If the state changed after step 1, reread it and rebuild the patch rather than overwriting newer work. If the state or journal is malformed, stop and report the repair needed.
</Safety>
