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

This repository is a Codex plugin root. It gives Codex a structured workflow for research-style experimentation inside a target repository.

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

- an orchestrator cursor kept alive by the Stop hook
- checkpointed worker, comparative ranker, and revision-worker records
- shared ranker and mode-specific revision prompt paths under `prompts/research-loop/`
- explicit resource leases for experiment commands
- command, metric, and result evidence in `journal.jsonl`
- final selection and completion audit evidence
- phase-gate validation

No research mode permits leakage, split manipulation, or deceptive scoring.

### 3. Review

Skill: `review`

Use this after research artifacts exist and before a final report is written.

It checks:

- split integrity evidence
- leakage evidence
- baseline comparison
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
- benchmark and split details
- result limitations
- failed attempts or negative findings
- reproducibility notes
- links or references to command logs, metrics, leakage checks, split checks, structured review, and verifier decision

The writeup must not present a rejected or engineer-mode result as a scientist-mode research claim.

## Repository layout

```text
.
├── .codex-plugin/plugin.json
├── README.md
├── GUIDELINES.md
├── pyproject.toml
├── references/
│   └── artifact-contract.md
├── schemas/
│   ├── active-run.schema.json
│   ├── config.schema.json
│   ├── journal.schema.json
│   ├── loop-state.schema.json
│   ├── node.schema.json
│   └── selection.schema.json
├── prompts/
│   └── research-loop/
├── skills/
│   ├── ideation/SKILL.md
│   ├── research-loop/SKILL.md
│   ├── review/SKILL.md
│   └── writeup/SKILL.md
├── src/
│   ├── cli/
│   ├── core/
│   ├── hooks/
│   ├── research/
│   ├── validation/
│   └── writeup/
└── tests/
    └── fixtures/
```

## Install or use locally

Use this repository root as the plugin root.

The plugin manifest is:

```bash
.codex-plugin/plugin.json
```

For local development, point your Codex/plugin tooling at this checkout or copy this checkout into your local plugin workspace.

For hard continuation, install the project-local Codex Stop hook in the target repository:

```bash
uv run ai-scientist hooks install --project-root <target-repo>
uv run ai-scientist hooks check --project-root <target-repo>
```

The hook is standalone and reads `.ai-scientist/active-run.json` plus
`.ai-scientist/runs/<run-id>/loop-state.json`. It returns `decision: "block"`
while a run is active or lacks passing completion audit evidence.

## Quick start

From this repository root, verify the plugin manifest and active CLI:

```bash
uv run python -m json.tool .codex-plugin/plugin.json >/dev/null
uv run ai-scientist --help
```

A successful run prints a `PASS` message.

## Ideation orchestrator

The `ideation` skill is goal-driven and has no CLI lifecycle. The current Codex
session creates a goal, freezes `contract.json`, delegates generator, critic, and
pilot work through native agents, and writes Markdown idea files plus a lightweight
`ideas.json` index. Progress and completion are recorded in `run.md`.

The only CLI commands used by ideation are `agents check` and `agents install`.

## Typical workflow

### Step 1: Generate ideas

Ask Codex to use the `ideation` skill with a research prompt.

Example prompt:

```text
Use ideation to propose experiments for improving this model on the current benchmark.
```

Expected artifacts are file-driven rather than CLI state:

```text
.ai-scientist/runs/<run-id>/contract.json
.ai-scientist/runs/<run-id>/run.md
.ai-scientist/runs/<run-id>/ideas.json
.ai-scientist/runs/<run-id>/ideas/<idea-id>.md
.ai-scientist/runs/<run-id>/logs/pilots/<idea-id>/report.md
```

### Step 2: Plan and run research

Ask Codex to use `research-loop` on a selected idea.

Example prompt:

```text
Run research-loop for idea-001 on this repository.
Preserve the benchmark split and run experiments through resource leases.
```

Expected artifacts include:

```text
.ai-scientist/runs/<run-id>/config.json
.ai-scientist/runs/<run-id>/journal.jsonl
.ai-scientist/runs/<run-id>/loop-state.json
.ai-scientist/runs/<run-id>/selection.json
.ai-scientist/runs/<run-id>/logs/resources/
```

Before moving to review, validate:

```bash
uv run ai-scientist validate run <target-repo> --gate research_to_review
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
uv run ai-scientist validate run <target-repo> --gate review_to_writeup
```

### Step 4: Write the final report

Ask Codex to use `writeup`.

Example prompt:

```text
Write up the accepted AI Scientist run.
Include disclosure, benchmark split, limitations, and reproducibility notes.
```

Before publication or final launch, validate:

```bash
uv run ai-scientist validate run <target-repo> --gate launch
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
      loop-state.json
      selection.json
      logs/
        resources/
        tasks/
      review/
        structured-review.json
```

See the detailed contract in:

```text
references/artifact-contract.md
```

## Acceptance criteria

The research loop holds one evidence standard: multi-seed reproducibility, strict
ablation, hypothesis-causality evidence, and leakage/split checks. A run may supply
`custom_criteria` in its start payload to add a run-specific acceptance bar on top of
those universal integrity rules; nothing may weaken them.

Leakage, split manipulation, and deceptive metrics are never permitted.

## Phase gates

Every transition is intended to fail closed if required evidence is missing or invalid.

### Research to review

Requires:

- completed research loop state
- no unresolved checkpointed work
- no active resource leases
- final selection pointing at an accepted node/outcome
- completion audit evidence
- approved `journal.jsonl` handoff record
- passing validator result

Validation command:

```bash
uv run ai-scientist validate run <target-repo> --gate research_to_review
```

### Review to writeup

Requires:

- structured review
- verdict
- leakage assessment
- split integrity assessment
- baseline comparison
- approved `journal.jsonl` handoff record
- passing validator result

Validation command:

```bash
uv run ai-scientist validate run <target-repo> --gate review_to_writeup
```

### Launch or final approval

Requires:

- completed writeup manifest and reports
- at least one recorded figure
- compiled PDF when required
- independent final audit with verdict `ACCEPT`

Validation command:

```bash
uv run ai-scientist validate run <target-repo> --gate launch
```

## Validator usage

Main validator:

```text
uv run ai-scientist validate run
```

Supported gates:

```bash
uv run ai-scientist validate run <target> --gate research_to_review
uv run ai-scientist validate run <target> --gate review_to_writeup
uv run ai-scientist validate run <target> --gate launch
```

`<target>` can be a target repository, a fixture root, or an `.ai-scientist/` directory.

The validator fails for problems such as:

- missing required JSON or JSONL artifacts
- malformed JSON or JSONL
- missing leakage or split-integrity evidence
- incomplete research completion state
- incomplete structured review coverage
- missing writeup reports, figures, PDF, disclosure, limitations, or final audit

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

1. `references/artifact-contract.md`
2. schemas in `schemas/`
3. `uv run ai-scientist validate run`
4. skill instructions that mention the changed contract

Before claiming a change is complete, run at least:

```bash
uv run python -m json.tool .codex-plugin/plugin.json >/dev/null
uv run pytest -q
```

## Status

v1 is code-complete and locally verified. The remaining known gap is a live plugin-install/runtime smoke test in the target Codex plugin environment.
