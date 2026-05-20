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

## Ideation loop

The ideation skill is hook/state driven. Start it with an explicit marker:

```bash
/ideate Generate ideas for improving the current benchmark without changing the split.
```

Codex performs proposal, reflection, and finalization in the live session. Python helpers only manage durable state, one-shot Semantic Scholar lookup, snapshots, strict idea validation, filesystem-diff checks, and phase-gate artifacts. `S2_API_KEY` is optional; without it Semantic Scholar may rate-limit more aggressively.

Finalized ideas are proposal-grade records, not bare metric tickets. The idea schema requires a falsifiable hypothesis, actual scientific insight, concrete related work, conference-style abstract, novelty rationale, required data, expected metric, executable step-by-step plan with dataset/model/evaluation fields, experiments, risks, and minimum evidence.

The historical `scripts/ideation_orchestrator.py` entrypoint now initializes hook-driven state for compatibility; it does not launch nested Codex agents.
