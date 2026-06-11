---
name: data-insight-revision
description: Required AI Scientist helper for research-loop revision diagnostics. Use for every research-loop revision decision before choosing revise_same_node, branch_from_node, abandon_or_reject, or escalate. It creates a fresh artifact-backed data/model failure analysis for the current node scenario, including failed or partial node evidence, critic feedback, surprising benchmark results, slice regressions, baseline disagreement, suspected label noise, distribution shift, shortcut learning, implementation-bug signals, or unclear data-related failure causes. Do not use as a final critic or as pre-ideation dataset profiling.
---

# Data Insight Revision

<Purpose>
Create a bounded, reproducible data-inspection pass for research-loop revision decisions. The output should explain observed node failures or partial successes with artifact-backed evidence and recommend one revision action.
</Purpose>

<Use_When>
- This skill is explicitly called by the user, orchestrator, or revision worker.
- A research-loop revision worker is preparing any revise, branch, abandon/reject, or escalate plan.
- A research-loop node has evidence such as predictions, losses, evaluation logs, metric tables, dataset refs, split refs, critic feedback, or even a lack of expected artifacts that itself needs diagnosis.
</Use_When>

<Do_Not_Use_When>
- The task is pre-ideation dataset understanding; use `data-insight-ideation` instead.
- The task is final acceptance review; critics own final validity, leakage, and benchmark judgment.
- The user is asking a general question outside an AI Scientist research-loop revision context.
</Do_Not_Use_When>

<Inputs>
Expect some subset of:

- target repository path;
- research-loop `run_id`, `node_id`, and optional `work_id`;
- frozen run-owned `research_contract`, mode/custom criteria, split refs, and baseline refs;
- node seed idea, implementation notes, worker result refs, benchmark/evaluator command refs, resource records, and critic verdicts;
- prediction files, loss files, logs, metrics, error samples, model outputs, or baseline comparison artifacts;
- exact revision question;
- allowed Python launcher from workspace instructions;
- assigned `result_path` when called as a subagent.
</Inputs>

<Core_Rule>
Do not merely reason from summary metrics. For each revision decision, perform a fresh diagnostic pass for the current node scenario. First inspect the repository, node evidence, and data interfaces, then write the smallest task-specific inspection script that can answer the revision question. Run it, keep its artifacts, and recommend only actions supported by those artifacts. Prior data-insight reports may be cited as evidence but must not replace the fresh pass.
</Core_Rule>

<Artifact_Location>
When inside an AI Scientist research run, write artifacts under:

```text
.ai-scientist/runs/<run-id>/logs/data-insight/revision/<node-id>/<work-id>/
```

If `work_id` is unavailable, use a stable assignment id from the orchestrator. Use these names unless the assignment provides different paths:

```text
inspection.py
evidence_inventory.json
error_table.csv
slice_metrics.json
failure_patterns.json
revision_insights.json
figures/
data_insight_revision_brief.md
```

When no run id exists, use the output directory given by the user or assignment. If none is provided and the task is outside an autonomous loop, ask before writing artifacts.
</Artifact_Location>

<Workflow>
1. Read workspace instructions and identify the correct Python launcher. Do not silently switch environments.
2. Inventory node evidence, dataset/split refs, baseline refs, evaluator outputs, prediction files, and critic claims. Record missing evidence in `evidence_inventory.json`.
3. Write a fresh `inspection.py` in the artifact directory for this `work_id` or assignment. The script must be specific to the available evidence and dataset interfaces rather than a generic EDA framework.
4. Run `inspection.py` with the workspace Python launcher when enough artifacts exist to execute it. If executable inspection is impossible, write an explicit blocker in `evidence_inventory.json` and `revision_insights.json`; do not skip the data-insight step.
5. Read the generated JSON/table/figure artifacts.
6. Write `data_insight_revision_brief.md` for humans and `revision_insights.json` for downstream revision planning.
7. If an assigned `result_path` exists, write a final JSON result there that references artifact paths.
</Workflow>

<Inspection_Targets>
The inspection code should answer the relevant subset of these questions:

- Evidence integrity: which prediction, loss, metric, split, baseline, and dataset artifacts exist, and which needed artifacts are missing?
- Metric sanity: did the node improve globally, regress, fail, or produce inconclusive evidence under the frozen metric?
- Error table: which examples are high-loss, high-confidence wrong, false positive, false negative, baseline-only correct, candidate-only correct, or model-disagreement cases?
- Slice metrics: do errors concentrate by class, group, source, length, missingness, time, cluster, modality, feature range, or other reproducible slice?
- Baseline comparison: does the candidate fail where the baseline succeeds, succeed where the baseline fails, or merely shift errors?
- Data quality: are suspicious failures explained by wrong labels, ambiguous targets, conflicting duplicates, missing context, impossible values, or systematic missingness?
- Distribution and shortcut risk: is the node relying on source/device/time artifacts, train-only cues, leakage-like fields, or underrepresented groups?
- Revision decision: does evidence support revising the same node, branching from a better parent/insight, abandoning/rejecting, or escalating for contract/environment/data-access approval?
- Missing evidence: if predictions, losses, split refs, or evaluator outputs are absent, is the correct recommendation to generate missing evidence, fix an implementation/logging bug, abandon an unsupported direction, or escalate?
</Inspection_Targets>

<Boundaries>
- Do not mutate datasets, split files, benchmark code, evaluator behavior, model checkpoints, or node implementation.
- Do not inspect locked final test labels during revision.
- Do not rerun heavy training, tune architectures, or launch large sweeps.
- Do not change the frozen split, target, metric, baseline, resource policy, or acceptance criteria.
- Do not relabel data directly. Recommend label audit or adjudication only as an intervention.
- Do not add dependencies or change the Python/CUDA/PyTorch environment.
- Do not hide missing packages with broad fallback logic; fail fast according to workspace instructions.
- Do not recommend architecture changes unless the data evidence explains why that change targets the observed failure.
- Do not act as the final critic. This skill informs revision planning; critic review still gates accepted plans and outcomes.
</Boundaries>

<Insight_Output>
`revision_insights.json` should use this shape:

```json
{
  "mode": "revision",
  "run_id": "",
  "node_id": "",
  "work_id": "",
  "artifact_refs": {
    "inspection_script": "...",
    "evidence_inventory": "...",
    "error_table": "...",
    "slice_metrics": "...",
    "brief": "..."
  },
  "evidence_summary": {
    "available_refs": [],
    "missing_refs": [],
    "usable_for_revision": true
  },
  "failure_summary": "",
  "error_patterns": [],
  "slice_metrics": [
    {
      "name": "",
      "definition": "",
      "metric": "",
      "global_value": null,
      "slice_value": null,
      "gap": null,
      "evidence_ref": ""
    }
  ],
  "suspected_root_causes": [
    "label_noise|underrepresented_slice|distribution_shift|shortcut|missing_context|metric_mismatch|implementation_bug|insufficient_evidence|unknown"
  ],
  "recommended_action": "revise_same_node|branch_from_node|abandon_or_reject|escalate",
  "revision_hypothesis": "",
  "validation_plan": [],
  "risk_to_contract": [],
  "critic_questions": [],
  "confidence": "low|medium|high"
}
```
</Insight_Output>

<Brief_Format>
Write the Markdown brief in this order:

1. `Revision Question`: the exact decision being informed.
2. `Evidence Inventory`: usable refs and missing refs.
3. `Inspection Code`: script path, command run, produced artifact refs.
4. `Observed Failure Pattern`: artifact-backed facts only.
5. `Slice And Baseline Findings`: measurable gaps and comparison notes.
6. `Likely Root Cause`: evidence and uncertainty.
7. `Recommended Revision Action`: one of revise, branch, abandon/reject, or escalate.
8. `Validation Plan`: the smallest check that would confirm the revision hypothesis.
9. `Critic Questions`: what the revision-plan critic should scrutinize.
</Brief_Format>

<Revision_Brainstorm_Hand_Off>
Feed the compact result into `revision-brainstorm`. The handoff should include `revision_insights.json`, the brief path, the recommended action, the revision hypothesis, validation plan, contract risks, and critic questions. `revision-brainstorm` still owns the final revise/branch/abandon/escalate plan.
</Revision_Brainstorm_Hand_Off>

<Final_Response>
When invoked directly, report the artifact paths, the strongest supported failure insight, the recommended revision action, and any blocker. When invoked by an orchestrator with `result_path`, write JSON only to that path and keep prose minimal in the conversation.
</Final_Response>
