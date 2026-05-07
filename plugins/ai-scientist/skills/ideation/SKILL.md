---
name: ideation
description: Generate structured research ideas from a prompt and initialize non-mutating .ai-scientist/ ideation artifacts for a target repository.
---

# Ideation

Use this skill when the user wants research ideas, hypotheses, or experiment proposals before running a research loop. This skill is backed by the Codex-native ideation orchestrator at `plugins/ai-scientist/scripts/ideation_orchestrator.py`.

## Inputs

- A prompt input describing the research goal, target benchmark, constraints, and desired strictness mode.
- Optional target repository path for artifact placement.
- Optional literature lookup budget. `S2_API_KEY` is required before the orchestrator starts because Python performs Semantic Scholar lookup directly.
- Optional `num_ideas` and `num_reflections` settings. Defaults are `10` ideas and `5` reflection rounds per idea.
- Optional `--codex-model` and `--codex-reasoning-effort`. Production defaults are `gpt-5.5` and `xhigh` so ideation is a deliberate research process, not a quick ticket generator.

## Workflow

1. Clarify the benchmark, dataset/split policy, and default strictness mode (`scientist`) when missing.
2. Do not mutate target repo code during ideation. The only permitted target repo writes are `.ai-scientist/` artifacts.
3. Run the orchestrator from the repository root:

   ```bash
   S2_API_KEY="$S2_API_KEY" python3 plugins/ai-scientist/scripts/ideation_orchestrator.py \
     --target-repo <target-repo> \
     --prompt "<research prompt>" \
     --num-ideas 10 \
     --num-reflections 5
   ```

4. The orchestrator must launch Codex agent tasks for proposal, reflection/refinement, and finalization. Python owns loop state, Semantic Scholar search, and artifact writes; Codex agents own idea reasoning.
5. Semantic Scholar lookup is performed by Python and logged to `.ai-scientist/runs/<run-id>/api-ledger.jsonl`.
6. Intermediate orchestration artifacts are retained under `.ai-scientist/logs/<run-id>/` as JSON audit files.
7. Finalized ideas are written to `.ai-scientist/ideas/ideas.json` using the idea schema. A finalized idea must include a falsifiable hypothesis, scientific insight, related work, conference-style abstract, novelty rationale, required data, expected metric, execution plan, experiments, risks, and minimum evidence. Ideas that do not finalize within the reflection budget are skipped and logged.
8. The orchestrator creates the ideation run artifacts and runs `plugins/ai-scientist/scripts/validate_run.py <target> --gate ideation_to_research --run-id <run-id>` before handing off to research.

## Output contract

Return a concise idea summary and artifact paths. The canonical ideas output is JSON in `.ai-scientist/ideas/ideas.json`; prose summaries are secondary and must not replace the JSON artifact.

Key generated paths:

- `.ai-scientist/ideas/ideas.json`
- `.ai-scientist/logs/<run-id>/ideation-run.json`
- `.ai-scientist/logs/<run-id>/agents/*.json`
- `.ai-scientist/runs/<run-id>/api-ledger.jsonl`
- `.ai-scientist/runs/<run-id>/run-status.json`
- `.ai-scientist/runs/<run-id>/handoff.jsonl`
