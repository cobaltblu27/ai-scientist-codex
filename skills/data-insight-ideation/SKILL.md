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
Do not merely think about the data. Reuse a valid existing ideation data-insight report only after checking freshness against the current run and contract. Otherwise inspect the repository and data interfaces, write the smallest task-specific inspection script that can answer the assigned insight questions, run it, keep its artifacts, and summarize only insights supported by those artifacts.
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
idea_seed_insights.json
figures/
data_insight_ideation_brief.md
```

When no run id exists, use the output directory given by the user or assignment. If none is provided and the task is outside an autonomous loop, ask before writing artifacts.
</Artifact_Location>

<Reuse_Rule>
Before writing new inspection code, check for existing artifacts in the ideation data-insight directory. Reuse them only when all of these are true:

- `idea_seed_insights.json` and `data_insight_ideation_brief.md` both exist;
- artifact refs named in `idea_seed_insights.json` still exist;
- the report matches the current `run_id`, research prompt or `research_contract`, dataset refs, split refs, evaluator refs, and benchmark assumptions;
- the report has no blocking `split_and_leakage_warnings` that make generator assignments invalid;
- the assignment does not explicitly request a fresh pass.

If any check fails, write and run a new `inspection.py`. If data access is missing or the environment is unclear, produce a blocker instead of fabricating insight. Outside autonomous loops, ask the user. Inside AI Scientist loops, record the blocker and continue according to the loop protocol.
</Reuse_Rule>

<Workflow>
1. Read workspace instructions and identify the correct Python launcher. Do not silently switch environments.
2. Check whether a valid existing report can be reused under the reuse rule.
3. If reusable, return the report refs and a compact generator note summary.
4. If not reusable, locate dataset loading, split definitions, schema docs, benchmark scripts, and evaluator commands from the repo and assignment.
5. Write `inspection.py` in the artifact directory. The script must be specific to the discovered dataset interfaces rather than a generic EDA framework.
6. Run `inspection.py` with the workspace Python launcher. Keep stdout/stderr or command notes when useful for auditability.
7. Read the generated JSON/figure/table artifacts.
8. Write `data_insight_ideation_brief.md` for humans and `idea_seed_insights.json` for downstream agents.
9. If an assigned `result_path` exists, write a final JSON result there that references the artifact paths.
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

<Insight_Output>
`idea_seed_insights.json` should use this shape:

```json
{
  "mode": "ideation",
  "source_context": {
    "run_id": "",
    "prompt_or_contract_ref": "",
    "dataset_refs": [],
    "split_refs": [],
    "evaluator_refs": [],
    "benchmark_assumptions": []
  },
  "artifact_refs": {
    "inspection_script": "...",
    "profile": "...",
    "split_audit": "...",
    "brief": "..."
  },
  "prediction_contract": {
    "unit": "",
    "target": "",
    "allowed_information": [],
    "split_policy": "",
    "metrics": [],
    "unknowns": []
  },
  "dataset_summary": {
    "n_examples": null,
    "modalities": [],
    "target_distribution": {},
    "notable_quality_issues": []
  },
  "split_and_leakage_warnings": [],
  "observed_data_bottlenecks": [],
  "slice_candidates": [
    {
      "name": "",
      "definition": "",
      "evidence_ref": "",
      "why_it_matters": ""
    }
  ],
  "promising_idea_seeds": [
    {
      "research_opportunity": "",
      "dataset_evidence": "",
      "baseline_requirement": "",
      "risk_to_avoid": ""
    }
  ],
  "directions_to_avoid": [],
  "required_baselines_or_checks": [],
  "confidence": "low|medium|high"
}
```
</Insight_Output>

<Brief_Format>
Write the Markdown brief in this order:

1. `Dataset Contract`: unit, target, allowed information, split, metric, unknowns.
2. `Inspection Code`: script path, command run, produced artifact refs.
3. `Dataset Findings`: only artifact-backed facts.
4. `Split And Leakage Risks`: pass/warn/fail style notes.
5. `Research Opportunities`: concrete idea seeds tied to dataset evidence.
6. `Directions To Avoid`: ideas likely to be invalid, saturated, or unsupported.
7. `Generator Assignment Notes`: compact bullets that the ideation orchestrator can paste into generator prompts.
</Brief_Format>

<Final_Response>
When invoked directly, report the artifact paths, the strongest supported ideation insights, and any blocker. When invoked by an orchestrator with `result_path`, write JSON only to that path and keep prose minimal in the conversation.
</Final_Response>
