# Research Loop Fix Plan

## Summary

The current research loop can produce an `accepted` node that is useful but not faithful to the original research goal. This creates false positives: a failed hypothesis can be reframed as a narrower success, and a weak model can be accepted because it merely beats baseline.

Fix the loop by adding a frozen research contract, mode-specific outcome semantics, stricter critic runtime enforcement, worker-owned repair, and validator gates that distinguish paper-worthy research from practical model engineering.

Core principle:

- `accepted` means critic-approved evidence.
- `outcome_type` states what was actually proven.
- Scientist/researcher acceptance requires truthful research conclusion against the original hypothesis.
- Builder/engineer acceptance requires a genuinely strong model, not just any baseline improvement.

## Research Contract And Outcomes

Add a frozen `research_contract` to each research run config.

For `scientist` and `researcher`, the contract is required at `research start` and must include:

- `primary_hypothesis`
- `success_criteria`
- `failure_criteria`
- `allowed_rescue_scope`
- `kill_criteria`
- `metrics_that_matter`
- `non_negotiable_comparisons`

For `builder` and `engineer`, the contract may exist but is not hard-required.

Keep node status values unchanged:

- `accepted`
- `invalid`
- `rejected`

Add accepted-node outcome fields:

- `outcome_type`: one of `hypothesis_supported`, `hypothesis_failed_with_evidence`, `rescue_finding_with_failed_hypothesis`, `practical_improvement`
- `current_claim`
- `claim_equivalence`
- `contract_evidence`
- `fundamental_failure_reason`
- `paper_worthiness`
- `strong_model_evidence`

Scientist/researcher accepted nodes must include outcome fields before critic start. The critic validates them instead of inventing them after the fact.

## Critic Runtime Enforcement

Freeze critic runtime config in `config.json`:

```json
{
  "research": {
    "critic_agent": {
      "model": "gpt-5.5",
      "reasoning_effort": "xhigh",
      "required": true
    }
  }
}
```

Update `node critic-start` to record and return:

- `required_model`
- `required_reasoning_effort`
- `critic_role`
- `rubric_snapshot`
- `evidence_fingerprint`
- `result_path`

Add a parent-side spawn record command:

```bash
node critic-spawn-record \
  --critic-id <critic-id> \
  --agent-id <agent-id> \
  --model gpt-5.5 \
  --reasoning-effort xhigh
```

Persist this metadata in loop state and critic logs.

`node critic-complete` must fail closed unless:

- critic result exists,
- result fingerprint is fresh,
- verdict is valid,
- parent-side spawn metadata exists,
- spawn model matches required model,
- spawn reasoning effort matches required effort.

This prevents medium-effort or untracked critics from approving final research output.

## Critic Roles

Scientist/researcher require two xhigh critics:

- `evidence_auditor`
- `claim_critic`

Builder/engineer require one xhigh critic:

- `performance_auditor`

Acceptance rules:

- Scientist/researcher: both required critic roles must `ACCEPT`.
- Builder/engineer: `performance_auditor` must `ACCEPT`.
- Any `REVISE` creates repair work.
- Any `INVALID` blocks trust.
- Any `REJECT` terminalizes the node with a reason.

## Required Critic Payload

Every critic must return structured JSON. `ACCEPT` is valid only when all required checks for that mode pass.

```json
{
  "verdict": "ACCEPT|REVISE|INVALID|REJECT",
  "mode": "engineer",
  "critic_role": "performance_auditor",
  "score": 0,
  "rationale": "...",
  "acceptance_checks": {
    "metric_contract_valid": true,
    "split_integrity_valid": true,
    "leakage_check_valid": true,
    "all_trials_accounted_for": true,
    "claim_matches_evidence": true,
    "mode_specific_bar_met": true,
    "cheap_improvements_remaining": false
  },
  "missed_opportunity_scan": {
    "searched": [
      "hyperparameters",
      "data cleaning",
      "architecture",
      "training schedule",
      "evaluation bugs"
    ],
    "actionable_improvements": [],
    "why_remaining_ideas_are_not_worth_running": "..."
  },
  "required_revisions": [],
  "risk_flags": []
}
```

If `verdict == ACCEPT`, validation must reject the critic payload when:

- required fields are missing,
- any required boolean is false,
- `cheap_improvements_remaining` is true,
- actionable improvements are listed,
- rationale is empty or only restates the node claim,
- the critic fails to address the frozen research contract in scientist/researcher modes.

## Mode-Specific Critic Gates

### Scientist

Accept only when the frozen research contract is resolved as one of:

- `hypothesis_supported`
- `hypothesis_failed_with_evidence`
- `rescue_finding_with_failed_hypothesis`

Required evidence:

- strict split/leakage discipline,
- reproducibility evidence,
- ablation or causal-link evidence,
- novelty evidence,
- limitations,
- all trials accounted for,
- claim equivalence or explicit rescue/negative labeling.

Useful but not paper-worthy evidence must be `REVISE` or `REJECT`, not `ACCEPT`.

### Researcher

Use the same contract discipline as scientist, with a slightly lighter reproducibility/ablation bar.

Required evidence:

- research-useful hypothesis resolution,
- meaningful validation or sensitivity evidence,
- clean split/leakage evidence,
- limitations,
- no quiet claim narrowing.

Promising partial progress remains `REVISE`.

### Balanced

Accept only when:

- baseline beat is credible,
- split/leakage checks pass,
- lightweight ablation or sensitivity evidence exists,
- risks are disclosed,
- no obvious cheap validation remains.

### Builder

Accept only when:

- artifact is runnable,
- baseline comparison is credible,
- rerun or verification trial confirms the result,
- integration notes and known risks exist,
- no straightforward build or reliability fix remains.

If a cheap integration/reliability improvement would likely improve usefulness, return `REVISE`.

### Engineer

Engineer is performance-first. It must reject weak or merely incremental results.

Add frozen config under `selection.performance_bar`:

- `min_improvement_margin`
- `min_confirmation_trials`
- `tuning_budget_policy`: `plateau_or_exhausted`
- `cheap_improvement_definition`

Engineer `ACCEPT` requires:

- selected score beats baseline by configured margin,
- confirmation trial reproduces the improvement,
- all successful and failed trials are accounted for,
- tuning/search budget is exhausted or plateau evidence exists,
- critic finds no cheap actionable improvement left.

The xhigh critic must actively search for missed methods that other subagents may have skipped:

- hyperparameters,
- random seeds,
- data preprocessing,
- model capacity,
- architecture variants,
- training schedule,
- loss/objective changes,
- regularization,
- inference-time tricks,
- evaluation bugs,
- leakage edge cases.

If the critic identifies a low-risk bounded improvement that fits current budget/resources, it must return `REVISE` with that experiment in `required_revisions`, even if the current score meets the numeric threshold.

## Worker-Owned Repair

Prevent the orchestrator from becoming both author and judge.

`REVISE`, `buggy`, and `repairing` states require worker continuation.

Worker continuation is mandatory until the node reaches one of:

- `accepted`
- `rejected`
- `invalid`
- blocked by a real environment, permission, dependency, reproducibility, resource, or user-decision blocker

The orchestrator must not stop at "partial progress" or repair a scientific node itself. If a worker returns with unresolved required revisions and no real blocker, the orchestrator must reassign the same node to a worker with the remaining revisions, relevant logs, and prior repair payloads.

Flow:

1. Critic returns `REVISE`, or command/evidence fails.
2. Node state becomes `repairing`.
3. CLI creates a repair assignment:

```json
{
  "node_id": "node-006",
  "status": "repairing",
  "repair_id": "repair-node-006-001",
  "critic_ref": "...",
  "required_revisions": [],
  "result_path": "logs/pending/repairs/repair-node-006-001.json"
}
```

4. Orchestrator spawns a worker for that node.
5. Worker edits only the node workspace and writes a repair payload:

```json
{
  "repair_id": "repair-node-006-001",
  "node_id": "node-006",
  "files_changed": [],
  "commands_run": [],
  "fixed_revisions": [],
  "remaining_risks": [],
  "recommended_status": "candidate"
}
```

6. Orchestrator runs official `resource run`.
7. Node transitions back to `candidate`.
8. Fresh xhigh critic reviews the updated node.

Disallow orchestrator edits to:

- experiment scripts,
- metrics/evidence generation,
- benchmark logic,
- leakage-check logic,
- scientific claims.

Allowed orchestrator edits:

- state files through CLI,
- selection finalization,
- validator/handoff records,
- non-scientific compatibility metadata only when explicitly logged.

Admin-only metadata patches must record:

```json
{
  "orchestrator_patch": true,
  "reason": "schema compatibility only",
  "requires_fresh_critic": true
}
```

Any orchestrator patch after critic review invalidates the critic fingerprint and requires fresh critic review.

## Selection And Validation

Selection is separate from acceptance.

`selection finalize` must include:

- selected node,
- selected `outcome_type`,
- metric key,
- metric direction,
- baseline metric,
- selected metric,
- ranked accepted nodes,
- rejected or superseded alternatives,
- rationale for why selected node is strongest.

Validation must fail when:

- selected node lacks required critic roles,
- critic runtime is missing or wrong,
- critic evidence fingerprint is stale,
- accepted node has unresolved repair,
- selected node has unaccounted failed trials,
- `metric_direction` is missing,
- outcome type is missing,
- scientist/researcher claim does not match the frozen contract,
- builder/engineer result is not a strong model.

Outcome-specific rules:

- `hypothesis_supported`: must beat baseline and satisfy success criteria.
- `hypothesis_failed_with_evidence`: may pass without beating baseline only when contract failure criteria are met and the critic marks `fundamental_failure: true`.
- `rescue_finding_with_failed_hypothesis`: may pass only when original hypothesis failure is explicit and rescue scope is allowed.
- `practical_improvement`: must beat baseline by the configured margin and pass mode-specific strength checks.

Routine failed tuning must never count as `hypothesis_failed_with_evidence`.

Failed-hypothesis completion is an allowed successful research-loop ending for scientist/researcher only when it is evidence-backed:

- selected node remains `accepted`,
- selected node `outcome_type` is `hypothesis_failed_with_evidence`,
- original hypothesis verdict is explicit,
- frozen contract failure criteria are satisfied,
- critic marks `fundamental_failure: true`,
- selection rationale states that the loop is ending with a negative research result, not an optimization failure or narrowed success claim.

If the hypothesis is merely unproven, weakly tested, or failed because a local implementation/tuning attempt was poor, the loop must continue, revise, reject the node, or end blocked/failed with reason. It must not produce an accepted failed-hypothesis outcome.

## Tests

Add tests for critic runtime:

- `critic-start` emits required xhigh/gpt-5.5 runtime.
- `critic-complete` fails without spawn metadata.
- `critic-complete` fails with wrong model.
- `critic-complete` fails with wrong reasoning effort.

Add tests for critic schema:

- `ACCEPT` without required rubric fields fails.
- `ACCEPT` with `cheap_improvements_remaining: true` fails.
- `REVISE` without required revisions fails.
- stale evidence fingerprint fails.

Add tests for scientist/researcher:

- supported hypothesis passes only with contract success evidence.
- useful narrowed result fails as success.
- rescue result passes only when original hypothesis failure and allowed rescue scope are explicit.
- solid negative result passes only with fundamental failure evidence.
- ordinary failed tuning cannot become a negative research result.
- research can complete with `hypothesis_failed_with_evidence` without beating baseline only when contract failure evidence is strong.
- inconclusive or weakly tested hypothesis failure blocks completion.

Add tests for builder/engineer:

- weak baseline beat fails.
- configured margin plus confirmation trial passes.
- missing confirmation trial fails.
- visible cheap improvement forces `REVISE`.
- budget plateau/exhaustion with no cheap improvement allows `ACCEPT`.

Add tests for repair ownership:

- `REVISE` creates repair assignment and sets `next_action = node_repair`.
- candidate transition after `REVISE` fails without worker repair payload.
- repair payload plus fresh resource run allows candidate.
- fresh critic is required after repair.
- orchestrator scientific patch blocks validation.
- admin metadata patch requires fresh critic.

Add tests for selection:

- accepted node missing one required critic role cannot be selected.
- selected metric direction is preserved.
- selection with unranked accepted nodes fails.
- selected accepted node with unaccounted failed trials fails.
- selected node with wrong outcome type for evidence fails.

## Implementation Targets

Primary files to update:

- `plugins/ai-scientist/scripts/ai_scientist_state_cli.py`
- `plugins/ai-scientist/scripts/ai_scientist_state.py`
- `plugins/ai-scientist/scripts/validate_run.py`
- `plugins/ai-scientist/schemas/node.schema.json`
- `plugins/ai-scientist/schemas/config.schema.json`
- `plugins/ai-scientist/schemas/research-plan.schema.json`
- `plugins/ai-scientist/skills/research-loop/SKILL.md`
- `plugins/ai-scientist/tests/test_research_loop_v1.py`

Secondary files to inspect and update if needed:

- `plugins/ai-scientist/scripts/research_loop/criteria.py`
- `plugins/ai-scientist/scripts/research_loop/prompts.py`
- `plugins/ai-scientist/tests/test_research_orchestrator_e2e.py`

## Assumptions

- Use `outcome_type`, not new terminal statuses.
- All research critics use `gpt-5.5` with `xhigh`.
- Workers may use default or cheaper settings.
- Scientist/researcher require full research contract and two critic roles.
- Builder/engineer require strong-model evidence, confirmation trial, and no cheap improvement remaining.
- Frozen config provides numeric thresholds; critics still keep the loop going if they identify actionable improvement within budget.
