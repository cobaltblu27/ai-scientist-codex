# AI Scientist Plugin

A Claude Code and Codex plugin for auditable research workflows: **ideation**, **bounded experiment loops**, **evidence review**, and **final writeups**. It is inspired by AI Scientist-style automation, but it does **not** wrap, import, invoke, vendor, or depend on `AI-Scientist-v2` at runtime.

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

This repository is a Claude Code and Codex plugin root. It gives the active coding agent a structured workflow for research-style experimentation inside a target repository.

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

- an orchestrator cursor persisted through `/goal` and durable run artifacts
- checkpointed worker, comparative ranker, and revision-worker records
- committed constant definitions for every Codex subagent role under `agents/`
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
├── .claude-plugin/plugin.json
├── .codex-plugin/plugin.json
├── agents/
├── bin/ai-scientist
├── AGENTS.md
├── CLAUDE.md
├── docs/
│   ├── README.md
│   ├── GUIDELINES.md
│   ├── FRONTEND.md
│   ├── PLAN.md
│   └── SCHEMA.md
├── .github/workflows/        # ci.yml (tests, build, wheel smoke) and release.yml (wheel + sdist on a v* tag)
├── pyproject.toml
├── references/
│   └── artifact-contract.md
├── skills/
│   ├── ideation/SKILL.md
│   ├── research-loop/SKILL.md
│   ├── review/SKILL.md
│   └── writeup/SKILL.md
├── src/
│   ├── cli/
│   ├── core/
│   ├── dashboard/            # API server, session launcher; dist/ is the built frontend (gitignored, shipped in the wheel)
│   ├── frontend/             # Vite sources of the dashboard
│   ├── research/
│   ├── validation/
│   │   └── schemas/          # JSON schemas the validator applies
│   └── writeup/
└── tests/
    └── fixtures/
```

## Install

Two pieces: the plugin (skills, agents, prompts) comes from git through Claude Code's plugin system, and the `ai-scientist` CLI that the skills call comes as a wheel attached to each GitHub release. The wheel bundles the JSON schemas and the built dashboard, and its `dashboard` extra pulls in `claude-agent-sdk` (which ships its own `claude` binary) so the dashboard can launch sessions.

```bash
claude plugin marketplace add cobaltblu27/ai-scientist-codex
claude plugin install ai-scientist@ai-scientist

uv tool install --python 3.12 "ai-scientist[dashboard] @ https://github.com/cobaltblu27/ai-scientist-codex/releases/download/v0.2.0/ai_scientist-0.2.0-py3-none-any.whl"
ai-scientist doctor
```

`ai-scientist doctor` prints where the install found the plugin (`plugin_source`: `env`, `checkout`, or `installed` from `~/.claude/plugins/installed_plugins.json`), the schemas, the frontend, and the SDK, and lists anything missing. It also flags a version skew between the plugin manifest and the CLI: upgrade both together (`claude plugin update ai-scientist@ai-scientist` and the `uv tool install` line for the new release). `AI_SCIENTIST_PLUGIN_ROOT` overrides plugin discovery; `ai-scientist dashboard --plugin-dir <path>` does the same for one dashboard.

Run each long-lived workflow under `/goal` in Claude Code or Codex. The goal provides persistence, while `.ai-scientist/active-run.json` and the run artifacts provide durable resume context and completion evidence.

## Development

Use this checkout as the plugin root and run the CLI from its virtualenv:

```bash
claude --plugin-dir .
uv sync --extra dashboard
uv run ai-scientist dashboard --build-only     # builds src/dashboard/dist with npm; only needed for the dashboard
uv run pytest -q
```

`bin/ai-scientist` is a fallback that runs the CLI with the system `python3` (3.12 or newer, no SDK) straight from a checkout, for example inside a git-installed plugin without the wheel. The manifests are `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`; their `version` must match `pyproject.toml` (a test enforces it). For Codex, point your plugin tooling at this checkout.

## Quick start

From this repository root, verify the Claude Code components and the CLI:

```bash
claude plugin validate .claude-plugin/plugin.json
claude plugin validate agents
claude plugin validate skills
uv run ai-scientist doctor
```

## Ideation orchestrator

The `ideation` skill has no CLI lifecycle. The current session freezes
`contract.json`, delegates generator, critic, and pilot work through native agents,
and writes Markdown idea files plus a lightweight `ideas.json` index. Progress and
completion are recorded in `run.md`.

The Codex compatibility installer copies the committed TOML agent definitions into
the Codex agent directory; Claude Code loads the committed Markdown definitions directly.

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
docs/SCHEMA.md
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

1. `docs/SCHEMA.md`
2. schemas in `src/validation/schemas/`
3. `uv run ai-scientist validate run`
4. skill instructions that mention the changed contract

Before claiming a change is complete, run at least:

```bash
uv run python -m json.tool .codex-plugin/plugin.json >/dev/null
uv run pytest -q
```

## Status

v1 is code-complete and locally verified. The remaining known gap is a live plugin-install/runtime smoke test in the target Codex plugin environment.
