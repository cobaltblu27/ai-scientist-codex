---
name: research-loop-checkpoint
description: Persists a research-loop orchestration transition into loop-state.json and journal.jsonl so the run can resume and the Stop hook can enforce continuation. Use only when explicitly called by the research-loop orchestrator.
---

# Research Loop Checkpoint

<Purpose>
Record the smallest durable state patch needed for a resumed research-loop orchestrator. Preserve the existing `loop-state.json` and `journal.jsonl` contract; do not treat a checkpoint as scientific acceptance or a workflow transition by itself.
</Purpose>

<Use_When>
- The research-loop orchestrator explicitly calls `$research-loop-checkpoint` after a durable assignment, result, queue change, branch/revision decision, selection change, or next-action change.
- The orchestrator is about to wait, end its turn, or delegate work and needs a resumable cursor.
</Use_When>

<Do_Not_Use_When>
- The user has not explicitly called this skill or the research-loop orchestrator has not assigned it.
- The change is only conversational reasoning with no durable state consequence.
- The goal is to validate, accept, or complete a run; checkpointing records those decisions but does not validate them.
</Do_Not_Use_When>

<Workflow>
1. Read `.ai-scientist/runs/<run-id>/loop-state.json` and the latest `journal.jsonl` entry. Never checkpoint from conversation memory alone.
2. Build a small patch containing only changed fields. Use stable IDs. Valid patch sections are `baseline`, `work`, `tasks`, `resources`, `selection`, `resource_queue`, `nodes`, and `orchestrator`.
3. Preserve authority labels when recording requirements: `binding_contract`, `binding_amendment`, `current_plan`, `advisory`, or `superseded`.
4. Compute `before_hash` as the SHA-256 of the canonical JSON encoding of the complete current state: sorted keys, compact separators, UTF-8.
5. Apply the patch using the existing merge rules:
   - shallow-merge object sections;
   - merge resource queues by stable job ID while preserving `pending`, `released`, and `completed` buckets;
   - merge each node by stable node ID and set its `updated_at`;
   - merge `orchestrator` and update `last_checkpoint_at`;
   - set a fresh `last_transition_id` such as `tr-<unique-id>`.
6. Compute `after_hash` from the complete updated state using the same canonical encoding.
7. Append one valid JSONL journal record before writing the state:

```json
{
  "event_type": "state_transition",
  "timestamp": "<UTC timestamp>",
  "run_id": "<run-id>",
  "transition_id": "<same transition id as state>",
  "before_hash": "<before hash>",
  "after_hash": "<after hash>",
  "details": {
    "command": "research-loop-checkpoint",
    "changed_sections": ["orchestrator", "work"]
  }
}
```

8. Write the complete updated `loop-state.json` and verify that it parses, contains the same `last_transition_id` as the journal record, and hashes to `after_hash`.
9. Return the checkpoint path, transition ID, changed sections, and next action. Do not paste full reports into the checkpoint.
</Workflow>

<Safety>
Only the main orchestrator writes checkpoints. Workers return evidence and suggested patches; they do not overwrite shared state. If the state changed after step 1, reread it and rebuild the patch rather than overwriting newer work. If the state or journal is malformed, stop and report the repair needed.
</Safety>
