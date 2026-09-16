---
name: research-loop-preflight
description: Validates the prerequisites for starting an AI Scientist research loop. Use only when explicitly called by research-loop before a new run; do not invoke for resuming an existing run.
---

# Research Loop Preflight

<Purpose>
Validate the inputs and repository prerequisites for a new AI Scientist research-loop run.
</Purpose>

<Use_When>
- The explicitly invoked research-loop calls `ai-scientist:research-loop-preflight` before initially starting a run.
- A new research-loop run needs its target idea, environment, repository, dependencies, and benchmark contract checked before orchestration begins.
</Use_When>

<Do_Not_Use_When>
- The user has not explicitly called this skill.
- The research loop is being resumed from an existing run.
- The user only wants an explanation of the research-loop workflow.
</Do_Not_Use_When>

<Goal_Preflight>
When initially starting research-loop, without continuing from a previous loop, read and follow these instructions before starting. DO NOT PROCEED WITHOUT COMPLETING NEEDED STEPS.

- Is the "Target Idea" specified? If not, exit immediately and ask for an idea.
- Is the Python environment given? If it is not explicitly mentioned, and you cannot find an obvious environment in `AGENTS.md`, `pyproject.toml`, `.envrc`, `.venv`, or similar workspace documentation, exit immediately and ask for the Python environment. Global Python does not count unless explicitly requested.
- Is the target repository initialized as Git with at least one commit? If `git rev-parse --is-inside-work-tree` fails or `git rev-parse HEAD` fails, exit immediately and ask the user to initialize Git and create an initial commit before starting. Node workspaces use Git worktrees by default, so a commit is required for reproducible isolation.
- Read the idea and consider what the implementation would look like. Identify likely dependencies. If required dependencies are not installed, exit and ask the user to install them. The user may install the dependency, explicitly authorize you to install it, or choose to run the loop without it.
- Check the benchmark contract. For campaign mode, verify that the fixed dataset, split/protocol, baseline, metric(s), evaluator command, and target threshold are already defined. If a prerequisite dataset, checkpoint, baseline artifact, or evaluator asset is missing, exit immediately and ask the user to provide it.

</Goal_Preflight>

<Next_Step>
After all checks pass, invoke `ai-scientist:research-loop-bootstrap` through Claude Code's Skill tool to freeze the run configuration and initialize its artifacts. `/goal` provides persistence; durable run state provides resume context.
</Next_Step>
