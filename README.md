# AI Scientist Codex Plugin

A Codex-native plugin for auditable research workflows: **ideation**, **bounded experiment loops**, **evidence review**, and **final writeups**. It is inspired by AI Scientist-style automation, but it does **not** wrap, import, invoke, vendor, or depend on `AI-Scientist-v2` at runtime.

The plugin is intentionally evidence-first: research state is written to local `.ai-scientist/` artifacts, phase transitions are validated by a deterministic helper, and final claims require explicit verifier approval.

Command examples use `python` for portability. Replace it with the launcher
provided by the target environment, such as `uv run python`,
`conda run -n <env> python`, `micromamba run -n <env> python`, `python3`, or an
absolute interpreter path. Do not assume a specific environment manager.

## Table of contents

- [Overview](#overview)
- [Key features](#key-features)
  - [1. Ideation](#1-ideation)
  - [2. Research loop](#2-research-loop)
  - [3. Review](#3-review)
  - [4. Writeup](#4-writeup)
- [Repository layout](#repository-layout)
- [Install or use locally](#install-or-use-locally)
- [Quick start](#quick-start)
- [Ideation orchestrator](#ideation-orchestrator)
- [Typical workflow](#typical-workflow)
  - [Step 1: Generate ideas](#step-1-generate-ideas)
  - [Step 2: Plan and run research](#step-2-plan-and-run-research)
  - [Step 3: Review the run](#step-3-review-the-run)
  - [Step 4: Write the final report](#step-4-write-the-final-report)
- [Artifact contract](#artifact-contract)
- [Strictness modes](#strictness-modes)
- [Phase gates](#phase-gates)
  - [Ideation to research](#ideation-to-research)
  - [Research to review](#research-to-review)
  - [Review to writeup](#review-to-writeup)
  - [Launch or final approval](#launch-or-final-approval)
- [Validator usage](#validator-usage)
- [Safety and integrity model](#safety-and-integrity-model)
- [Best use cases](#best-use-cases)
- [Limitations](#limitations)
- [Maintainer guidelines](#maintainer-guidelines)
- [Status](#status)

## Overview

This repository packages a Codex plugin under `plugins/ai-scientist/`. The plugin gives Codex a structured workflow for research-style experimentation inside a target repository.

Instead of operating as a black-box paper generator, the plugin requires explicit artifacts for each stage:

- ideas and hypotheses
- dependency decisions
- API call ledgers
- baseline and experiment evidence
- leakage and split-integrity checks
- structured review verdicts
- final verifier decisions

The result is a workflow that is easier to audit, reproduce, reject, or turn into a final report.

## Key features

### 1. Ideation

Skill: `ideation`

Use this when you want to turn a prompt into structured experiment ideas before changing the target repository.

It helps with:

- defining the research goal
- clarifying benchmark and split constraints
- choosing a strictness mode
- optionally using Semantic Scholar through `S2_API_KEY` (missing keys warn loudly for live searches)
- producing ranked structured JSON ideas with `ACCEPTED`, `ACCEPTED_WITHOUT_REFERENCE`, or `REJECTED` evaluation
- initializing non-invasive `.ai-scientist/` metadata

Expected artifacts include:

```text
.ai-scientist/runs/<run-id>/config.json
.ai-scientist/runs/<run-id>/ideas.json
```

Ideation should not mutate target repository code. The only permitted target repository writes during ideation are `.ai-scientist/` artifacts.

### 2. Research loop

Skill: `research-loop`

Use this when you want Codex to run bounded experiments for a selected idea while preserving benchmark and split integrity.

It manages:

- dependency planning before execution
- approval state for dependencies
- API budgeting and `journal.jsonl` API-call records
- baseline evidence
- experiment node evidence
- leakage checks
- split integrity checks
- result summaries
- mode-specific deliverables
- phase-gate validation

No research mode permits leakage, split manipulation, or deceptive scoring.

### 3. Review

Skill: `review`

Use this after research artifacts exist and before a final report is written.

It checks:

- split integrity evidence
- leakage evidence
- baseline comparison
- strictness-mode criteria
- command and evidence trail
- whether the result should be accepted, revised, rejected, or marked as a negative result

Expected artifact:

```text
.ai-scientist/runs/<run-id>/review/structured-review.json
```

### 4. Writeup

Skill: `writeup`

Use this only after review artifacts and final launch checks are available.

A writeup must include:

- explicit AI Scientist / Codex assistance disclosure
- strictness mode
- benchmark and split details
- result limitations
- failed attempts or negative findings
- reproducibility notes
- links or references to command logs, metrics, leakage checks, split checks, structured review, and verifier decision

The writeup must not present a rejected or engineer-mode result as a scientist-mode research claim.

## Repository layout

```text
.
├── README.md
├── GUIDELINES.md
└── plugins/
    └── ai-scientist/
        ├── .codex-plugin/plugin.json
        ├── README.md
        ├── references/
        │   └── artifact-contract.md
        ├── schemas/
        │   ├── config.schema.json
        │   ├── idea.schema.json
        │   ├── journal.schema.json
        │   ├── active-run.schema.json
        │   ├── loop-state.schema.json
        │   ├── principles.schema.json
        │   ├── run-status.schema.json
        │   └── verifier-decision.schema.json
        ├── scripts/
        │   ├── ai_scientist_state.py
        │   ├── ai_scientist_stop_hook.py
        │   ├── ideation_orchestrator.py
        │   ├── install_codex_hooks.py
        │   └── validate_run.py
        ├── skills/
        │   ├── ideation/SKILL.md
        │   ├── research-loop/SKILL.md
        │   ├── review/SKILL.md
        │   └── writeup/SKILL.md
        └── tests/
            └── fixtures/
```

## Install or use locally

Use `plugins/ai-scientist/` as the plugin root.

The plugin manifest is:

```bash
plugins/ai-scientist/.codex-plugin/plugin.json
```

For local development, point your Codex/plugin tooling at `plugins/ai-scientist` or copy that directory into your local plugin workspace.

For hard continuation, install the project-local Codex Stop hook in the target repository:

```bash
python plugins/ai-scientist/scripts/install_codex_hooks.py --project-root <target-repo>
python plugins/ai-scientist/scripts/install_codex_hooks.py --project-root <target-repo> --check
```

The hook is standalone and reads `.ai-scientist/active-run.json` plus
`.ai-scientist/runs/<run-id>/loop-state.json`. It returns `decision: "block"`
while a run is active or lacks passing completion audit evidence.

## Quick start

From this repository root, verify the plugin manifest and the valid minimal fixture:

```bash
python -m json.tool plugins/ai-scientist/.codex-plugin/plugin.json >/dev/null
python plugins/ai-scientist/scripts/validate_run.py \
  plugins/ai-scientist/tests/fixtures/valid-minimal \
  --gate all
```

A successful run prints a `PASS` message.

You can also confirm that negative fixtures fail closed. For example, this should fail because leakage evidence is missing:

```bash
python plugins/ai-scientist/scripts/validate_run.py \
  plugins/ai-scientist/tests/fixtures/missing-leakage-evidence \
  --gate research_to_review
```

## Ideation orchestrator

The `ideation` skill is backed by an agent-driven loop:

```text
plugins/ai-scientist/scripts/ai_scientist_state_cli.py
```

The current Codex session is the orchestrator. Python only manages deterministic
state, Semantic Scholar recording, validation, and handoff artifacts:

1. `ideation start` records the prompt, frozen config, run-local `ideas.json`,
   `loop-state.json`, and `journal.jsonl`.
2. `ideation resume --prompt` returns the next cursor action for the main Codex
   orchestrator.
3. Native Codex subagents generate ideas, critique drafts, and rank candidates.
4. Helper commands record drafts, Semantic Scholar evidence, critic verdicts,
   final idea decisions, ranking, and terminal run state.
5. The project-local Stop hook blocks ending until ideation reaches
   `COMPLETED`, `COMPLETED_BUDGET_EXHAUSTED`, `EXHAUSTED_NO_CANDIDATE`, or
   `CANCELLED`.

Default loop settings are `--num-ideas 10`, `--reflection-budget 10`, and
`--strictness-mode scientist`.

Example start:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo . \
  ideation start \
  --run-id ideation-001 \
  --prompt "Generate ideas for improving the current benchmark without changing the split." \
  --num-ideas 10
```

Then continue from the cursor:

```bash
python plugins/ai-scientist/scripts/ai_scientist_state_cli.py \
  --target-repo . \
  ideation resume --run-id ideation-001 --prompt
```

## Typical workflow

### Step 1: Generate ideas

Ask Codex to use the `ideation` skill with a research prompt.

Example prompt:

```text
Use ideation to propose experiments for improving this model on the current benchmark.
Use scientist mode unless another mode is justified.
```

Expected artifacts:

```text
.ai-scientist/config.json
.ai-scientist/active-run.json
.ai-scientist/runs/<run-id>/ideas.json
.ai-scientist/runs/<run-id>/loop-state.json
```

Validate the transition into research when the run artifacts are prepared:

```bash
python plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate ideation_to_research
```

### Step 2: Plan and run research

Ask Codex to use `research-loop` on a selected idea.

Example prompt:

```text
Run research-loop for idea-001 on this repository.
Preserve the benchmark split, plan dependencies first, and use balanced mode.
```

Expected artifacts include:

```text
.ai-scientist/runs/<run-id>/config.json
.ai-scientist/runs/<run-id>/journal.jsonl
.ai-scientist/runs/<run-id>/baseline/
.ai-scientist/runs/<run-id>/nodes/
.ai-scientist/runs/<run-id>/loop-state.json
.ai-scientist/runs/<run-id>/run-status.json
```

Before moving to review, validate:

```bash
python plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate research_to_review
```

### Step 3: Review the run

Ask Codex to use `review`.

Example prompt:

```text
Review the latest AI Scientist run.
Check leakage, split integrity, baseline comparison, and mode-specific criteria.
Return accept, revise, reject, or negative-result with evidence.
```

Expected artifact:

```text
.ai-scientist/runs/<run-id>/review/structured-review.json
```

Validate the transition into writeup:

```bash
python plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate review_to_writeup
```

### Step 4: Write the final report

Ask Codex to use `writeup`.

Example prompt:

```text
Write up the accepted AI Scientist run.
Include disclosure, strictness mode, benchmark split, limitations, and reproducibility notes.
```

Before publication or final launch, validate:

```bash
python plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate launch
```

## Artifact contract

Runs are stored in the target repository under `.ai-scientist/`.

A typical run looks like this:

```text
.ai-scientist/
  config.json
  ideas/
    ideas.json
  runs/
    <run-id>/
      config.json
      journal.jsonl
      run-status.json
      verifier-decision.json
      principles.json
      baseline/
        metrics.json
        command.log
      nodes/
        <node-id>/
          metrics.json
          command.log
          split-integrity.json
          leakage-check.json
          result-summary.json
      review/
        structured-review.json
```

See the detailed contract in:

```text
plugins/ai-scientist/references/artifact-contract.md
```

## Strictness modes

The research loop supports five strictness modes:

| Mode | Purpose | Acceptance meaning |
| --- | --- | --- |
| `scientist` | Strongest evidence standard: multi-seed reproducibility, strict ablation, hypothesis-causality evidence, leakage/split checks. | Credible research claim. |
| `researcher` | Paper-oriented evidence with some pragmatic tuning after hypothesis validation. | Research-style evidence with disclosed pragmatism. |
| `balanced` | Baseline beat with leakage/split checks and lightweight ablation or sensitivity evidence. | Honest useful finding. |
| `builder` | Practical held-out improvement with baseline comparison and leakage/split checks. | Strong practical candidate. |
| `engineer` | Aggressive tuning and selection allowed with fixed benchmark/split and tuning log. | Strong usable model, not a paper claim. |

No mode permits leakage, split manipulation, or deceptive metrics.

## Phase gates

Every transition is intended to fail closed if required evidence is missing or invalid.

### Ideation to research

Requires:

- at least one researchable candidate in `runs/<run-id>/ideas.json`
- `config.json` with strictness mode, target repo, and API budgets
- `config.json` with dependency plan entries marked as one of:
  - `approved`
  - `rejected`
  - `not_needed`
- at least one `journal.jsonl` API-call record
- approved `journal.jsonl` handoff record
- passing validator result

Validation command:

```bash
python plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate ideation_to_research
```

### Research to review

Requires:

- baseline metrics and command log
- at least one experiment node
- node command logs
- node metrics
- split integrity evidence
- leakage evidence
- result summary
- mode-specific deliverables
- best node beats baseline under the declared benchmark
- approved `journal.jsonl` handoff record
- passing validator result

Validation command:

```bash
python plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate research_to_review
```

### Review to writeup

Requires:

- structured review
- verdict
- leakage assessment
- split integrity assessment
- baseline comparison
- strictness-mode criteria
- approved `journal.jsonl` handoff record
- passing validator result

Validation command:

```bash
python plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate review_to_writeup
```

### Launch or final approval

Requires:

- `verifier-decision.json`
- `decision: "go"`
- empty `blockers` list

Example:

```json
{
  "decision": "go",
  "blockers": []
}
```

Validation command:

```bash
python plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate launch
```

## Validator usage

Main validator:

```text
plugins/ai-scientist/scripts/validate_run.py
```

Supported gates:

```bash
python plugins/ai-scientist/scripts/validate_run.py <target> --gate ideation_to_research
python plugins/ai-scientist/scripts/validate_run.py <target> --gate research_to_review
python plugins/ai-scientist/scripts/validate_run.py <target> --gate review_to_writeup
python plugins/ai-scientist/scripts/validate_run.py <target> --gate launch
python plugins/ai-scientist/scripts/validate_run.py <target> --gate principles
python plugins/ai-scientist/scripts/validate_run.py <target> --gate all
```

`<target>` can be a target repository, a fixture root, or an `.ai-scientist/` directory.

The validator fails for problems such as:

- missing required JSON or JSONL artifacts
- malformed JSON or JSONL
- stale or non-zero validation records
- missing approved handoff records
- missing leakage or split-integrity evidence
- missing dependency approval statuses
- no-go verifier decisions
- non-empty verifier blockers
- incomplete principle traceability

## Safety and integrity model

The plugin is designed to enforce these rules:

- No runtime dependency on `AI-Scientist-v2` or any external reference checkout.
- No train/test leakage.
- No benchmark or split manipulation unless explicitly defined by the benchmark setup.
- No deceptive scoring or unsupported novelty claims.
- No unapproved dependency installs.
- API use must be budgeted and logged.
- Final writeups are gated by verifier decision.
- Negative and failed results must be handled honestly.

## Best use cases

Use this plugin when you want Codex to help with:

- experiment ideation
- ML or research project planning
- benchmark-preserving experiment loops
- scientific artifact tracking
- evidence review
- reproducible result summaries
- final research or engineering reports

Avoid treating the plugin as a black-box “make a paper” button. Its value is structured, auditable, evidence-gated research assistance.

## Limitations

- v1 is locally verified, but live plugin installation/runtime smoke testing still depends on the target Codex plugin environment.
- The validator checks artifact integrity and phase-gate evidence; it does not prove that a scientific claim is true.
- Human review remains important for methodology, claim strength, and real-world relevance.
- Dependency installation and external API access should remain user-supervised.

## Maintainer guidelines

See [`GUIDELINES.md`](GUIDELINES.md) for detailed maintainer guidance.

When changing the artifact contract, update these together:

1. `plugins/ai-scientist/references/artifact-contract.md`
2. schemas in `plugins/ai-scientist/schemas/`
3. `plugins/ai-scientist/scripts/validate_run.py`
4. positive and negative fixtures in `plugins/ai-scientist/tests/fixtures/`
5. skill instructions that mention the changed contract

Before claiming a change is complete, run at least:

```bash
python -m json.tool plugins/ai-scientist/.codex-plugin/plugin.json >/dev/null
python plugins/ai-scientist/scripts/validate_run.py plugins/ai-scientist/tests/fixtures/valid-minimal --gate all
```

## Status

v1 is code-complete and locally verified. The remaining known gap is a live plugin-install/runtime smoke test in the target Codex plugin environment.
