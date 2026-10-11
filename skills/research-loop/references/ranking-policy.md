# Ranking Policy

Use the ranker only when a comparable recent cohort must compete for scarce
follow-up capacity. It allocates slots; it does not validate evidence, judge
success, alter the contract, critique workers, or write worker instructions.
Default to selecting `N = 3`; select fewer only when the active-node cap or
frozen resource policy cannot support three follow-up slots.

- Preserve the best valid measured result as the champion, but champion status
  does not automatically grant another slot.
- Build the cohort from expandable nodes near the top of `ai-scientist research
  frontier`.
- Honor the active-node cap.

Pass direct code, parent, experiment, metric, and failure refs plus requested
top `N`. Persist the cohort, selected nodes, ranking result ref, and rationale.
Give selected workers measured research context, not ranker prose.
