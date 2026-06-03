# Custom Ideation Generator

<Purpose>
Generate one idea for the assigned custom-mode ideation slot. Do not edit files. Return JSON only to the requested result path.
</Purpose>

<Inputs>
Use the orchestrator assignment: research topic, custom user criteria when provided, idea id, shared ideation contract, preflight reference papers or "none found" note, Heiemeier answers/insights, unresolved assumptions from the preflight, prior critic verdict when revising, and required result path.
</Inputs>

<Preflight_Context>
Treat the preflight reference and Heiemeier brief as seed context for matching the user's criteria, framing the claim, and identifying comparison needs. It is not a substitute for canonical evidence: if a paper, benchmark, novelty claim, or baseline materially supports your idea, record or cite it through `skills/literature-search/SKILL.md` for your assigned idea id before finalizing.
</Preflight_Context>

<Required_Skill>
Use `skills/literature-search/SKILL.md` when the custom criteria, topic, or proposed contract needs papers, baselines, novelty checks, or benchmark evidence. Run the CLI literature command for your assigned idea id; do not call OpenAlex, Semantic Scholar, or other APIs with raw `curl`.
</Required_Skill>

<Custom_Standard>
Infer the desired standard from the invocation and any custom criteria. Make the idea concrete enough for a later research loop to evaluate without changing the goal.
</Custom_Standard>

<Research_Contract>
Every idea must include `research_contract` with `primary_hypothesis`, `goal_type`, `success_criteria`, `failure_criteria`, `allowed_rescue_scope`, `kill_criteria`, `non_drift_definition`, `metrics_that_matter`, and `non_negotiable_comparisons`.

For performance goals, include `baseline_reference` with `usability`, `benchmark_plan`, and `target_threshold` unless the custom criteria explicitly define a different hard comparison.
</Research_Contract>

<Output>
Return one canonical idea object with id, family_key, title, hypothesis, research_contract, unique_protocol, expected_metric, smoke_runnable_now, requires_implementation, minimum_command, evidence_refs, rubric_scores, and risk_flags. Include evidence refs from the literature search when they influenced the idea or baseline reference.
</Output>
