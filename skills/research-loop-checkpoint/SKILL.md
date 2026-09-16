---
name: research-loop-checkpoint
description: Persists a research-loop orchestration transition into loop-state.json and journal.jsonl so the `/goal` campaign can resume reliably. Use only when explicitly called by the research-loop orchestrator.
---

# Research Loop Checkpoint

<Purpose>
Record the smallest durable state patch needed for a resumed research-loop orchestrator. Preserve the existing `loop-state.json` and `journal.jsonl` contract; do not treat a checkpoint as scientific acceptance or a workflow transition by itself.
</Purpose>

<Workflow>
1. Read `.ai-scientist/runs/<run-id>/loop-state.json` and the latest `journal.jsonl` entry. Never checkpoint from conversation memory alone.
2. Build a small patch containing only changed fields. Use stable IDs. Valid patch sections are `baseline`, `work`, `tasks`, `resources`, `selection`, `resource_queue`, `nodes`, and `orchestrator`. Artifact shapes are defined in `docs/SCHEMA.md` (plugin repo); honor its required keys, everything else is free. Every `work` entry carries `status`, `agent_thread_id`, `result_ref`, and `node` (owning node id, or `null` for run-wide work); a branch node entry carries `parent_node_id`. Statuses are lowercase; a node or work item is terminal only when its status is one of `completed`, `cancelled`, `failed`, `abandoned`, `accepted`, `rejected`.
3. Preserve authority labels when recording requirements: `binding_contract`, `binding_amendment`, `current_plan`, `advisory`, or `superseded`. A requirement the user adds after the contract was frozen is a `binding_amendment`; keep it in the `orchestrator` section so a resumed orchestrator reads it with the rest of the run state.
   A checkpoint that reopens a terminated run may also patch the top-level `phase_status`, `active`, `run_outcome`, and `blocked_reason`, which are otherwise owned by the terminal transition. Reopening means `phase_status` `running`, `active` true, and no stale `run_outcome` or `blocked_reason`; the amendment that justifies it belongs in the same patch, and the journal record says which outcome the run is being reopened from.
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
  "node_id": "<node-id>",
  "details": {
    "command": "research-loop-checkpoint",
    "changed_sections": ["orchestrator", "work"]
  }
}
```

`node_id` is optional: set it when the record concerns one node, omit it otherwise.

6. Write the complete updated `loop-state.json` and verify that it parses and contains the same `last_transition_id` as the journal record.
7. Return the checkpoint path, transition ID, changed sections, and next action. Do not paste full reports into the checkpoint.

</Workflow>

<Safety>
Only the main orchestrator writes checkpoints. Workers return evidence and suggested patches; they do not overwrite shared state. If the state changed after step 1, reread it and rebuild the patch rather than overwriting newer work. If the state or journal is malformed, stop and report the repair needed.
</Safety>
