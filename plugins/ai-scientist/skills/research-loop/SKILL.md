---
name: research-loop
description: Execute bounded Codex-native experiment loops with dependency planning, API ledgers, strictness modes, metric contracts, runtime mutation checks, and fail-closed .ai-scientist/ phase gates.
---

# Research Loop

Use this skill to run selected ideas against a target repository while preserving benchmark and split integrity. The workflow is Codex-native: no runtime import, shell invocation, or wrapper dependency on `AI-Scientist-v2`.

## Required CLI shape

A research run must declare the benchmark contract explicitly:

```bash
python3 plugins/ai-scientist/scripts/research_orchestrator.py \
  --target-repo <repo> \
  --idea-json <idea.json> \
  --strictness-mode balanced \
  --baseline-command '<command>' \
  --metric-key <metric-name> \
  --metric-direction maximize \
  --success-threshold <optional-number> \
  --split-policy '<fixed split description>' \
  --agent-runner codex
```

Use `--metric-direction minimize` for losses/errors. Fresh targets without `.ai-scientist/` require `--idea-json` so the orchestrator can create `.ai-scientist/ideas/ideas.json` non-destructively.

## Required artifacts

All run state lives under `.ai-scientist/`. Research validation expects run-owned governance artifacts: `research-plan.json`, `dependency-plan.json`, `dependency-status.json`, `api-ledger.jsonl`, `principles.json`, `run-status.json`, `selection.json`, `dispatcher-events.jsonl`, `handoff.jsonl`, `verifier-decisions/research_to_review.json`, and launch-only `verifier-decision.json`.

`run-status.json.last_validations.<gate>` is authoritative. `last_validation` is still written and read as a legacy fallback.

## Strictness modes

Default mode is `balanced` unless the orchestrator/target config chooses otherwise.

- `scientist`: reproducibility note, experiment rationale, split/leakage evidence, ablation summary, tuning summary, limitations.
- `researcher`: rationale, related-risk notes, reproducibility note, ablation or sensitivity evidence, limitations.
- `balanced`: rationale, split/leakage evidence, result summary, and at least one validation-oriented deliverable.
- `builder`: runnable artifact summary, command log, metrics, integration notes, known risks.
- `engineer`: minimal patch/experiment summary, command log, metrics, rollback notes.

No mode permits leakage, split manipulation, deceptive scoring, unapproved dependency use, or unexpected repository mutation.

## Dependency, API, and mutation controls

1. Plan dependencies before execution in `dependency-plan.json`.
2. Record approvals in `dependency-status.json`; blocked/unapproved dependencies block handoff.
3. Log external API/model usage, or explicit no-calls fixture evidence, to `api-ledger.jsonl`.
4. Codex agents return manifests only. Python validates paths and materializes files inside the node workspace.
5. Every baseline/node command records `runtime-mutation-check.json`; unexpected mutations outside allowed `.ai-scientist/`/workspace paths block selection and handoff.

## Workflow

1. Map the target repo, dataset, loader, benchmark, metric key/direction, threshold, and split policy.
2. Create baseline artifacts: command log, metrics, split/leakage checks, and runtime mutation evidence.
3. For each experiment node, emit `prompt.json` with action/mode/metric metadata before agent execution, validate the manifest, run bounded commands, and record metrics, resource usage, split/leakage, mutation checks, result summary, and mode deliverables.
4. Write `selection.json` naming the selected node and direction-aware comparison to baseline.
5. Run evidence validation before any handoff:

   ```bash
   python3 plugins/ai-scientist/scripts/validate_run.py <target> \
     --gate research_to_review --run-id <run-id> --validation-mode evidence
   ```

6. Only after evidence validation exits 0, write validation metadata to both `last_validation` and `last_validations.research_to_review`, append the approved `handoff.jsonl` record, and write `verifier-decisions/research_to_review.json` with `approved|blocked|rejected`.
7. Run final transition validation:

   ```bash
   python3 plugins/ai-scientist/scripts/validate_run.py <target> \
     --gate research_to_review --run-id <run-id> --validation-mode final
   ```

A non-zero evidence or final validator exit blocks review. Do not substitute launch `verifier-decision.json` (`go|no_go`) for the gate-specific verifier decision.

## Completion

Return the selected node, metric key/direction, baseline and selected metric values, threshold result if present, leakage/split status, mutation-check status, strictness mode, evidence/final validation commands, and artifact paths. Report negative or blocked outcomes honestly.
