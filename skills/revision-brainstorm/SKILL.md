---
name: revision-brainstorm
description: Shared research-loop skill for revision workers that need to turn critic feedback, failed experiments, or partial node evidence into a bounded revise/branch/abandon/escalate plan.
---

# Revision Brainstorm

<Purpose>
Use this skill when acting as a research-loop revision worker. Your job is to propose a bounded next move after a node has failed, partially succeeded, drawn a critic revision request, or produced evidence that suggests a better branch.
</Purpose>

<Inputs>
Expect the orchestrator assignment to include the frozen selected idea, `research_contract`, mode/custom criteria, node evidence, critic verdicts, resource evidence, baseline split refs when present, and the exact revision question.
</Inputs>

<Protocol>
First return a revision plan unless the orchestrator explicitly assigned implementation.

Choose exactly one action:

- `revise_same_node`: fix or improve the current node without changing its research direction.
- `branch_from_node`: create a new node from any recorded parent node whose evidence makes it the best starting point.
- `abandon_or_reject`: stop the direction because evidence meets failure/kill criteria or the cost is not justified.
- `escalate`: ask the orchestrator or user for a decision because the next move changes reproducibility, benchmark meaning, data access, environment, or acceptance criteria.
</Protocol>

<Integrity_Rules>
Do not narrow the claim quietly, change the frozen split, hide negative evidence, rerun heavy jobs without a resource reason, or alter the benchmark to make a result look better. If a branch changes the research direction, say what changes and why it remains inside the frozen contract or why it needs approval.
</Integrity_Rules>

<Output>
Return structured JSON to the assigned result path when provided. Include `work_id`, `node_id`, `status`, `chosen_action`, `rationale`, `revision_plan`, `branch_parent_node_id` when relevant, `evidence_refs`, `resource_expectations`, `critic_questions`, and `blockers`.
</Output>
