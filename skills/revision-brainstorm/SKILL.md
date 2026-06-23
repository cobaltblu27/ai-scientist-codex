---
name: revision-brainstorm
description: Shared research-loop skill for revision workers that need to turn critic feedback, failed experiments, or partial node evidence into multiple concrete revision or branch candidates, rank them, and recommend a bounded next move for orchestrator and critic review.
---

# Revision Brainstorm

<Purpose>
Use this skill when acting as a research-loop revision worker. Your job is to generate concrete next-move options after a node has failed, partially succeeded, drawn a critic revision request, or produced evidence that suggests a better branch. The report should rank options, recommend a primary next move, and name compatible options that could be scheduled together, but the orchestrator and critic own the scheduling/control decision.
</Purpose>

<Inputs>
Expect the orchestrator assignment to include the node seed idea, frozen run-owned `research_contract`, mode/custom criteria, learning notes ref when present, node evidence, critic verdicts, resource evidence, baseline split refs when present, and the exact revision question.
</Inputs>

<Protocol>
First return a revision brainstorm report unless the orchestrator explicitly assigned implementation.

Before generating options, always use `skills/data-insight-revision/SKILL.md` for the current revision scenario. The data-insight pass must create a fresh evidence inventory, task-specific inspection code, and a Markdown data-insight report for this revision decision. Treat that report as evidence for brainstorming, not as the final loop action.

Read `learning_notes_ref` when provided before generating candidates. Each serious candidate must cite which global learning note, discovery-note item, node result, critic verdict, or data-insight finding it uses, contradicts, or deliberately sets aside.

Write a bottleneck diagnosis before proposing next moves. The bottleneck diagnosis is required context, not a candidate lane. It should identify the suspected limiting factor, evidence for and against it, uncertainty, quick probes that would reduce uncertainty, and what branch families it makes plausible or implausible. If the evidence does not support a clear bottleneck, say what evidence is missing and prefer candidates that resolve that uncertainty without changing benchmark meaning.

Before generating enhance or branch candidates, use both `skills/literature-search/SKILL.md` and `skills/local-literature-search/SKILL.md` for a bottleneck-targeted literature/source scan. Run 1-3 targeted `research literature-search` queries for external approach families that could get past the diagnosed bottleneck, and search the target repo's local `papers/` corpus for curated local mechanisms, priors, baselines, reusable components, source-code hooks, limitations, and original PDF details. Use the results for motivation, mechanism ideas, split-safe priors, baselines, diagnostics, or implementation pieces, not as an exact end-to-end approach to copy as the research claim. It is allowed to download papers, clone source code, and borrow implementation components when useful; record paper/source refs, repository URL or commit when available, visible license/provenance, and any adaptation. If the external CLI, local corpus, or network is unavailable, report that explicitly in the literature/source scan section and make the candidate uncertainty higher rather than inventing citations.

Decompose the full method pipeline before forming candidates. Cover input data, labels/splits/evaluator, preprocessing and feature construction, external data or priors, model modules, representation/encoder pieces, interaction or fusion blocks, objective/loss, sampling/curriculum, training schedule, prediction head, inference, uncertainty/calibration, and evaluation slices. For each relevant stage, state what capability it must provide, evidence that it is working or failing, and whether the fix is a same-direction enhancement or a changed-approach branch.

Generate multiple concrete next-move candidates before recommending one:

- at least one `enhance_current` candidate that improves the current mechanism without changing its research direction;
- at least three `branch` candidates with distinct mechanism changes, not only different hyperparameters, weights, or gates.

Each candidate must use a compact plan shape: `Hypothesis`, `Plan`, `Validation`, `Decision Criteria`, and `Risks`. For branch candidates, include parent node, mechanism change, why it targets the bottleneck, implementation pieces, scientific claim if positive, and required critic questions. At least one branch candidate should be outside the current model family unless the frozen contract forbids that.

Use these action labels when classifying candidates and naming the primary recommendation:

- `revise_same_node`: fix or improve the current node without changing its research direction.
- `branch_from_node`: create a new node from any recorded parent node whose evidence makes it the best starting point. The branch may borrow a recorded insight from another node when it remains inside the frozen contract.
- `abandon_or_reject`: stop the direction because evidence meets failure/kill criteria or the cost is not justified.
- `escalate`: ask the orchestrator or user for a decision because the next move changes reproducibility, benchmark meaning, data access, environment, or acceptance criteria.

Rank branch candidates highly when the data-insight evidence shows room for improvement that requires a changed approach, mechanism, objective, architecture, preprocessing strategy, data-slice strategy, or training protocol. Do not wait for same-node exhaustion before recommending `branch_from_node`. Recommend `revise_same_node` only when the same approach remains appropriate and needs a bounded fix, debug pass, ablation, or implementation correction.

The recommendation is advisory. Do not present it as a final loop action, do not mark a node stopped, and do not create or schedule a branch yourself. The orchestrator chooses which option or compatible option bundle to schedule after critic review and portfolio/resource triage.
</Protocol>

<Enhance_Brainstorming_Guide>
Use enhance candidates for local improvements to the current mechanism. They should answer: "What part of the existing path can be made cleaner, stronger, or more reliable without changing the research direction?"

Form enhance candidates from the pipeline decomposition. Good enhance targets include data cleaning within the same dataset, preprocessing corrections, feature normalization, module wiring, interaction strength, objective weighting, sampling balance, regularization, training schedule, ablation-driven simplification, predictor-head capacity, or uncertainty reporting when those remain faithful to the current approach.

Do not let enhance candidates become generic metric tweaks. Each one must name the pipeline stage, the current mechanism being preserved, the specific local weakness, the smallest implementation change, the literature/source evidence that motivated or constrained it when applicable, and the validation that would prove the same mechanism improved. If the evidence says the limiting factor is missing information, insufficient data support, absent biological prior, distribution shift, or an unsupported representation, stop treating it as an enhance problem and convert it into a branch candidate.
</Enhance_Brainstorming_Guide>

<Branch_Brainstorming_Guide>
Use branch candidates for changed mechanisms, changed information sources, or changed assumptions inside the frozen contract. They should answer: "What different path could solve the real bottleneck if the current mechanism is not enough?"

Do not anchor branch formation only on previous failed tries. Start from the full pipeline decomposition and ask what each stage would need in an ideal successful system. A branch may target input representation, preprocessing, external data, priors, encoder/backbone, cross-entity interaction, objective/loss, sampling strategy, training protocol, prediction target, uncertainty model, or evaluation-slice specialization.

When a local failure reveals a deeper insufficiency, branch at the deeper cause. For example, if predictor-head optimization suggests datapoints are fundamentally insufficient, propose a branch that adds split-safe prior knowledge, external data, pretraining, pathway/target structure, multitask signal, or another information source instead of continuing to tune the head.

Use the external and local literature/source scans to widen the branch search like a strong PhD researcher would: look for adjacent problem formulations, priors used in related biomedical tasks, objectives that expose hidden supervision, representation choices that encode the missing structure, local-corpus limitations or future-work hooks, and source implementations that can reduce engineering risk. Each branch candidate must state: pipeline stage targeted, missing capability, new mechanism or information source, why the current lineage cannot supply it, split-safe data/prior integration plan, literature/source motivation, implementation pieces, and scientific claim if positive. Branches must be meaningfully distinct from each other; different weights, gates, thresholds, or head sizes are not separate branches unless they instantiate different mechanisms.
</Branch_Brainstorming_Guide>

<Integrity_Rules>
Do not narrow the claim quietly, change the frozen split, hide negative evidence, rerun heavy jobs without a resource reason, or alter the benchmark to make a result look better. If a branch changes the research direction, say what changes and why it remains inside the frozen contract or why it needs approval.
</Integrity_Rules>

<Model_Improvement_Rule>
Residual, error, calibration, or output-correction analysis is diagnostic evidence, not the default intervention. Do not make the main revision a post-head residual corrector, calibration layer, or output patch unless the frozen contract or explicit orchestrator question allows post-processing as the target method.

Before proposing a revision, compare where the current model works, where it fails, where residual/output correction helps, and where residual/output correction still fails or overfits. Use that contrast to name a model-side root-cause hypothesis such as representation bottleneck, missing conditioning signal, weak feature interaction, loss mismatch, label/slice noise, distribution shift, shortcut reliance, optimization issue, or architecture/inductive-bias mismatch.

The preferred revision must improve the model before or within the prediction head: encoder/backbone, feature interaction, conditioning, objective or auxiliary loss, data preprocessing, augmentation, sampling/reweighting, training schedule, architecture, or uncertainty modeling that changes training/model behavior. A residual corrector may be proposed only as a diagnostic baseline, ablation, or temporary measurement tool, and raw base-model metrics must be reported separately from corrected-output metrics.
</Model_Improvement_Rule>

<Output>
Write a Markdown brainstorm report to the assigned result path when provided.

Use this report structure:

1. `Header`: work id, node id, status, primary recommended action, recommended candidate id, parent node when relevant, borrowed insight when relevant, and blocker summary.
2. `Evidence Context`: data-insight report path, artifact refs, critic verdicts, resource evidence, and global learning/discovery notes used.
3. `Bottleneck Diagnosis`: suspected limiting factor, supporting evidence, contrary evidence, uncertainty, full-pipeline opportunity map, and probes that would reduce uncertainty.
4. `Literature And Source Scan`: external queries run, CLI evidence refs, local `papers/` query terms and tag filters, selected local paper ids/detail paths/metadata/PDF refs, key papers/source repos, borrowed implementation components if any, how evidence motivates candidates, and why no exact end-to-end approach is being copied as the claim.
5. `Enhance Candidates`: one or more same-direction options. For each candidate include candidate id, action label, pipeline stage, preserved mechanism, literature/source motivation when applicable, `Hypothesis`, `Plan`, `Validation`, `Decision Criteria`, and `Risks`.
6. `Branch Candidates`: at least three changed-approach options. For each candidate include candidate id, action label, parent node, pipeline stage, missing capability, mechanism change or new information source, literature/source motivation, `Hypothesis`, `Plan`, `Validation`, `Decision Criteria`, scientific claim if positive, and `Risks`.
7. `Ranking And Recommendation`: primary recommendation, compatible candidate bundle when useful, backup option, why branch or enhance is preferred now, and why lower-ranked options are lower priority.
8. `Validation And Critic Questions`: frozen split/evaluator policy, controls, ablations, official-evaluator policy, and questions the revision-plan critic should answer before implementation.
9. `Discovery Note Suggestions`: reusable lessons or branch seeds for the orchestrator to integrate.
</Output>
