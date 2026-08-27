# Specs
This is a project to implement AI-Scientist-v2 into a codex plugin.
This plugin aims to make four steps of AI-scientist-v2: Ideation, research-loop, review, and writeup, into four skills of codex.


## Purpose
This agent orchestration framework will be mostly AI-focused researches. Every run holds one evidence standard; a run may add its own acceptance criteria on top, but never weaken the universal integrity rules.

## Repositories for reference
- AI-Scientist-V2 is a repository of automated research harness using llm. this plugin is inspired from it; and design for each step, ideation, research loop and so on are influenced from it.
- Oh-My-Codex is a codex all-in-one toolkit. We'll adapt its methodology for consistent state managment, agent orchestration, and keeping the loop ongoing until a criteria is met.

## Agent Prompting
Many specs to add will require change of CLI or prompt. Same feature can be implemented as both, where addition to prompts such as SKILL.md is soft enforcement and change to CLI is a deterministic hard-rule. Sometimes you will need to determine where to change.

Default to the prompt. Skills own the loop: they choose actions, write run artifacts under `.ai-scientist/runs/<run-id>/`, and decide when a phase is done. A skill writing `loop-state.json` or `active-run.json` directly is the normal path, not a workaround.

Reserve the CLI for the two things a prompt cannot guarantee:

1. **Enforcement that must hold even when the model misbehaves.** The Stop hook is the clearest case: it decides whether a session is allowed to stop, so it cannot live in prose the same session is free to ignore.
2. **Artifact shape.** Because skills hand-write state, the CLI is what keeps that state parseable and comparable across runs. Validation of a written artifact belongs here even though the writing does not.

Everything else, including orchestration policy, branching and ranking decisions, resource pacing, and evidence standards, belongs in prompts. Move a rule into the CLI only when real-world runs prove the prompt version does not hold.

## Criteria
- Each step is a loop that must continue until the criteria is met.

## Prompt format
When writing a new prompt, make sure the prompt follows a markdown + xml hybrid. there's no strict rule, but use xml tag when its good to mark the end of the block. here's the example:

```
---
name: ralph
description: Self-referential loop until task completion with architect verification
---

[RALPH + ULTRAWORK - ITERATION {{ITERATION}}/{{MAX}}]

Your previous attempt did not output the completion promise. Continue working on the task.

<Purpose>
Ralph is a persistence loop that keeps working on a task until it is fully complete and architect-verified. It wraps ultrawork's parallel execution with session persistence, automatic retry on failure, and mandatory verification before completion.
</Purpose>

<Use_When>
- Task requires guaranteed completion with verification (not just "do your best")
- User says "ralph", "don't stop", "must complete", "finish this", or "keep going until done"
- Work may span multiple iterations and needs persistence across retries
- Task benefits from parallel execution with architect sign-off at the end
</Use_When>

<Do_Not_Use_When>
- User wants a full autonomous pipeline from idea to code -- use `autopilot` instead
- User wants to explore or plan before committing -- use `plan` skill instead
- User wants a quick one-shot fix -- delegate directly to an executor agent
- User wants manual control over completion -- use `ultrawork` directly
</Do_Not_Use_When>
```

## Skills Policy
Skills in this project are mostly a dedicted tool for specific usuage; do not make them trigger without explicit calling.

## Compatibility
When editing prompts, you do not usually have to worry to much about backward compatibility, as we rarely have to handle continueing from previous runs. So when editing prompts to change behavior from A to B, refrain from terms like 'do not ~<previous behaviour>' or '~is not ~<previous prompts>', unless previous behavour seems to be a common fail case that can happen unless negative prompt is specified. Most of the time, agent won't know what was the previous version's instruction anyways.

## Prompt Flexibility
Specify the goal, decision, evidence requirements, and non-negotiable boundaries while leaving report structure and depth flexible. Avoid mandatory return forms with long field lists, especially forms with ten or more fields or repeated per-item schemas, because agents may focus on completing the form instead of producing a strong result. Prefer a few content goals in natural Markdown and request additional sections or details only when relevant. Keep exact machine-readable fields in CLI state or artifact schemas instead of duplicating them in prose reports. Use a rigid output format only when a parser or CLI genuinely requires it, and keep that format to the minimum required fields.
