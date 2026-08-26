---
name: create-contract
description: Draft and write a standalone AI Scientist research_contract JSON artifact for later ideation or research-loop use. Explicit-only; do not start any loop.
---

# Create Contract

<Use_When>
Use this skill ONLY when the user explicitly asks to create, draft, prepare, repair, or write an AI Scientist research contract before a later ideation or research-loop run.
</Use_When>

<Do_Not_Use_When>
- The user asks to start ideation.
- The user asks to start the research loop.
- The user asks to resume, checkpoint, complete, or otherwise operate an active AI Scientist loop.
- The task is to prepare a full ideation-start or research-start payload instead of a standalone `research_contract`.
</Do_Not_Use_When>

<Purpose>
Create one clean, reviewable contract artifact:

`.ai-scientist/contracts/<contract-id>/research-contract.json`

The artifact is for later use by ideation or research-loop. This skill does not start ideation, does not start research-loop, does not create loop state, does not spawn agents, and does not prepare full run payloads.
</Purpose>

<Output_Boundary>
By default, write only this file:

`.ai-scientist/contracts/<contract-id>/research-contract.json`

Do not write any other file unless the user explicitly gives another output path. In particular, do not write:

- `.ai-scientist/active-run.json`
- `.ai-scientist/runs/<run-id>/config.json`
- `.ai-scientist/runs/<run-id>/loop-state.json`
- `.ai-scientist/runs/<run-id>/journal.jsonl`
- notes, pending work, agent assignments, or loop logs

Do not call `ideation start`, `research start`, `resume`, `checkpoint`, `complete`, `cancel`, or any command that changes loop state.
</Output_Boundary>

<Contract_Shape>
Write JSON with exactly this top-level shape unless the user explicitly requests a compatible superset:

```json
{
  "research_contract": {
    "goal_type": "performance",
    "primary_hypothesis": "",
    "dataset": {},
    "split_protocol": "",
    "allowed_inputs": [],
    "forbidden_inputs": [],
    "metrics": {
      "primary": "",
      "secondary": []
    },
    "metrics_that_matter": [],
    "non_negotiable_comparisons": [],
    "baseline_reference": {},
    "benchmark_plan": "",
    "evaluator_command": "",
    "success_criteria": "",
    "failure_criteria": "",
    "kill_criteria": [],
    "target_threshold": "",
    "non_drift_definition": ""
  }
}
```
</Contract_Shape>

<Drafting_Rules>
Use only scientific and evaluation details supplied by the user or directly implied by the benchmark contract. Do not paste the user's original prompt, conversational context, runtime instructions, system instructions, developer instructions, AGENTS.md content, or agent assignment text into `research_contract`.

If a required scientific or evaluation field is unknown, ask the user or write an explicit placeholder that cannot be mistaken for a final contract, such as `TODO: specify dataset`. Do not invent dataset, split protocol, allowed or forbidden inputs, baseline, metric, threshold, evaluator command, success criteria, or failure criteria.

Keep `failure_criteria` limited to what the user specified or what is directly implied by the benchmark contract. Do not add broad failure modes, convenience exits, or extra acceptance rules.

The contract should be concise, machine-readable, and CLI-friendly. Prefer strings, arrays, and small objects over long prose. Use stable identifiers for datasets, splits, baselines, metrics, and evaluator commands when the user provides them.
</Drafting_Rules>

<Procedure>
1. Choose `contract-id` from the user's supplied id. If none is supplied, derive a short filesystem-safe id from the research topic.
2. Draft the `research_contract` fields from the user's scientific objective and evaluation constraints.
3. Mark unknown required fields with explicit `TODO:` placeholders rather than guessing.
4. Check that no contamination keys are present.
5. Write `.ai-scientist/contracts/<contract-id>/research-contract.json` unless the user explicitly requested another path.
6. Report the path and any remaining `TODO:` placeholders. Do not start ideation or research-loop.
</Procedure>
