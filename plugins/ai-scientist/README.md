# AI Scientist Codex Plugin

This plugin provides Codex-native research workflows inspired by AI-scientist style automation without wrapping or invoking any external reference implementation. It is skill-first and stores auditable run state in the target repository under `.ai-scientist/`.

## Skills

- `ideation` — run an agent-driven Codex ideation loop from an inline prompt, with deterministic Python state helpers, optional Semantic Scholar evidence, versioned drafts, ranking, and non-invasive artifacts.
- `research-loop` — plan dependencies, run bounded experiments, log API use, and enforce phase gates.
- `review` — evaluate evidence for leakage, split integrity, baseline comparison, and mode criteria.
- `writeup` — generate a final report with explicit disclosure, limitations, and negative-result handling.

## CLI launcher

Command examples use the unified `ai-scientist` CLI. From this checkout, run it
as `uv run ai-scientist ...`; after installation, `ai-scientist ...` is the
console command. Legacy `plugins/ai-scientist/scripts/*.py` paths remain as thin
compatibility wrappers for older hooks and docs.

## Local credentials

Optional local API credentials may be kept in `plugins/ai-scientist/credentials.json`.
That file is ignored by git. Use `plugins/ai-scientist/credentials.example.json`
as the non-secret shape reference.

## Hard continuation setup

AI Scientist can install a project-local Codex Stop hook so active runs cannot
silently end before their loop state and completion audit pass:

```bash
ai-scientist hooks install --project-root <target-repo>
ai-scientist hooks check --project-root <target-repo>
```

The hook is standalone: it reads `.ai-scientist/active-run.json` and
`.ai-scientist/runs/<run-id>/loop-state.json`, emits `decision: "block"` for
active or incomplete phases, and does not depend on OMX or `oh-my-codex`.

## Artifact contract

See `references/artifact-contract.md`. Validate run artifacts with:

```bash
ai-scientist validate run <fixture-or-target-repo> --gate ideation_to_research
ai-scientist validate run <fixture-or-target-repo> --gate research_to_review
ai-scientist validate run <fixture-or-target-repo> --gate review_to_writeup
ai-scientist validate run <fixture-or-target-repo> --gate launch
ai-scientist validate run <fixture-or-target-repo> --gate principles
```

The validator is deterministic and fail-closed: missing evidence, malformed JSON/JSONL, non-approved handoffs, non-zero validator exits, no-go verifier decisions, or incomplete principle traceability return a non-zero exit.

## Research loop helper

The research loop is orchestrated by the current Codex session, not by a Python
process that launches nested Codex agents. Use the helper CLI only for state and
audit mutations:

```bash
ai-scientist --target-repo <target-repo> research start --run-id <run-id>
ai-scientist --target-repo <target-repo> resource run --node-id <node-id> --trial-id <trial-id> -- <command>
ai-scientist --target-repo <target-repo> selection finalize --selected-node <node-id>
```

The helper writes compact v1 artifacts under `.ai-scientist/runs/<run-id>/` and
logs state transitions, resource events, validation, and handoff records to
`journal.jsonl`.

## Ideation orchestrator

The ideation skill is agent-driven. The current Codex session is the long-running
orchestrator; Python only records deterministic state through:

```bash
ai-scientist
```

Install the project-local Stop hook first. Then start ideation state, use
`ideation resume --prompt` to get the next cursor action, spawn native Codex
subagents for generation/criticism/ranking, and record their outputs with
`ideation intent ...`, `idea ...`, and `ideation rank-finalize`. Do not use the
retired `ideation_orchestrator.py` loop or nested `codex exec`.

Generated run metadata is stored under `.ai-scientist/runs/<run-id>/config.json`.
Target repositories may use `.ai-scientist/config.json` as a config override for
plugin defaults from `plugins/ai-scientist/config/config.json`.

Example:

```bash
ai-scientist \
  --target-repo . \
  ideation start \
  --run-id ideation-001 \
  --prompt "Generate ideas for improving the current benchmark without changing the split." \
  --num-ideas 10
```

Ideation writes terminal ideas to `.ai-scientist/runs/<run-id>/ideas.json`.
`ideation complete` produces a research-ready handoff only; it does not start the
research loop. `EXHAUSTED_NO_CANDIDATE` is terminal for the Stop hook but still
fails the `ideation_to_research` validator.
