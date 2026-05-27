---
name: ideation
description: Generate structured research ideas from an inline prompt by running a Codex-native, Stop-hook-enforced ideation loop.
---

# Ideation

Use this skill when the user wants research ideas, hypotheses, or experiment proposals before running a research loop.

You are the ideation orchestrator. The current Codex session owns the loop. Python helper commands only create artifacts, validate state transitions, call/record Semantic Scholar when requested, and compute the next Stop-hook cursor. Do not run a Python loop, do not run nested `codex exec`, and do not run the retired `ideation_orchestrator.py`.

## Non-Negotiable Rules

1. Treat the invocation text as the research topic. Do not require a Markdown topic file.
2. Do not mutate target repository source code during ideation. The only target-repository writes are under `.ai-scientist/`.
3. Install/check the project-local Stop hook before starting a real run.
4. All state transitions go through `plugins/ai-scientist/scripts/ai_scientist_state_cli.py`.
5. Record a subagent intent before spawning a generator, critic, or ranker. A pending intent intentionally blocks Stop until you record completion or cancellation.
6. Spawn a separate idea-generation subagent for each substantive idea draft or revision. Use `gpt-5.5` with `xhigh` effort for substantive idea generation when model controls are available.
7. Spawn a fresh critic for each draft or revised draft. Include previous critic verdict/revision notes in the new critic prompt; do not reuse long critic context.
8. Spawn the ranker only after idea generation/reflection is done and at least one researchable candidate exists.
9. `ideation_to_research` means "safe for research to consume." It must not start the research loop. Research start is a separate explicit user action.
10. Do not report success while Stop hook would still block.

## Required Artifacts

All source-of-truth artifacts live under `.ai-scientist/runs/<run-id>/`:

- `config.json`: frozen ideation config, mode preset, prompt templates, and scoring policy.
- `loop-state.json`: active cursor, active idea, pending intent, terminal status, candidate/ranking state.
- `ideas.json`: canonical terminal idea archive.
- `journal.jsonl`: append-only audit stream.
- `logs/drafts/*.json`: versioned draft payloads.
- `logs/critics/*.json`: critic verdict payloads.
- `logs/semantic-scholar/*.json`: Semantic Scholar response payloads when used.
- `logs/ranking/ranking-final.json`: final ranking payload.

Root `.ai-scientist/active-run.json` points the Stop hook to the active run.

## Python Launcher

Command examples use `python` for portability. Treat it as a placeholder for the
Python launcher provided by the target environment: `uv run python`,
`conda run -n <env> python`, `micromamba run -n <env> python`, `python3`, or an
absolute interpreter path.

Use the launcher that can import and run the plugin helper scripts in the target
project. Do not assume this development server's `micromamba` layout exists on
other machines. If the target repo has `.venv`, `uv.lock`, `pyproject.toml`,
`environment.yml`, `conda` metadata, or project docs, follow that environment.
Do not silently switch Python launchers mid-run; if the right environment is
unclear and the command is required, ask or fail fast with a clear blocker.

## Strictness Modes

Default mode is `scientist`. Mode is frozen once `ideation start` runs.

- `scientist`: requires literature evidence for plain `ACCEPTED`; critic prioritizes novelty, ablation value, publication claim, leakage/split risk, and evidence quality.
- `researcher`: requires literature evidence for plain `ACCEPTED`; critic prioritizes research usefulness, evidence, ablation, and feasibility.
- `balanced`: literature search is expected, but `ACCEPTED_WITHOUT_REFERENCE` can be researchable if config allows it; critic balances research value and practical performance.
- `engineer`: Semantic Scholar is advisory only; critic prioritizes likely performance, implementation feasibility, and repo fit. Novelty is optional.
- `builder`: Semantic Scholar is advisory only; critic prioritizes pragmatic usefulness, buildability, expected performance, and risk. Novelty is optional.

Mode presets live in frozen `config.json`. Read them instead of hardcoding prompts if the config provides a template.

## Startup

From the target repository root, install/check the Stop hook:

```bash
python plugins/ai-scientist/scripts/install_codex_hooks.py --project-root <target-repo>
```

Start the run:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation start \
  --run-id <run-id> \
  --prompt "<research prompt>" \
  --strictness-mode scientist \
  --num-ideas 10
```

If `--strictness-mode` is omitted, default is `scientist`. If `--num-ideas` is omitted, default is 10 attempted slots. This is slot-based, not "10 accepted ideas."

Resume from state:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation resume --run-id <run-id> --prompt
```

Use the returned `next_action` and prompt text as the immediate loop cursor. Repeat resume after every major state transition.

## Cursor Actions

The helper computes `next_action`. Follow it exactly.

- `start_next_idea`: record generator intent, spawn one generator subagent, record draft result.
- `record_subagent_result`: a previous generator/critic/ranker intent is pending; record completion or cancellation before doing anything else.
- `search_semantic_scholar`: run/record Semantic Scholar evidence for the active idea.
- `spawn_critic`: record critic intent, spawn a fresh critic, record verdict.
- `revise_or_reject`: critic returned `REVISE` or `REJECT`; revise same idea thread or explicitly reject it.
- `finalize_idea`: call `idea finalize`; if deterministic gates refuse it, follow the returned error and resume.
- `rank_candidates`: record ranker intent, spawn ranking agent, record final ranking.
- `complete_or_exhaust`: call `ideation complete` if researchable candidate and ranking exist; otherwise call `ideation exhaust`.

## Subagent Protocol

Before spawning any subagent:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation intent start --run-id <run-id> --role generator
```

Use `--role critic --idea-id <idea-id>` for critics and `--role ranker` for ranking.

After the subagent returns, record output. Default input is inline JSON. Use `--path` only for oversized payloads.

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation intent complete --run-id <run-id> --json '<payload>'
```

If the subagent result is malformed or unusable, cancel the pending intent with a reason, then resume:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation intent cancel --run-id <run-id> --reason "malformed generator output"
```

Failed/cancelled attempts consume loop budget. Do not leave a pending intent unresolved.

## Generator Agent

Spawn exactly one generator for one idea slot or one substantive revision. The generator should not edit files. It returns one canonical idea object.

Generator prompt must include:

- research topic
- strictness mode
- current slot/idea id
- mode-specific generator prompt from `config.json` when available
- previous critic verdict and required revisions when this is a revision
- instruction to return JSON only

Canonical draft payload should include at least:

```json
{
  "id": "idea-001",
  "title": "Short title",
  "hypothesis": "Concrete hypothesis",
  "expected_metric": "Metric or benchmark target",
  "method": "Proposed method or implementation direction",
  "experiment_plan": ["Step 1", "Step 2"],
  "risks": ["Risk 1"],
  "novelty_rationale": "Required for scientist/researcher; optional for builder/engineer"
}
```

If using direct recording instead of `intent complete`:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  idea draft --run-id <run-id> --json '<canonical idea JSON>'
```

## Semantic Scholar

Use Semantic Scholar only when the cursor requests it or when the mode/prompt makes it useful. Scientist/researcher require literature evidence before plain `ACCEPTED`. Builder/engineer treat S2 as inspiration, not a gate.

Live query:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  idea search-semantic-scholar --run-id <run-id> --idea-id <idea-id> --query "<query>"
```

Precomputed evidence payload:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  idea search-semantic-scholar --run-id <run-id> --idea-id <idea-id> --json '<evidence JSON>'
```

All API evidence is logged to `journal.jsonl` as `api_call`.

## Critic Agent

Spawn a fresh critic for every draft version. The critic should not edit files. It returns a verdict payload.

Critic prompt must include:

- current canonical idea draft
- strictness mode and mode-specific critic prompt from frozen `config.json`
- evidence/search results if available
- previous critic verdict and required revisions if this is a revised draft
- instruction to return JSON only

Critic payload schema:

```json
{
  "verdict": "ACCEPT",
  "score": 82,
  "strengths": ["..."],
  "weaknesses": ["..."],
  "required_revisions": [],
  "mode_specific_assessment": {},
  "risk_flags": []
}
```

Allowed verdicts:

- `ACCEPT`: candidate may become plain `ACCEPTED` if deterministic gates pass.
- `ACCEPT_WITHOUT_REFERENCE`: allowed only by mode config; useful for builder/engineer or S2 failure cases.
- `REVISE`: do not finalize; either revise same idea thread or reject explicitly.
- `REJECT`: reject explicitly or revise if the orchestrator has a clear reason.

Record verdict:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  idea critic-record --run-id <run-id> --idea-id <idea-id> --json '<critic JSON>'
```

## Revision And Rejection

For `REVISE`, either keep the same idea thread:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  idea revise-start --run-id <run-id> --idea-id <idea-id> --reason "<revision reason>"
```

Then spawn a new generator for the revised draft.

Or abandon it explicitly:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  idea reject --run-id <run-id> --idea-id <idea-id> --reason "abandoned_after_revise"
```

For budget exhaustion on an active idea:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  idea exhaust --run-id <run-id> --idea-id <idea-id> --reason "reflection_budget_exhausted"
```

Rejected/exhausted ideas stay in the audit trail and final `ideas.json` with `evaluation: "REJECTED"`.

## Finalizing An Idea

Only finalize the latest draft after a fresh critic verdict matching the latest draft hash.

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  idea finalize --run-id <run-id> --idea-id <idea-id>
```

If this fails, do not bypass it by editing JSON. Resume and follow the returned error. Common blockers are stale critic, missing S2 evidence for scientist/researcher, or mode disallowing `ACCEPTED_WITHOUT_REFERENCE`.

## Ranking Agent

After all requested slots are attempted, or after budget forces stopping, rank candidates if at least one researchable candidate exists.

Record intent:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation intent start --run-id <run-id> --role ranker
```

Ranker prompt must include:

- all terminal ideas from `.ai-scientist/runs/<run-id>/ideas.json`
- frozen mode config and ranking prompt
- evidence summaries and critic verdicts
- instruction to score every terminal non-malformed idea
- instruction that dense `rank` applies only to plain `ACCEPTED`
- instruction to select one default research candidate

Ranking payload:

```json
{
  "selected_idea_id": "idea-001",
  "rationale": "Why this is the default candidate",
  "ranked_ideas": [
    {
      "idea_id": "idea-001",
      "score": 88,
      "score_components": {
        "novelty": 20,
        "evidence": 20,
        "feasibility": 25,
        "repo_fit": 23
      },
      "rationale": "Strong candidate",
      "risk_flags": []
    }
  ]
}
```

Record ranking:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation rank-finalize --run-id <run-id> --json '<ranking JSON>'
```

## Completion

Successful completion requires:

- no pending subagent intent
- no active unterminated idea
- requested slots attempted unless early stop is explicitly configured
- at least one researchable candidate under the frozen mode config
- finalized ranking
- valid selected candidate
- `ideation_to_research` validation/handoff evidence

Complete:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation complete --run-id <run-id>
```

If budget was exhausted but at least one researchable candidate exists:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation complete --run-id <run-id> --budget-exhausted
```

If no researchable candidate exists:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation exhaust --run-id <run-id>
```

Terminal statuses:

- `COMPLETED`: successful normal handoff.
- `COMPLETED_BUDGET_EXHAUSTED`: successful handoff after budget exhaustion.
- `EXHAUSTED_NO_CANDIDATE`: terminal failure, Stop hook allows exit, `ideation_to_research` fails.
- `CANCELLED`: explicit cancellation, no valid handoff.

Cancel only when the user asks or continuation is impossible:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo <target-repo> \
  ideation cancel --run-id <run-id> --reason "<reason>"
```

## Validation

Run this before reporting a successful research-ready handoff:

```bash
python plugins/ai-scientist/scripts/validate_run.py \
  <target-repo> --gate ideation_to_research --run-id <run-id>
```

`EXHAUSTED_NO_CANDIDATE` should fail this validator. That is expected and still terminal for Stop hook.

## Final Response

Report:

- run id
- strictness mode
- terminal status
- selected idea id if any
- number of terminal ideas and researchable candidates
- validation command and result
- artifact paths

Do not claim the research loop has started unless the user explicitly asked for a separate research-loop start.
