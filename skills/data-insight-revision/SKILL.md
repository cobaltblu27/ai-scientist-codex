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
- frozen run-owned `research_contract`, split refs, and baseline refs;
- node seed idea, implementation notes, worker result refs, benchmark/evaluator command refs, resource records, and critic verdicts;
- prediction files, loss files, logs, metrics, error samples, model outputs, or baseline comparison artifacts;
- exact revision question;
- allowed Python launcher from workspace instructions;
- assigned `result_path` when called as a subagent.
</Inputs>

<Core_Rule>
Do not merely reason from summary metrics. For each revision decision, use artifact-backed diagnostic evidence for the current node scenario. Prefer a fresh diagnostic pass, but first check `discovery_notes_ref` when provided for `Data Insight Work`. If an in-progress entry is substantially similar over the same dataset/split, prediction files, metric outputs, and revision question, poll or wait briefly for its expected artifact path instead of duplicating it. If a completed entry is close enough and still matches the current evidence version, reuse it with explicit refs. Write a new task-specific inspection only when the question is materially different, the evidence changed, or the existing insight is stale, blocked, or too broad. Recommend only actions supported by the produced or reused artifacts.
</Core_Rule>

<Soft_Coordination>
`Data Insight Work` entries are natural-language coordination hints, not hard locks. Similar enough means the same dataset/split, same prediction or result artifacts, and the same decision question or failure mode. Different enough means a different node evidence version, different artifact version, different slice/failure hypothesis, or different decision need.

When coordination would help, include a short suggested `Data Insight Work` note describing the question, evidence scope, artifact location, status, and why it matters. Include only details that are known and useful for another agent deciding whether to reuse, poll, or start a different pass.
</Soft_Coordination>

<Model_Failure_Diagnosis>
When prediction files, residuals, logits, scores, losses, or per-example outputs are available, the inspection must compare success cases against failure cases. If a residual corrector, calibration layer, ensemble, or other output-level patch exists or is tempting, treat it as a diagnostic probe: record where it helps, where it fails, and whether it appears to overfit a slice.

Use that contrast to identify a model-side root-cause hypothesis. Prefer insights that can drive upstream changes to representation, conditioning, feature interaction, loss/objective, data preprocessing, augmentation, sampling/reweighting, training schedule, architecture, or uncertainty modeling that changes training/model behavior. Do not recommend "add a residual corrector after the prediction head" as the primary revision unless the frozen contract explicitly makes post-processing/calibration the target method.
</Model_Failure_Diagnosis>

<Artifact_Location>
When inside an AI Scientist research run, write artifacts under:

```text
.ai-scientist/runs/<run-id>/logs/data-insight/revision/<node-id>/<work-id>/
```

If `work_id` is unavailable, use a stable assignment id from the orchestrator. For a fresh inspection, keep the executable inspection and Markdown report in this directory. Add tables, JSON, or figures only when they materially support the diagnosis, using descriptive names.

When no run id exists, use the output directory given by the user or assignment. If none is provided and the task is outside an autonomous loop, ask before writing artifacts.
</Artifact_Location>

<Workflow>
1. Read workspace instructions and identify the correct Python launcher. Do not silently switch environments.
2. Read `discovery_notes_ref` when provided and inspect `Data Insight Work` for close in-progress, completed, blocked, or stale insight entries.
3. Inventory node evidence, dataset/split refs, baseline refs, evaluator outputs, prediction files, and critic claims. Record missing evidence in `evidence_inventory.json` when creating a new pass.
4. If close in-progress work exists and your decision depends on it, poll or wait briefly for its expected artifact path; otherwise return the pending ref or continue only if the assignment allows unrelated planning.
5. If close completed work exists and still matches the current evidence version, reuse it and write a compact result pointing to the existing artifacts.
6. If no close usable work exists, write a fresh `inspection.py` in the artifact directory for this `work_id` or assignment. The script must be specific to the available evidence and dataset interfaces rather than a generic EDA framework.
7. Run `inspection.py` with the workspace Python launcher when enough artifacts exist to execute it. If executable inspection is impossible, write an explicit blocker in `evidence_inventory.json` and the Markdown report; do not skip the data-insight step.
8. Read the generated or reused JSON/table/figure artifacts.
9. Write `data_insight_revision_report.md` as the downstream revision-planning artifact. Use sustained prose for failure explanation, root-cause hypotheses, and action recommendation.
10. If an assigned `result_path` exists, write the Markdown report there.
</Workflow>

<Inspection_Targets>
The inspection code should answer the relevant subset of these questions:

- Evidence integrity: which prediction, loss, metric, split, baseline, and dataset artifacts exist, and which needed artifacts are missing?
- Metric sanity: did the node improve globally, regress, fail, or produce inconclusive evidence under the frozen metric?
- Error table: which examples are high-loss, high-confidence wrong, false positive, false negative, baseline-only correct, candidate-only correct, or model-disagreement cases?
- Success/failure contrast: what distinguishes examples the current model gets right from examples it gets wrong, and which differences point to an upstream model/data/training issue?
- Output correction probe: if residual correction, calibration, ensembling, or post-head patching helps, which slices improve, which slices remain weak, and does the base model itself still fail?
- Slice metrics: do errors concentrate by class, group, source, length, missingness, time, cluster, modality, feature range, or other reproducible slice?
- Baseline comparison: does the candidate fail where the baseline succeeds, succeed where the baseline fails, or merely shift errors?
- Data quality: are suspicious failures explained by wrong labels, ambiguous targets, conflicting duplicates, missing context, impossible values, or systematic missingness?
- Distribution and shortcut risk: is the node relying on source/device/time artifacts, train-only cues, leakage-like fields, or underrepresented groups?
- Approach-change opportunities: does artifact-backed evidence show room for improvement that would require a different mechanism, objective, architecture, preprocessing strategy, data-slice strategy, or training protocol rather than another same-node fix?
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

<Report_Format>
Write a compact Markdown report that communicates:

- the question and evidence inspected;
- the important artifact-backed findings and uncertainty;
- the recommended revision action, why it follows from the findings, and the smallest useful validation;
- relevant artifact refs or blockers.

Choose headings, order, and depth to fit the evidence. Discuss slices, baseline contrasts, output correction, coordination notes, or critic questions only when they affect the recommendation.
</Report_Format>

<Revision_Brainstorm_Hand_Off>
Feed the Markdown report and relevant artifact refs into `revision-brainstorm`, together with the recommended action. Add a revision hypothesis, validation idea, contract risk, or critic question when it is important to the next decision. `revision-brainstorm` still owns final idea generation, ranking, and the revise/branch/abandon/escalate recommendation.
</Revision_Brainstorm_Hand_Off>

<Final_Response>
When invoked directly, report the artifact paths, the strongest supported failure insight, the recommended revision action, and any blocker. When invoked by an orchestrator with `result_path`, write the Markdown report to that path and keep conversation prose minimal.
</Final_Response>
