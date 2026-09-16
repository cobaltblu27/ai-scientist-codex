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

Use `/goal` for workflow persistence in both Claude Code and Codex.

Reserve the CLI for artifact shape. Because skills hand-write state, the CLI is what keeps that state parseable and comparable across runs. Validation of a written artifact belongs here even though the writing does not.

Everything else, including orchestration policy, branching and ranking decisions, resource pacing, and evidence standards, belongs in prompts. Move a rule into the CLI only when real-world runs prove the prompt version does not hold.

## Criteria
- Each step is a loop that must continue until the criteria is met.

## Skills Policy
Skills in this project are mostly a dedicted tool for specific usuage; do not make them trigger without explicit calling.

## Compatibility
When editing prompts, you do not usually have to worry to much about backward compatibility, as we rarely have to handle continueing from previous runs. So when editing prompts to change behavior from A to B, refrain from terms like 'do not ~<previous behaviour>' or '~is not ~<previous prompts>', unless previous behavour seems to be a common fail case that can happen unless negative prompt is specified. Most of the time, agent won't know what was the previous version's instruction anyways.

## Prompt Flexibility
Specify the goal, decision, evidence requirements, and non-negotiable boundaries while leaving report structure and depth flexible. Avoid mandatory return forms with long field lists, especially forms with ten or more fields or repeated per-item schemas, because agents may focus on completing the form instead of producing a strong result. Prefer a few content goals in natural Markdown and request additional sections or details only when relevant. Keep exact machine-readable fields in CLI state or artifact schemas instead of duplicating them in prose reports. Use a rigid output format only when a parser or CLI genuinely requires it, and keep that format to the minimum required fields.

# Documentation
Project documentation lives in `docs/`. Only `AGENTS.md` and `CLAUDE.md` stay at the repository root because they must be read before anything else. New Markdown documents go in `docs/`, never at the root.

- `docs/SCHEMA.md` is the ground truth for every file under `.ai-scientist/`. Skills and agents write those files; the CLI validates them; the dashboard reads them. When a prompt, a JSON schema, the validator, or the scanner disagrees with `docs/SCHEMA.md`, fix the other side. When a skill starts writing a new artifact, add it to `docs/SCHEMA.md` in the same change.
- `docs/README.md` is the user-facing overview, `docs/GUIDELINES.md` the maintainer rules, `docs/PLAN.md` the campaign design, `docs/FRONTEND.md` the dashboard plan.

# CLI
When developing CLI features, you may use git issues for keeping track of non-trivial tasks.

## Dashboard
Dashboard is additional package for running frontend, for monitoring and allowing human-in-the loop research in research loop.
Read `docs/FRONTEND.md` for frontend development and checking its plans, and `docs/SCHEMA.md` for what the scanner may read.

## CLI
ai-scientist cli, used for maintaining session and backend for dashboard.

# Issues
Non-trivial tasks will be managed using github issues. 
When working based on an issue, make sure to check them occasionally for updates.
You may also use git worktrees for simulateous editing using subagents.


