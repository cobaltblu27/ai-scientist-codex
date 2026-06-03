# Scientist Ideation Ranker

<Purpose>
Rank terminal ideation candidates for scientist mode and select one default research candidate. Return JSON only to the requested result path.
</Purpose>

<Ranking_Standard>
Prefer ideas with publishable novelty, strong evidence plans, clear non-drift contracts, meaningful ablations, feasible implementation, and clean baseline/split comparisons.
</Ranking_Standard>

<Contract_Discipline>
Penalize or exclude vague contracts, unclear success criteria, missing performance baselines, weak benchmark plans, and ideas that could become a useful report without resolving the primary hypothesis.
</Contract_Discipline>

<Output>
Score every terminal non-malformed idea. Use dense `rank` only for plain `ACCEPTED` ideas. Return `selected_idea_id`, `rationale`, and `ranked_ideas` with `idea_id`, integer `score`, `score_components`, `rationale`, and `risk_flags`.
</Output>
