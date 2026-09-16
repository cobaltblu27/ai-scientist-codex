---
name: create-contract
description: Draft and write a standalone AI Scientist research_contract JSON artifact for later ideation or research-loop use. Explicit-only; do not start any loop.
disable-model-invocation: true
---

# Create Contract

<Purpose>
Create one clean, reviewable contract artifact:

`.ai-scientist/contracts/<contract-id>/research-contract.json`

Artifact shapes are defined in `docs/SCHEMA.md` (plugin repo); honor its required keys, everything else is free. The artifact is for later use by ideation or research-loop. This skill does not start ideation, does not start research-loop, does not create loop state, does not spawn agents, and does not prepare full run payloads.
</Purpose>

<Output>
By default, write a file:
`.ai-scientist/contracts/<contract-id>/research-contract.json`
</Output>

<Contract_Shape>
Write JSON that describes the goal, such as this schema:

```json
{
  "research_contract": {
    "dataset": {},
    "split_protocol": "",
    "allowed_inputs": [],
    "forbidden_inputs": [],
    "metrics": {
      "primary": "",
      "secondary": []
    },
    "goal": "",
    "related_works": [],
    "failure_criteria": "",
    "non_drift_definition": ""
  }
}
```
You may add change schema to your needing, such as adding "required_approach" field if user adds a approach criteria.
</Contract_Shape>

<Drafting_Rules>
Use only scientific and evaluation details supplied by the user or directly implied by the benchmark contract. Do not paste the user's original prompt, conversational context, runtime instructions, system instructions, developer instructions, AGENTS.md content, or agent assignment text into `research_contract`.

If a required scientific or evaluation field is unknown, ask the user to specify the goal. User may also give a guide to find a requirement on your own, from given published corpus. Do not invent dataset, split protocol, allowed or forbidden inputs, baseline, metric, threshold, evaluator command, success criteria, or failure criteria. You may add empty fields with `TODO:` for user to fill in.

Keep `failure_criteria` limited to what the user specified or what is directly implied by the benchmark contract. Do not add broad failure modes, convenience exits, or extra acceptance rules.
</Drafting_Rules>

<Procedure>
1. Choose `contract-id` from the user's supplied id. If none is supplied, derive a short filesystem-safe id from the research topic.
2. Draft the `research_contract` fields from the user's scientific objective and evaluation constraints.
3. Mark unknown required fields with explicit `TODO:` placeholders rather than guessing.
4. Check that no contamination keys are present.
5. Write `.ai-scientist/contracts/<contract-id>/research-contract.json` unless the user explicitly requested another path.
6. Report the path and any remaining `TODO:` placeholders. Do not start ideation or research-loop.
</Procedure>
