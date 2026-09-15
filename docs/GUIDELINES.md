# AI Scientist Plugin Guidelines

These guidelines define how to maintain and use this plugin safely. They apply to plugin files in this repository and to any target repository artifacts created by the plugin.

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
8. Treat `ai-scientist validate run` as the fail-closed validation spine for phase gates.

## Scientific integrity rules

All modes must preserve these invariants:

- No train/test leakage.
- No benchmark or split manipulation unless the benchmark explicitly defines that setup.
- No metric deception, cherry-picked reporting, or unsupported novelty claims.
- No accepted score without command logs and evidence artifacts.
- No final positive writeup when verifier decision is `no_go` or blockers are present.

A run may add its own acceptance criteria, but none may weaken leakage, split, or evidence-trail requirements.

## Artifact requirements

A valid run should include:

- `.ai-scientist/contracts/<contract-id>/research-contract.json`
- `.ai-scientist/runs/<run-id>/contract.json`
- `.ai-scientist/runs/<run-id>/run.md`
- `.ai-scientist/runs/<run-id>/ideas.json`
- `.ai-scientist/runs/<run-id>/ideas/<idea-id>.md`
- `.ai-scientist/runs/<run-id>/logs/pilots/<idea-id>/report.md`
- `.ai-scientist/active-run.json`
- `.ai-scientist/runs/<run-id>/config.json`
- `.ai-scientist/runs/<run-id>/loop-state.json`
- `.ai-scientist/runs/<run-id>/journal.jsonl`
- `.ai-scientist/runs/<run-id>/selection.json`
- experiment node evidence: command logs, metrics, split integrity, leakage checks, result summaries, and mode deliverables.

If the artifact contract changes, update all of these together:

1. `docs/SCHEMA.md`
2. Relevant schema files in `src/validation/schemas/`
3. `src/validation/run.py`
4. Skill instructions that mention the changed contract

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
uv run pytest -q
```

CI (`.github/workflows/ci.yml`) runs the same suite plus the frontend build, `uv build`, and a smoke test of the wheel installed into a fresh virtualenv.

## Releases

The CLI reaches users as a wheel attached to a GitHub release; the plugin reaches them through `claude plugin install` from git. To cut a release:

1. Bump `version` in `pyproject.toml`, `.claude-plugin/plugin.json`, and `.codex-plugin/plugin.json` (`<version>+codex.<timestamp>`) together; `tests/test_install.py` fails when they drift.
2. Update the wheel URL in the README install section to the new version.
3. Run `uv run pytest -q`, commit, then `git tag v<version> && git push origin main --tags`.
4. `.github/workflows/release.yml` builds the frontend, the wheel and the sdist, smoke-tests the wheel, and creates the GitHub release with both files attached. It refuses a tag that does not match the `pyproject.toml` version.
5. Users upgrade both halves: `git pull && ./install.sh` in their clone, or `claude plugin update ai-scientist@ai-scientist` plus the `uv tool install` line from the README.

## Documentation standards

- Keep README examples runnable from the repository root.
- Prefer explicit artifact paths over vague descriptions.
- Document limitations and negative-result behavior.
- Do not imply the plugin can produce a credible research claim unless the verifier evidence supports it.

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
