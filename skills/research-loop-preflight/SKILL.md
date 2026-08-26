---
name: research-loop-preflight
description: Validates the prerequisites for starting an AI Scientist research loop and creates its active goal. Use only when explicitly called before a new research-loop run; do not invoke implicitly or for resuming an existing run.
---

# Research Loop Preflight

<Purpose>
Validate the inputs and repository prerequisites for a new AI Scientist research-loop run, then create the active goal that will own the loop.
</Purpose>

<Use_When>
- The user explicitly calls `$research-loop-preflight` before initially starting a research loop.
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

<Setting_Goal>
When the run is ready to start, first set a goal using `create_goal`.

Set the goal as follows:

```text
Follow the $research-loop skill guide to achieve the following:
- Perform experiments using subagents
- From the results, find what can be done to improve the architecture.
- Continue improving the research tree to iteratively enhance the model architecture.
- The goal is finished when we have a node that meets the success criteria, or a given halt criterion is met.
- Include additional pause criteria such as token or time constraints only when they are given by the user.

The research-loop may be long-running, but duration alone neither requires stopping nor justifies creating work. Continue while contract-relevant runnable work remains; explicitly retire advisory or unsupported work.
```
</Setting_Goal>
</Goal_Preflight>

<Next_Step>
After all checks pass and the goal is created, explicitly call `$research-loop-bootstrap` to freeze the run configuration and initialize its Markdown artifacts.
</Next_Step>
