# AI Scientist Codex Plugin

A Codex-native plugin for auditable research workflows: ideation, bounded experiment loops, evidence review, and final writeups. The implementation is designed for local repository work with deterministic artifact checks rather than wrapping or invoking an external AI Scientist runtime.

## What is included

- **Four primary skills** under `plugins/ai-scientist/skills/`:
  - `ideation` — generate structured experiment ideas and initialize non-invasive `.ai-scientist/` artifacts.
  - `research-loop` — run bounded experiments with dependency planning, API ledgers, strictness modes, and phase gates.
  - `review` — evaluate split integrity, leakage risk, baseline comparison, strictness-mode criteria, and verdicts.
  - `writeup` — produce final reports with disclosure, limitations, and negative-result handling.
- **Artifact contract** in `plugins/ai-scientist/references/artifact-contract.md`.
- **JSON schemas** in `plugins/ai-scientist/schemas/`.
- **Fail-closed validator** in `plugins/ai-scientist/scripts/validate_run.py`.
- **Positive and negative fixtures** in `plugins/ai-scientist/tests/fixtures/`.

## Repository layout

```text
.
├── README.md
├── GUIDELINES.md
└── plugins/
    └── ai-scientist/
        ├── .codex-plugin/plugin.json
        ├── README.md
        ├── references/artifact-contract.md
        ├── schemas/
        ├── scripts/validate_run.py
        ├── skills/
        │   ├── ideation/SKILL.md
        │   ├── research-loop/SKILL.md
        │   ├── review/SKILL.md
        │   └── writeup/SKILL.md
        └── tests/fixtures/
```

## Install or use locally

Use `plugins/ai-scientist/` as the plugin root. The manifest is at:

```bash
plugins/ai-scientist/.codex-plugin/plugin.json
```

For local development, point your Codex/plugin tooling at the `plugins/ai-scientist` directory or copy that directory into your local plugin workspace.

## Validate the plugin

Run the static and fixture checks from the repository root:

```bash
python3 -m json.tool plugins/ai-scientist/.codex-plugin/plugin.json >/dev/null
find plugins/ai-scientist/skills -mindepth 2 -maxdepth 2 -name SKILL.md
python3 plugins/ai-scientist/scripts/validate_run.py plugins/ai-scientist/tests/fixtures/valid-minimal --gate all
```

Representative negative checks should fail closed, for example:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py \
  plugins/ai-scientist/tests/fixtures/missing-leakage-evidence \
  --gate research_to_review
```

## Core safety model

The plugin is intentionally evidence-first:

- No runtime dependency on external reference repositories.
- No train/test leakage, split manipulation, or deceptive metrics.
- Dependency installation requires explicit planning and approval.
- API use is budgeted and logged in `api-ledger.jsonl`.
- Phase transitions require approved `handoff.jsonl` records and passing validator results.
- Final launch/writeup requires a `verifier-decision.json` decision of `go` with no blockers.

See `GUIDELINES.md` for maintainer and contributor expectations.

## Status

v1 is code-complete and locally verified. The remaining known gap is a live plugin-install/runtime smoke test in the target Codex plugin environment.
