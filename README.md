# AI Scientist Codex Plugin

A Codex-native plugin for auditable research workflows: **ideation**, **bounded experiment loops**, **evidence review**, and **final writeups**. It is inspired by AI Scientist-style automation, but it does **not** wrap, import, invoke, vendor, or depend on `AI-Scientist-v2` at runtime.

The plugin is intentionally evidence-first: research state is written to local `.ai-scientist/` artifacts, phase transitions are validated by a deterministic helper, and final claims require explicit verifier approval.

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
- optionally using Semantic Scholar through `S2_API_KEY`
- producing structured JSON ideas
- initializing non-invasive `.ai-scientist/` metadata

Expected artifacts include:

```text
.ai-scientist/config.json
.ai-scientist/ideas/ideas.json
```

Ideation should not mutate target repository code. The only permitted target repository writes during ideation are `.ai-scientist/` artifacts.

### 2. Research loop

Skill: `research-loop`

Use this when you want Codex to run bounded experiments for a selected idea while preserving benchmark and split integrity.

It manages:

- dependency planning before execution
- approval state for dependencies
- API budgeting and `api-ledger.jsonl`
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
        │   ├── api-ledger.schema.json
        │   ├── config.schema.json
        │   ├── dependency-plan.schema.json
        │   ├── handoff.schema.json
        │   ├── idea.schema.json
        │   ├── journal.schema.json
        │   ├── principles.schema.json
        │   ├── run-status.schema.json
        │   └── verifier-decision.schema.json
        ├── scripts/
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

## Quick start

From this repository root, verify the plugin manifest and the valid minimal fixture:

```bash
python3 -m json.tool plugins/ai-scientist/.codex-plugin/plugin.json >/dev/null
python3 plugins/ai-scientist/scripts/validate_run.py \
  plugins/ai-scientist/tests/fixtures/valid-minimal \
  --gate all
```

A successful run prints a `PASS` message.

You can also confirm that negative fixtures fail closed. For example, this should fail because leakage evidence is missing:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py \
  plugins/ai-scientist/tests/fixtures/missing-leakage-evidence \
  --gate research_to_review
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
.ai-scientist/ideas/ideas.json
```

Validate the transition into research when the run artifacts are prepared:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate ideation_to_research
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
.ai-scientist/runs/<run-id>/dependency-plan.json
.ai-scientist/runs/<run-id>/api-ledger.jsonl
.ai-scientist/runs/<run-id>/baseline/
.ai-scientist/runs/<run-id>/nodes/
.ai-scientist/runs/<run-id>/run-status.json
.ai-scientist/runs/<run-id>/handoff.jsonl
```

Before moving to review, validate:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate research_to_review
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
python3 plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate review_to_writeup
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
python3 plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate launch
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
      dependency-plan.json
      api-ledger.jsonl
      journal.json
      run-status.json
      handoff.jsonl
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

- at least one idea in `ideas/ideas.json`
- `config.json` with strictness mode, target repo, and API budgets
- `dependency-plan.json` with every planned dependency marked as one of:
  - `approved`
  - `rejected`
  - `not_needed`
- initialized `api-ledger.jsonl`
- approved `handoff.jsonl` record
- passing validator result

Validation command:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate ideation_to_research
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
- approved `handoff.jsonl` record
- passing validator result

Validation command:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate research_to_review
```

### Review to writeup

Requires:

- structured review
- verdict
- leakage assessment
- split integrity assessment
- baseline comparison
- strictness-mode criteria
- approved `handoff.jsonl` record
- passing validator result

Validation command:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate review_to_writeup
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
python3 plugins/ai-scientist/scripts/validate_run.py <target-repo> --gate launch
```

## Validator usage

Main validator:

```text
plugins/ai-scientist/scripts/validate_run.py
```

Supported gates:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py <target> --gate ideation_to_research
python3 plugins/ai-scientist/scripts/validate_run.py <target> --gate research_to_review
python3 plugins/ai-scientist/scripts/validate_run.py <target> --gate review_to_writeup
python3 plugins/ai-scientist/scripts/validate_run.py <target> --gate launch
python3 plugins/ai-scientist/scripts/validate_run.py <target> --gate principles
python3 plugins/ai-scientist/scripts/validate_run.py <target> --gate all
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
python3 -m json.tool plugins/ai-scientist/.codex-plugin/plugin.json >/dev/null
python3 plugins/ai-scientist/scripts/validate_run.py plugins/ai-scientist/tests/fixtures/valid-minimal --gate all
```

## Status

v1 is code-complete and locally verified. The remaining known gap is a live plugin-install/runtime smoke test in the target Codex plugin environment.
