# Specs
This is a project to implement AI-Scientist-v2 into a codex plugin.
This plugin aims to make four steps of AI-scientist-v2: Ideation, research-loop, review, and writeup, into four skills of codex.


## Purpose
This agent orchestration framework will be mostly AI-focused researches. Behaviours should be based on which "mode" is chosen.

## Repositories for reference
- AI-Scientist-V2 is a repository of automated research harness using llm. this plugin is inspired from it; and design for each step, ideation, research loop and so on are influenced from it.
- Oh-My-Codex is a codex all-in-one toolkit. We'll adapt its methodology for consistent state managment, agent orchestration, and keeping the loop ongoing until a criteria is met.

## Agent Prompting
Many specs to add will require change of CLI or prompt. Same feature can be implemented as both, where addition to prompts such as SKILL.md is soft enforcement and change to CLI is a deterministic hard-rule. Sometimes you will need to determine where to change. Good rule of thumb to decide is: If it's related with loop state criteria, such as STOP hook, budget, etc, it belongs in CLI. If its not, it can be either, but prioritize prompt editing first. CLI-based hard rule enforcement is revered when real-world testing proves it is needed.

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
