# Performance-Campaign Ideation And Research Loop

## Summary

Convert the workflow from "select one idea, then research it" into a run-owned performance campaign. Ideation starts from a fixed `research_contract` and produces multiple accepted ideas under that contract. Research starts from the full idea batch, creates one initial node per idea, learns globally across nodes, and eventually selects one accepted final node.

## Public Interface Changes

- Extend `ideation start` to accept `--json/--json-file` payloads containing a required top-level `research_contract`.
- Keep `--prompt` as the human topic/context, but make the binding benchmark goal come from `research_contract`.
- Change ideation completion/handoff so `ideation_to_research` requires a valid run-owned `research_contract`, at least `min_candidates` accepted ideas, no pending generator/critic intents, and no ranking requirement.
- Keep `ideation rank-candidates` and `rank-finalize` available only as legacy/manual commands, but remove them from normal prompts, cursor flow, completion gates, and Stop-hook requirements.
- Change `research start` so `--selected-idea-id` is optional. Require either a new campaign payload with `research_contract` plus `idea_batch`, or a legacy payload with `selected_idea` plus optional `--selected-idea-id`.

## Implementation Changes

- Store `research_contract` at run/config level, not inside each idea.
- Stop requiring `research_contract` in generated idea drafts.
- Accepted ideas must instead include fields like `hypothesis`, `mechanism`, `implementation_sketch`, `expected_metric_effect`, `fit_to_research_contract`, `novelty_angle`, and `risks`.
- Enforce performance-only campaign contracts with required hard fields: `goal_type: performance`, fixed dataset, fixed split/protocol, fixed baseline, metric(s), evaluator command, success criteria, target threshold, and non-drift definition.
- Update generator prompts to consume the shared contract and create distinct model-improvement ideas under it.
- Update critic prompts to reject ideas that change dataset, split, metric, baseline, evaluator, or goal.
- Keep scientist mode paper-worthy: prefer novelty and big-picture finding potential, but do not require each individual idea to already be a complete paper claim.
- Remove ranker from `skills/ideation/SKILL.md` normal flow.
- Update `ideation_to_research` validator and completion audit to check accepted idea batch instead of final ranking.
- Update Stop-hook completion evaluation to allow ideation completion without ranking when batch handoff is ready.
- Freeze `research_contract`, `idea_batch`, mode, resource policy, and `learning_notes_ref` in research config.
- Initialize research state with an empty node forest plus enough metadata for the orchestrator to create one initial node per idea.
- Keep baseline unit code, but do not require or trigger it when the contract already provides fixed dataset, split, baseline, and evaluator.
- Update research-loop skill and worker prompt so each initial node gets one idea seed plus the shared contract.
- Allow cross-node insight transfer by recording fields such as `borrowed_from_node_id`, `insight_ref`, and `branch_reason` on branched or revised nodes.
- Add global learning notes as a canonical artifact, preferably `.ai-scientist/runs/<run-id>/learning-notes.jsonl`.
- Pass learning notes to workers, critics, and revision workers as advisory context, not as a constraint.
- Expand critic verdicts to include `ACCEPT_FINAL`, `PROMISING_CONTINUE`, `NEEDS_SCIENTIFIC_FRAMING`, `REVISE`, `KILL`, and `INVALID`.
- Treat high-performing but not paper-worthy nodes as `PROMISING_CONTINUE` or `NEEDS_SCIENTIFIC_FRAMING`, not `KILL`.
- Reserve `KILL` for contract violation, weak evidence, exhausted paths, or clearly bad performance.
- Add or revive queue state under research loop state for runnable benchmark/experiment work.
- Let the queue manage capacity and runnable order while the orchestrator keeps scientific priority ownership.
- Workers run only after the orchestrator marks queued work released/approved.

## Test Plan

- `ideation start` freezes run-owned `research_contract`.
- Generated ideas persist without per-idea `research_contract`.
- Accepted idea without `fit_to_research_contract` is blocked.
- Idea that changes dataset, split, baseline, metric, or evaluator is blocked.
- Ideation completion succeeds without ranking when an accepted batch exists.
- Legacy rank commands still validate/manual-record when called directly.
- `ideation_to_research` passes with contract plus accepted idea batch plus approved handoff.
- `ideation_to_research` fails when contract is missing, no accepted ideas exist, or pending intents remain.
- Stop hook allows completed ideation without `selected_idea_id`.
- `research start` accepts `idea_batch` and freezes it into config.
- Legacy single selected idea start still works.
- Initial research state can record multiple nodes seeded from different ideas.
- `research select` still finalizes exactly one accepted node.
- `research_to_review` validation no longer requires `selected_idea_id` for campaign runs.
- Ideation prompts mention fixed contract and no ranking.
- Research worker, critic, and revision prompts mention shared contract, node seed idea, and learning notes.
- Critic prompts include the new non-terminal positive verdicts.

## Assumptions

- Keep the name `idea`; do not rename to direction or strategy.
- Keep `ideation_to_research`, but redefine it as "contract plus accepted idea batch is safe for research."
- Keep old single-idea research start as compatibility, but make campaign batch mode the normal path.
- Do not delete baseline unit; simply avoid using it when the fixed contract already supplies baseline, split, and evaluator.
- Scope is ideation plus research-loop orchestration/contracts/prompts/state. Review/writeup changes are limited to compatibility with the new final selected node.
