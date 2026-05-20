# AI Scientist Plugin Guidelines

These guidelines define how to maintain and use this plugin safely. They apply to changes under `plugins/ai-scientist/` and to any target repository artifacts created by the plugin.

## Product boundaries

1. Keep the plugin Codex-native: use skills, local artifacts, schemas, and deterministic validation.
2. Do not import, invoke, shell out to, wrap, vendor, or require an external reference implementation at runtime.
3. Ideation runs in the live Codex session through hooks and durable state. It must not launch nested Codex sessions for proposal/reflection/finalization.
4. Python may call Semantic Scholar directly during ideation. `S2_API_KEY` is optional, but every search/cache event must be logged.
5. Ideation outputs must be scientifically substantive: require an actual mechanism/insight, concrete related work, an executable plan, baseline/ablation design, risks, and minimum evidence before research execution.
6. Keep the public surface to exactly four primary skills unless a future version explicitly changes the product contract:
   - `ideation`
   - `research-loop`
   - `review`
   - `writeup`
7. Store run state in target repositories under `.ai-scientist/`.
8. Treat `plugins/ai-scientist/scripts/validate_run.py` as the fail-closed validation spine for phase gates.

## Scientific integrity rules

All modes must preserve these invariants:

- No train/test leakage.
- No benchmark or split manipulation unless the benchmark explicitly defines that setup.
- No metric deception, cherry-picked reporting, or unsupported novelty claims.
- No accepted score without command logs and evidence artifacts.
- No final positive writeup when verifier decision is `no_go` or blockers are present.

Strictness modes may differ in required evidence, but none may weaken leakage, split, or evidence-trail requirements.

## Artifact requirements

A valid run should include:

- `.ai-scientist/config.json`
- `.ai-scientist/ideas/ideas.json`
- `.ai-scientist/state/active-ideation.json`
- `.ai-scientist/runs/<run-id>/ideation-state.json`
- `.ai-scientist/runs/<run-id>/actions/*.json`
- `.ai-scientist/runs/<run-id>/drafts/*.json`
- `.ai-scientist/runs/<run-id>/reflections/*.md`
- `.ai-scientist/logs/<run-id>/ideation-run.json`
- `.ai-scientist/runs/<run-id>/semantic-scholar-cache/*.json`
- `.ai-scientist/runs/<run-id>/dependency-plan.json`
- `.ai-scientist/runs/<run-id>/api-ledger.jsonl`
- `.ai-scientist/runs/<run-id>/journal.json`
- `.ai-scientist/runs/<run-id>/run-status.json`
- `.ai-scientist/runs/<run-id>/handoff.jsonl`
- `.ai-scientist/runs/<run-id>/verifier-decision.json`
- `.ai-scientist/runs/<run-id>/principles.json`
- experiment node evidence: command logs, metrics, split integrity, leakage checks, result summaries, and mode deliverables.

If the artifact contract changes, update all of these together:

1. `plugins/ai-scientist/references/artifact-contract.md`
2. Relevant schema files in `plugins/ai-scientist/schemas/`
3. `plugins/ai-scientist/scripts/validate_run.py`
4. Positive and negative fixtures in `plugins/ai-scientist/tests/fixtures/`
5. Skill instructions that mention the changed contract

## Dependency and API policy

- Prepare a dependency plan before research execution.
- Mark every planned dependency as `approved`, `rejected`, or `not_needed`.
- Require user-supervised approval before installing dependencies.
- During a run, remember newly approved packages and do not repeatedly ask for the same package.
- Use `S2_API_KEY` only when configured and only within the declared phase budget.
- Log API calls or cache hits to `api-ledger.jsonl` where practical.

## Validation expectations

Before claiming a change is complete, run at minimum:

```bash
python3 -m json.tool plugins/ai-scientist/.codex-plugin/plugin.json >/dev/null
python3 -m json.tool plugins/ai-scientist/hooks.json >/dev/null
python3 -m unittest discover -s plugins/ai-scientist/tests -p 'test_*.py'
```

For gate changes, also run the relevant positive and negative fixtures. Negative fixtures must fail for the intended reason class.

## Documentation standards

- Keep README examples runnable from the repository root.
- Prefer explicit artifact paths over vague descriptions.
- Document limitations and negative-result behavior.
- Do not imply the plugin can produce a credible research claim unless the selected strictness mode and verifier evidence support it.

## Commit hygiene

Use Lore-format commit messages for repository changes:

```text
<intent line: why the change was made>

Constraint: <constraint that shaped the decision>
Rejected: <alternative> | <reason>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Directive: <future warning>
Tested: <commands/evidence>
Not-tested: <known gaps>
```
