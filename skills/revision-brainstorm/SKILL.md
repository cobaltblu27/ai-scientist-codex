---
name: revision-brainstorm
description: Shared research-loop skill for revision workers that need to turn critic feedback, failed experiments, or partial node evidence into a bounded revise/branch/abandon/escalate plan.
---

# Revision Brainstorm

<Purpose>
Use this skill when acting as a research-loop revision worker. Your job is to propose a bounded next move after a node has failed, partially succeeded, drawn a critic revision request, or produced evidence that suggests a better branch.
</Purpose>

<Inputs>
Expect the orchestrator assignment to include the node seed idea, frozen run-owned `research_contract`, mode/custom criteria, learning notes ref when present, node evidence, critic verdicts, resource evidence, baseline split refs when present, and the exact revision question.
</Inputs>

<Protocol>
First return a revision plan unless the orchestrator explicitly assigned implementation.

Before choosing the action, always use `skills/data-insight-revision/SKILL.md` for the current revision scenario. The data-insight pass must create a fresh evidence inventory and task-specific inspection code for this revision decision. If evidence is insufficient or the issue appears implementation/resource-related, the data-insight result should say that explicitly and recommend the appropriate revise, branch, abandon/reject, or escalate action.

Choose exactly one action:

- `revise_same_node`: fix or improve the current node without changing its research direction.
- `branch_from_node`: create a new node from any recorded parent node whose evidence makes it the best starting point. The branch may borrow a recorded insight from another node when it remains inside the frozen contract.
- `abandon_or_reject`: stop the direction because evidence meets failure/kill criteria or the cost is not justified.
- `escalate`: ask the orchestrator or user for a decision because the next move changes reproducibility, benchmark meaning, data access, environment, or acceptance criteria.

Branch aggressively when the data-insight evidence shows room for improvement that requires a changed approach, mechanism, objective, architecture, preprocessing strategy, data-slice strategy, or training protocol. Do not wait for same-node exhaustion before choosing `branch_from_node`. Use `revise_same_node` only when the same approach remains appropriate and needs a bounded fix, debug pass, ablation, or implementation correction.
</Protocol>

<Integrity_Rules>
Do not narrow the claim quietly, change the frozen split, hide negative evidence, rerun heavy jobs without a resource reason, or alter the benchmark to make a result look better. If a branch changes the research direction, say what changes and why it remains inside the frozen contract or why it needs approval.
</Integrity_Rules>

<Model_Improvement_Rule>
Residual, error, calibration, or output-correction analysis is diagnostic evidence, not the default intervention. Do not make the main revision a post-head residual corrector, calibration layer, or output patch unless the frozen contract or explicit orchestrator question allows post-processing as the target method.

Before proposing a rescue, compare where the current model works, where it fails, where residual/output correction helps, and where residual/output correction still fails or overfits. Use that contrast to name a model-side root-cause hypothesis such as representation bottleneck, missing conditioning signal, weak feature interaction, loss mismatch, label/slice noise, distribution shift, shortcut reliance, optimization issue, or architecture/inductive-bias mismatch.

The preferred revision must improve the model before or within the prediction head: encoder/backbone, feature interaction, conditioning, objective or auxiliary loss, data preprocessing, augmentation, sampling/reweighting, training schedule, architecture, or uncertainty modeling that changes training/model behavior. A residual corrector may be proposed only as a diagnostic baseline, ablation, or temporary measurement tool, and raw base-model metrics must be reported separately from corrected-output metrics.
</Model_Improvement_Rule>

<Output>
Return structured JSON to the assigned result path when provided. Include `work_id`, `node_id`, `status`, `chosen_action`, `rationale`, `revision_plan`, `branch_parent_node_id` when relevant, `borrowed_from_node_id` and `insight_ref` when relevant, `data_insight_refs`, `evidence_refs`, `resource_expectations`, `critic_questions`, and `blockers`.
</Output>
