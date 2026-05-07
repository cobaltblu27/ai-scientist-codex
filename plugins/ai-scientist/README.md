# AI Scientist Codex Plugin

This plugin provides Codex-native research workflows inspired by AI-scientist style automation without wrapping, importing, or invoking any external reference implementation such as `AI-Scientist-v2`. It is skill-first and stores auditable run state in the target repository under `.ai-scientist/`.

## Skills

- `ideation` — run a Codex-agent ideation loop from a prompt, with Python-managed Semantic Scholar search, reflection/refinement, finalization, and non-invasive artifacts.
- `research-loop` — run bounded experiments with explicit metric contracts, prompt/manifests, runtime mutation checks, governance artifacts, and two-phase research handoff validation.
- `review` — evaluate evidence for leakage, split integrity, baseline comparison, and mode criteria.
- `writeup` — generate a final report with explicit disclosure, limitations, and negative-result handling.

## Artifact contract

See `references/artifact-contract.md`. Validate run artifacts with:

```bash
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate ideation_to_research
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate research_to_review --validation-mode evidence
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate research_to_review --validation-mode final
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate review_to_writeup
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate launch
python3 plugins/ai-scientist/scripts/validate_run.py <fixture-or-target-repo> --gate principles
```

`research_to_review` defaults to `--validation-mode final`. Evidence mode is for pre-handoff scientific/artifact validation and intentionally avoids circular requirements on handoff and gate-specific verifier decisions. Final mode requires the approved handoff plus `.ai-scientist/runs/<run-id>/verifier-decisions/research_to_review.json` with `decision: "approved"`.

The existing launch artifact `.ai-scientist/runs/<run-id>/verifier-decision.json` keeps its `go`/`no_go` semantics and is not used as the research handoff verifier decision.

The validator is deterministic and fail-closed: missing evidence, malformed JSON/JSONL, stale validation metadata, failed split/leakage checks, unexpected runtime mutations, non-approved handoffs, blocked gate verifier decisions, non-zero validator exits, no-go launch decisions, or incomplete principle traceability return a non-zero exit.

## Research loop metric contract

Research runs declare `metric_key` and `metric_direction` in `research-plan.json` and `selection.json`:

- `maximize`: selected metric must be greater than baseline; threshold means selected `>= success_threshold`.
- `minimize`: selected metric must be lower than baseline; threshold means selected `<= success_threshold`.

The selected node in `selection.json` is authoritative; validators do not infer success by taking the maximum legacy `score` across nodes.

## Ideation orchestrator

The ideation skill is backed by:

```bash
plugins/ai-scientist/scripts/ideation_orchestrator.py
```

It reads a research prompt directly, requires `S2_API_KEY`, launches Codex agent tasks for proposal/reflection/finalization, and stores intermediate JSON audit logs under `.ai-scientist/logs/<run-id>/`. Production ideation defaults to `--codex-model gpt-5.5 --codex-reasoning-effort xhigh`.

Finalized ideas are proposal-grade records, not bare metric tickets. The idea schema requires a falsifiable hypothesis, actual scientific insight, concrete related work, conference-style abstract, novelty rationale, required data, expected metric, executable step-by-step plan, experiments, risks, and minimum evidence.

Example:

```bash
S2_API_KEY="$S2_API_KEY" python3 plugins/ai-scientist/scripts/ideation_orchestrator.py \
  --target-repo . \
  --prompt "Generate ideas for improving the current benchmark without changing the split." \
  --num-ideas 10 \
  --num-reflections 5
```
