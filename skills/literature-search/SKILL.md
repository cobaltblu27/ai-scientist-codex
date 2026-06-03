---
name: literature-search
description: Query literature evidence for ideation using OpenAlex first, with Semantic Scholar as fallback.
---

# Literature Search

<Purpose>
Use this skill when the ideation loop needs paper evidence, baseline references, novelty checks, or related-work raw material. The agent using this skill chooses queries and evidence relevance; the CLI executes API calls, caching, provenance, and state updates.
</Purpose>

<Use_When>
- Ideation cursor asks for literature evidence.
- A generator needs papers before drafting or revising an idea.
- A critic asks for reference/baseline evidence.
- A performance idea needs a comparable paper, model, or benchmark source.
</Use_When>

<Who_Uses_It>
Generator subagents should use this skill directly when they need literature raw material for an idea. The main ideation orchestrator may also use it as a backstop when the cursor still reports missing literature evidence.
</Who_Uses_It>

<Provider_Order>
Use OpenAlex first. Semantic Scholar is fallback only when OpenAlex fails or is explicitly requested.

Default CLI behavior:

```bash
ai-scientist \
  --target-repo <target-repo> \
  idea search-semantic-scholar \
  --run-id <run-id> \
  --idea-id <idea-id> \
  --query "<query>"
```

Despite the historical command name, `--provider auto` means OpenAlex first, then Semantic Scholar fallback.
</Provider_Order>

<Generator_Workflow>
When used by a generator subagent:

1. Start from the assigned topic, mode, idea id, and result path.
2. Form 1-3 targeted queries before drafting the final idea.
3. Run the CLI command for the assigned `idea_id`; do not use raw `curl`.
4. Read the recorded evidence refs from the CLI response or `.ai-scientist/runs/<run-id>/loop-state.json`.
5. Use the evidence to choose or reject baseline references, benchmark plans, and novelty claims.
6. Return the final idea JSON to the assigned generator result path.
</Generator_Workflow>

<OpenAlex_Query_Guide>
OpenAlex search works best with concise paper-topic queries:

- include dataset/task name, metric, and method family when known;
- include "benchmark", "baseline", "state of the art", or the model family for performance ideas;
- avoid long natural-language paragraphs;
- run multiple targeted queries rather than one broad query.

Good examples:

- `drug target affinity Davis KIBA baseline graph neural network`
- `ADMET benchmark data leakage scaffold split`
- `molecular property prediction scaffold split baseline graph transformer`
</OpenAlex_Query_Guide>

<Fallback_Rule>
If OpenAlex fails through timeout, network error, malformed response, or service error, allow the CLI auto provider to fall back to Semantic Scholar. Do not manually retry OpenAlex many times inside ideation. Record the returned provider, fallback source, fallback reason, evidence ref, and result count from the CLI response/state.
</Fallback_Rule>

<Evidence_Use>
The literature search does not write the idea for the agent. Use returned papers as raw material:

- identify plausible baseline/reference papers;
- check whether the idea is already obvious or saturated;
- extract benchmark protocols and comparable metrics;
- revise `research_contract.baseline_reference`, `benchmark_plan`, and `target_threshold` when needed;
- reject ideas whose only support is a weak title match.
</Evidence_Use>

<Boundaries>
Do not call APIs directly with `curl` or ad hoc scripts. Subagents may run the `ai-scientist` CLI literature command. The CLI owns provider calls, cache files, logs, budgets, fallback, and provenance; the subagent owns query choice and interpretation.
</Boundaries>
