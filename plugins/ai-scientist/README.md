# AI Scientist Codex Plugin

This plugin provides Codex-native research workflows inspired by AI-scientist style automation without wrapping or invoking any external reference implementation. It is skill-first and stores auditable run state in the target repository under `.ai-scientist/`.

## Skills

- `ideation` — run a Codex-agent ideation loop from a prompt, with Python-managed Semantic Scholar search, reflection/refinement, finalization, and non-invasive artifacts.
- `research-loop` — plan dependencies, run bounded experiments, log API use, and enforce phase gates.
- `review` — evaluate evidence for leakage, split integrity, baseline comparison, and mode criteria.
- `writeup` — generate a final report with explicit disclosure, limitations, and negative-result handling.

## Artifact contract

See `references/artifact-contract.md`. Validate run artifacts with:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate ideation_to_research
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate research_to_review
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate review_to_writeup
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate launch
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate principles
```

The validator is deterministic and fail-closed: missing evidence, malformed JSON/JSONL, non-approved handoffs, non-zero validator exits, no-go verifier decisions, or incomplete principle traceability return a non-zero exit.

## Ideation orchestrator

The ideation skill is backed by:

```bash
plugins/ai-scientist/scripts/ideation_orchestrator.py
```

It reads a research prompt directly, requires `S2_API_KEY`, launches Codex agent tasks for proposal/reflection/finalization, and stores intermediate JSON audit logs under `.ai-scientist/logs/<run-id>/`.

Example:

```bash
S2_API_KEY="$S2_API_KEY" python3 plugins/ai-scientist/scripts/ideation_orchestrator.py \
  --target-repo . \
  --prompt "Generate ideas for improving the current benchmark without changing the split." \
  --num-ideas 10 \
  --num-reflections 5
```
