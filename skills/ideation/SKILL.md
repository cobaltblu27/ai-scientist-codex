---
name: ideation
description: Generate structured research ideas from an inline prompt by running a Codex-native, Stop-hook-enforced ideation loop.
---

# Ideation

<Purpose>
Use this skill ONLY when the user explicitly triggers this skill. This skill is for research ideas, hypotheses, or experiment proposals before running a research loop, a separate skill.

You are the ideation orchestrator. The current Codex session owns the loop. Python helper commands only create artifacts, validate state transitions, call/record Semantic Scholar when requested, and compute the next Stop-hook cursor. Do not run a Python loop, do not run nested `codex exec`, and do not run a retired Python-owned ideation orchestrator.
</Purpose>

<Execution_Policy>
- 
</Execution_Policy>

<Non_Negotiable_Rules>
1. Treat the invocation text as the research topic. Do not require a Markdown topic file.
2. Do not mutate target repository source code during ideation. The only target-repository writes are under `.ai-scientist/`.
3. Install/check the project-local Stop hook before starting a real run.
4. All state transitions go through `ai-scientist`.
5. Record subagent intents before spawning generators, critics, or the ranker. Pending intents intentionally block Stop until you record completion or cancellation.
6. Before spawning the first generator batch for a topic, perform the prompt-only pre-generation synthesis: find reference papers, run `skills/heiemeier-question/SKILL.md`, and use those insights to frame generator assignments.
7. Spawn a separate idea-generation subagent for each substantive idea draft or revision. Use `gpt-5.5` with `xhigh` effort for substantive idea generation when model controls are available.
8. Spawn a fresh critic for each draft or revised draft. Include previous critic verdict/revision notes in the new critic prompt; do not reuse long critic context.
9. Ranking is LLM-owned. After idea generation/reflection is done and at least one researchable candidate exists, `rank-candidates` starts the ranker intent.
10. `ideation_to_research` means "safe for research to consume." It must not start the research loop. Research start is a separate explicit user action.
11. Do not report success while Stop hook would still block.
</Non_Negotiable_Rules>
- 
<Required_Artifacts>

## Required Artifacts

All source-of-truth artifacts live under `.ai-scientist/runs/<run-id>/`:

- `config.json`: frozen ideation config, mode preset, prompt paths, and scoring policy.
- `loop-state.json`: active cursor, active idea ids, pending intents, terminal status, candidate/ranking state.
- `ideas.json`: canonical terminal idea archive.
- `journal.jsonl`: append-only audit stream.
- `logs/drafts/*.json`: versioned draft payloads.
- `logs/critics/*.json`: critic verdict payloads.
- `logs/openalex/*.json` and `logs/semantic-scholar/*.json`: literature response payloads when used.
- `logs/pending/<intent-id>.json`: assigned path where each subagent writes JSON only.
- `logs/ideation-contract.json`: shared run context, repo entrypoints, split policy, hardware limits, forbidden workflows, reusable baselines, metric names, and strictness mode.
- `logs/ranking/ranking-final.json`: final ranking payload.

Root `.ai-scientist/active-run.json` points the Stop hook to the active run.
Shared literature caches live under `.ai-scientist/evidence-cache/openalex/` and `.ai-scientist/evidence-cache/semantic-scholar/`.

</Required_Artifacts>

<Python_Launcher>

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

</Python_Launcher>

<Ideation_Policy>

<Common>

These are common rules for ideation. You MUST consider this for idea generation and reflection.
- When suggesting a new AI architecture for performance boost, you MUST include a reference paper that contains a comparable performance result. The reference should be or be close to SOTA (you may use web search to confirm this).

</Common>

<Modes>

- These are ideation policy "modes". You MUST consider the policy of given mode into consideration on idea generation and reflection.
- Default mode is `scientist`. Mode is frozen once `ideation start` runs.
- Mode presets live in frozen `config.json`. Read prompt paths from the preset instead of hardcoding subagent prompts.

### `scientist`:
- centered on scientific/engineering finding or novel methodology for enhanced performance.
- when suggesting a methodology for performance boost, refrain from mere incremental changes.
- requires literature evidence for plain `ACCEPTED`; critic prioritizes novelty, publication claim, leakage/split risk, and evidence quality.
### `engineer`: 
- Search for papers, that can guarantee a performance boost.
- Semantic Scholar is advisory only; critic prioritizes likely performance, implementation feasibility, and repo fit. Novelty is optional.
### `custom`:
- Follow the user's custom criteria and make the success rule explicit enough for handoff.

Subagent prompt files are mode-specific:

- Generator: `prompts/ideation/<mode>/generator.md`
- Critic: `prompts/ideation/<mode>/critic.md`
- Ranker: `prompts/ideation/<mode>/ranker.md`


</Modes>
</Ideation_Policy>

<Startup>

## Startup

From the target repository root, install/check the Stop hook:

```bash
ai-scientist hooks install --project-root <target-repo>
```

Start the run:

```bash
ai-scientist \
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
ai-scientist \
  --target-repo <target-repo> \
  ideation resume --run-id <run-id> --prompt
```

Use the returned `next_action` and prompt text as the immediate loop cursor. Repeat resume after every major state transition.

</Startup>

<Cursor_Actions>

## Cursor Actions

The helper computes `next_action`. Follow it exactly.

- `start_generator_batch`: run the prompt-only pre-generation synthesis before the first generator batch for a topic, then record up to `ideation.concurrency.max_subagents` generator intents, spawn that many generator subagents, and record all draft results.
- `collect_subagent_results`: previous generator/critic/ranker intents are pending; record completion or cancellation for each representative `intent_id` before doing anything else.
- `search_semantic_scholar`: use `literature-search` as a backstop; run/record OpenAlex-first literature evidence if the generator did not already attach required evidence.
- `start_critic_batch`: record critic intents for all ready draft `idea_ids`, spawn critics, then record all verdicts.
- `revise_or_reject_batch`: one or more critics returned `REVISE` or `REJECT`; revise same idea thread(s) or explicitly reject them.
- `finalize_ready_ideas`: call `ideation finalize-ready`; the transition is atomic and refuses stale critics, duplicate families without a meaningful protocol/metric delta, invalid commands, or missing evidence.
- `rank_candidates`: call `ideation rank-candidates`; this starts the ranker intent and blocks Stop until the result is recorded or cancelled.
- `complete_or_exhaust`: call `ideation complete` if researchable candidate and ranking exist; otherwise call `ideation exhaust`.

</Cursor_Actions>

<Pre_Generation_Synthesis>

## Pre-Generation Synthesis

Before the first generator intent batch for a topic, follow this prompt-only order:

1. Preflight reference scan.
2. Heiemeier question pass.
3. Generator assignment synthesis.
4. Generator intent batch.

This sequence is orchestration guidance, not a new CLI lifecycle gate. Do not create new required artifacts, new cursor actions, or new Stop-hook blockers for this preflight. Keep the result as compact context that is copied into generator assignments.

### Preflight Reference Scan

Find reference papers first. Use the query strategy and provider order from `skills/literature-search/SKILL.md`: OpenAlex first, Semantic Scholar as fallback. Because no canonical idea id may exist yet, these preflight references are advisory seed context only. Do not treat them as canonical `evidence_refs` unless a generator later records evidence through the existing literature CLI for its assigned idea id.

Capture a short brief:

- likely benchmark/reference papers, or a clear "none found" note;
- task, dataset, metric, and baseline hints found in those papers;
- reference gaps, conflicting evidence, and unresolved assumptions.

### Heiemeier Question Pass

Use `skills/heiemeier-question/SKILL.md` on the original topic plus the preflight reference brief. Lay out the questions and answer them one by one. Extract only the high-signal insights needed for generator assignments: problem framing, current approaches, gap, key insight, smallest publishable version, skeptical-reviewer evidence, and success checks.

### Generator Assignment Synthesis

Before spawning generator subagents, convert the reference scan and Heiemeier answers into a compact assignment brief. Give every generator the shared brief, then add slot-specific emphasis so subagents explore distinct hypotheses instead of rephrasing the same paper trail.

The compact brief should include:

- preflight reference papers or a "none found" note;
- Heiemeier answers/insights;
- unresolved assumptions from the preflight;
- seed directions to explore and obvious directions to avoid;
- reminder that generator-owned literature search is still required when the idea relies on papers, baselines, novelty, or benchmark evidence.

</Pre_Generation_Synthesis>

<Subagent_Protocol>

## Subagent Protocol

Before spawning any subagent:

```bash
ai-scientist \
  --target-repo <target-repo> \
  ideation intent start-batch --run-id <run-id> --role generator --count <n>
```

Use `--role critic --idea-ids <idea-id> ...` for critic batches. Ranking remains single-agent and is started with `ideation rank-candidates`.

Each returned intent includes `result_path`. Give that path to the subagent and require it to overwrite the file with JSON only. `intent complete --intent-id <id>` reads `result_path` by default. Use `--json` or `--path` only as explicit overrides.

```bash
ai-scientist \
  --target-repo <target-repo> \
  ideation intent complete --run-id <run-id> --intent-id <intent-id>
```

If the subagent result is malformed or unusable, cancel the pending intent with a reason, then resume:

```bash
ai-scientist \
  --target-repo <target-repo> \
  ideation intent cancel --run-id <run-id> --intent-id <intent-id> --reason "malformed generator output"
```

Failed/cancelled attempts consume loop budget. Do not leave pending intents unresolved.

</Subagent_Protocol>

<Generator_Agent>

## Generator Agent

Spawn one generator per idea slot or substantive revision in the current batch. Generators should not edit files. Each returns one canonical idea object.

Generator prompt must include:

- research topic
- strictness mode
- current slot/idea id
- mode-specific generator prompt from `config.json` when available
- preflight reference papers or a "none found" note
- Heiemeier answers/insights from the pre-generation synthesis
- unresolved assumptions from the preflight
- `skills/literature-search/SKILL.md` and permission to use it during the generator intent
- previous critic verdict and required revisions when this is a revision
- instruction to return JSON only

Generators should use the preflight reference and Heiemeier brief as seed context, not as a substitute for canonical evidence. Generators should use `literature-search` themselves when the idea needs papers, baseline references, novelty checks, or benchmark protocol evidence. This is especially expected for scientist-mode drafts and performance-focused ideas. The generator may run `idea search-semantic-scholar` for its assigned `idea_id`; this records canonical evidence while the generator still owns query choice and synthesis.

Canonical draft payload should include at least:

```json
{
  "id": "idea-001",
  "family_key": "family_key",
  "title": "Short title",
  "hypothesis": "Concrete hypothesis",
  "research_contract": {
    "primary_hypothesis": "The exact hypothesis the research loop must resolve",
    "goal_type": "performance",
    "success_criteria": "Hard, non-drifting success rule",
    "failure_criteria": "Hard rule for when the original hypothesis is genuinely false",
    "allowed_rescue_scope": "What narrowed findings are allowed, if any",
    "kill_criteria": "When to stop rather than drift",
    "non_drift_definition": "What would count as quiet claim drift",
    "metrics_that_matter": ["score"],
    "non_negotiable_comparisons": ["baseline", "reference paper"],
    "baseline_reference": {
      "title": "Comparable reference paper or model",
      "usability": "How this reference can be used for baseline calculation"
    },
    "benchmark_plan": "How to calculate an apples-to-apples benchmark score in this repo",
    "target_threshold": "Minimum score or statistical rule required for success"
  },
  "unique_protocol": "What makes this experiment distinct from same-family ideas",
  "expected_metric": "Metric or benchmark target",
  "smoke_runnable_now": true,
  "requires_implementation": [],
  "minimum_command": "uv run python -m pytest",
  "evidence_refs": [],
  "rubric_scores": {"feasibility": 80, "repo_fit": 80},
  "risk_flags": ["Risk 1"]
}
```

Full prose, related work, and detailed plans belong in the referenced draft log, not in persisted state or final `ideas.json`. The `research_contract` is the exception: it must be persisted because research start freezes it as the anti-drift contract for node workers and critics.

</Generator_Agent>

<Direct_Draft_Recording>

If using direct recording instead of `intent complete`:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea draft --run-id <run-id> --json '<canonical idea JSON>'
```

</Direct_Draft_Recording>

<Literature_Search>

## Literature Search

Generator subagents should use `skills/literature-search/SKILL.md` when the mode/prompt makes it useful. The orchestrator should use the same skill when the cursor requests literature evidence because a generator returned without required evidence. Scientist requires literature evidence before plain `ACCEPTED`. Engineer and custom treat literature search as advisory unless the frozen config or custom criteria require it.

Provider policy: use OpenAlex first. Semantic Scholar is fallback when OpenAlex fails or when explicitly requested. The command name is historical; `--provider auto` is OpenAlex-first.

Live query:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea search-semantic-scholar --run-id <run-id> --idea-id <idea-id> --query "<query>"
```

Explicit provider examples:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea search-semantic-scholar --run-id <run-id> --idea-id <idea-id> --query "<query>" --provider openalex
```

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea search-semantic-scholar --run-id <run-id> --idea-id <idea-id> --query "<query>" --provider semantic_scholar
```

Precomputed evidence payload:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea search-semantic-scholar --run-id <run-id> --idea-id <idea-id> --json '<evidence JSON>'
```

Batch evidence attachment:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea record-evidence-batch --run-id <run-id> --idea-ids idea-001 idea-002 --queries "query 1" "query 2"
```

All API evidence is logged to `journal.jsonl` as `api_call` with provider, fallback source/reason when applicable, and provenance `live`, `cache`, or `precomputed`. Batch evidence writes are atomic: one invalid idea id blocks the whole state update.

</Literature_Search>

<Critic_Agent>

## Critic Agent

Spawn a fresh critic for every draft version. The critic should not edit files. It returns a verdict payload.

Critic prompt must include:

- current canonical idea draft
- strictness mode and mode-specific critic prompt path from frozen `config.json`
- evidence/search results if available
- previous critic verdict and required revisions if this is a revised draft
- instruction to return JSON only
- the requirement that `research_contract` blocks quiet drift from the original goal into a merely valid report or weak negative result

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

- `ACCEPT`: candidate may become plain `ACCEPTED` if CLI hard gates pass.
- `ACCEPT_WITHOUT_REFERENCE`: allowed only by mode config; useful for engineer/custom or S2 failure cases.
- `REVISE`: do not finalize; either revise same idea thread or reject explicitly.
- `REJECT`: reject explicitly or revise if the orchestrator has a clear reason.

Record verdict:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea critic-record --run-id <run-id> --idea-id <idea-id> --json '<critic JSON>'
```

</Critic_Agent>

<Revision_And_Rejection>

## Revision And Rejection

For `REVISE`, either keep the same idea thread:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea revise-start --run-id <run-id> --idea-id <idea-id> --reason "<revision reason>"
```

Then spawn a new generator for the revised draft.

Or abandon it explicitly:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea reject --run-id <run-id> --idea-id <idea-id> --reason "abandoned_after_revise"
```

For budget exhaustion on an active idea:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea exhaust --run-id <run-id> --idea-id <idea-id> --reason "reflection_budget_exhausted"
```

Rejected/exhausted ideas stay in the audit trail and final `ideas.json` with `evaluation: "REJECTED"`.

</Revision_And_Rejection>

<Finalizing_Ideas>

## Finalizing Ideas

Only finalize the latest draft after a fresh critic verdict matching the latest draft hash.

```bash
ai-scientist \
  --target-repo <target-repo> \
  ideation finalize-ready --run-id <run-id>
```

Use `idea finalize --idea-id <idea-id>` only for a targeted single-idea transition. If finalization fails, do not bypass it by editing JSON. Resume and follow the returned error. Common blockers are stale critic, missing S2 evidence for scientist, duplicate family/protocol/metric overlap, invalid `minimum_command`, placeholder commands without `requires_implementation`, or mode disallowing `ACCEPTED_WITHOUT_REFERENCE`.

</Finalizing_Ideas>

<Ranking>

## Ranking

After all requested slots are attempted, or after budget forces stopping, rank candidates if at least one researchable candidate exists.

Start the ranker:

```bash
ai-scientist \
  --target-repo <target-repo> \
  ideation rank-candidates --run-id <run-id>
```

The ranker prompt must include:

- all terminal ideas from `.ai-scientist/runs/<run-id>/ideas.json`
- frozen mode config and ranker prompt path
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
ai-scientist \
  --target-repo <target-repo> \
  ideation intent complete --run-id <run-id> --intent-id <ranker-intent-id>
```

For manual/direct payload recording, `ideation rank-finalize --run-id <run-id> --json '<ranking JSON>'` remains available.

</Ranking>

<Completion>

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
ai-scientist \
  --target-repo <target-repo> \
  ideation complete --run-id <run-id>
```

If budget was exhausted but at least one researchable candidate exists:

```bash
ai-scientist \
  --target-repo <target-repo> \
  ideation complete --run-id <run-id> --budget-exhausted
```

If no researchable candidate exists:

```bash
ai-scientist \
  --target-repo <target-repo> \
  ideation exhaust --run-id <run-id>
```

Terminal statuses:

- `COMPLETED`: successful normal handoff.
- `COMPLETED_BUDGET_EXHAUSTED`: successful handoff after budget exhaustion.
- `EXHAUSTED_NO_CANDIDATE`: terminal failure, Stop hook allows exit, `ideation_to_research` fails.
- `CANCELLED`: explicit cancellation, no valid handoff.

</Completion>

<Cancellation>

Cancel only when the user asks or continuation is impossible:

```bash
ai-scientist \
  --target-repo <target-repo> \
  ideation cancel --run-id <run-id> --reason "<reason>"
```

</Cancellation>

<Validation>

## Validation

Run this before reporting a successful research-ready handoff:

```bash
ai-scientist validate run \
  <target-repo> --gate ideation_to_research --run-id <run-id>
```

`EXHAUSTED_NO_CANDIDATE` should fail this validator. That is expected and still terminal for Stop hook.

</Validation>

<Final_Response>

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

</Final_Response>
