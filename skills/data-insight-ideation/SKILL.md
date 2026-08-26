---
name: data-insight-ideation
description: Required AI Scientist helper for pre-ideation dataset inspection. Use when a user or active ideation orchestrator needs data-grounded insight before idea generation, especially when a concrete dataset, benchmark, split, target, or research contract exists and generators need artifact-backed dataset bottlenecks, leakage risks, slice candidates, baseline requirements, or research opportunity seeds. The skill may reuse a valid existing ideation data-insight report for the same run/contract; otherwise it must create and run inspection code. Do not use as a general EDA trigger or as a research-loop revision/error-analysis skill.
---

# Data Insight Ideation

<Purpose>
Create a bounded, reproducible data-inspection pass before idea generation. The output should help ideation agents propose better research ideas by grounding them in observed dataset structure, split risks, simple signals, and concrete bottlenecks.
</Purpose>

<Use_When>
- This skill is explicitly called by the user.
- An active AI Scientist ideation orchestrator calls this skill during required pre-generation synthesis.
- A concrete dataset, benchmark, split, target, or draft research contract is available and idea generators need data-grounded context.
</Use_When>

<Do_Not_Use_When>
- The task is research-loop revision after node evidence exists; use `data-insight-revision` instead.
- The task is final validity review; critics already own final leakage, benchmark, and evidence inspection.
- The user explicitly asks for paper-only ideation outside the AI Scientist serious AI/ML research flow.
</Do_Not_Use_When>

<Inputs>
Expect some subset of:

- target repository path;
- ideation `run_id` when inside `.ai-scientist/runs/<run-id>/`;
- research prompt or draft `research_contract`;
- dataset refs, split refs, schema/docs, evaluator command, or benchmark entrypoints;
- allowed Python launcher from workspace instructions;
- assigned `result_path` when called as a subagent.
</Inputs>

<Core_Rule>
Do not merely think about the data. Reuse a valid existing ideation data-insight report only after checking freshness against the current run and contract. When `discovery_notes_ref` exists, also check `Data Insight Work` for a substantially similar in-progress or completed dataset-insight question before starting duplicate inspection work. Otherwise inspect the repository and data interfaces, write the smallest task-specific inspection script that can answer the assigned insight questions, run it, keep its artifacts, and summarize only insights supported by those artifacts.
</Core_Rule>

<Artifact_Location>
When inside an AI Scientist ideation run, write artifacts under:

```text
.ai-scientist/runs/<run-id>/logs/data-insight/ideation/
```

Use these names unless the assignment provides different paths:

```text
inspection.py
profile.json
split_audit.json
figures/
data_insight_ideation_report.md
```

When no run id exists, use the output directory given by the user or assignment. If none is provided and the task is outside an autonomous loop, ask before writing artifacts.
</Artifact_Location>

<Reuse_Rule>
Before writing new inspection code, check for existing artifacts in the ideation data-insight directory. Reuse them only when all of these are true:

- `data_insight_ideation_report.md` exists;
- artifact refs named in the report still exist;
- the report matches the current `run_id`, research prompt or `research_contract`, dataset refs, split refs, evaluator refs, and benchmark assumptions;
- the report has no blocking `split_and_leakage_warnings` that make generator assignments invalid;
- the assignment does not explicitly request a fresh pass.

If any check fails, write and run a new `inspection.py`. If data access is missing or the environment is unclear, produce a blocker instead of fabricating insight. Outside autonomous loops, ask the user. Inside AI Scientist loops, record the blocker and continue according to the loop protocol.
</Reuse_Rule>

<Soft_Coordination>
`Data Insight Work` in `discovery-notes.md` is a natural-language coordination surface, not a hard lock. If an in-progress entry asks a close enough ideation data question over the same dataset/split/evaluator assumptions, avoid duplicate work and poll or wait briefly for the expected artifact path if generators depend on it. If a completed entry is close enough and fresh, reuse it. Start a new pass only when the question is materially different, the dataset/split/evaluator assumption changed, or the existing item is blocked, stale, or too broad.

When starting or finishing insight work, include a concise `Data Insight Work Note` with the question, artifact scope, expected artifact path or artifact refs, useful-for notes, and whether the item is in progress, completed, blocked, or stale.
</Soft_Coordination>

<Workflow>
1. Read workspace instructions and identify the correct Python launcher. Do not silently switch environments.
2. Check `discovery_notes_ref` when provided for close `Data Insight Work`, then check whether a valid existing report can be reused under the reuse rule.
3. If close in-progress work exists and generators depend on it, poll or wait briefly for its expected artifact path rather than duplicating it.
4. If reusable, return the report refs and a compact generator note summary.
5. If not reusable, locate dataset loading, split definitions, schema docs, benchmark scripts, and evaluator commands from the repo and assignment.
6. Write `inspection.py` in the artifact directory. The script must be specific to the discovered dataset interfaces rather than a generic EDA framework.
7. Run `inspection.py` with the workspace Python launcher. Keep stdout/stderr or command notes when useful for auditability.
8. Read the generated JSON/figure/table artifacts.
9. Write `data_insight_ideation_report.md` as the downstream generator context. Use sustained prose for dataset bottlenecks, leakage risks, and concrete idea seeds.
10. If an assigned `result_path` exists, write the Markdown report there.
</Workflow>

<Inspection_Targets>
The inspection code should answer the relevant subset of these questions:

- Prediction contract: what is one example, what is the target, what information is allowed at prediction time, what split policy and metric are implied?
- Dataset profile: row/example count, feature/modalities, target distribution, missingness, sparsity, duplicate or near-duplicate signals, impossible values, high-cardinality fields, and obvious outliers.
- Split audit: train/validation/test sizes, target distribution by split, duplicate overlap, group/source/time overlap, feature distribution shift, and suspicious fields that may leak labels or future information.
- Simple signal checks: cheap feature-target associations, majority or mean predictor floor, optional lightweight linear/tree probe only when dependencies are already available and the run budget allows it.
- Data quality: label ambiguity hints, conflicting duplicates, systematic missingness, source/device/time artifacts, underrepresented classes or groups.
- Ideation value: dataset bottlenecks, slice candidates, risks to avoid, baseline requirements, and research opportunities that are testable under the existing benchmark.
</Inspection_Targets>

<Boundaries>
- Do not mutate source datasets, benchmark code, split files, or evaluator behavior.
- Do not inspect locked final test labels during ideation.
- Do not train heavy models, tune architectures, or run large sweeps.
- Do not add dependencies or change the Python/CUDA/PyTorch environment.
- Do not hide missing packages with broad fallback logic; fail fast according to workspace instructions.
- Do not recommend changing the split, target, metric, or benchmark as if it were an ordinary idea. Flag those as contract risks requiring orchestrator/user approval.
- Do not present plots as evidence unless they produce a reproducible slice definition, metric, table, or artifact-backed observation.
</Boundaries>

<Report_Format>
Write the Markdown report in this order:

1. `Dataset Contract`: unit, target, allowed information, split, metric, unknowns.
2. `Inspection Code`: script path, command run, produced artifact refs.
3. `Dataset Findings`: only artifact-backed facts.
4. `Split And Leakage Risks`: pass/warn/fail style notes.
5. `Research Opportunities`: concrete idea seeds tied to dataset evidence.
6. `Directions To Avoid`: ideas likely to be invalid, saturated, or unsupported.
7. `Generator Assignment Notes`: compact bullets that the ideation orchestrator can paste into generator prompts.
8. `Data Insight Work Note`: suggested discovery-note update for in-progress, completed, blocked, or stale insight work.
</Report_Format>

<Final_Response>
When invoked directly, report the artifact paths, the strongest supported ideation insights, and any blocker. When invoked by an orchestrator with `result_path`, write the Markdown report to that path and keep conversation prose minimal.
</Final_Response>
