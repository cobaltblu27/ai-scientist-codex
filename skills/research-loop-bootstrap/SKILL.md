---
name: research-loop-bootstrap
description: Initializes a new AI Scientist research-loop run by freezing validated startup inputs into Markdown and creating its durable run artifacts. Use only when explicitly called after research-loop-preflight; never invoke implicitly or for an existing run.
---

# Research Loop Bootstrap

<Purpose>
Replace command-based bootstrap with a small, human-readable run initializer. Freeze the validated startup contract in Markdown and create the files the orchestrator and Stop hook need for durable continuation.
</Purpose>

<Use_When>
- The user explicitly calls `$research-loop-bootstrap` after `$research-loop-preflight` passes.
- A new research-loop run needs its startup inputs frozen and its run directory initialized.
</Use_When>

<Do_Not_Use_When>
- The user has not explicitly called this skill.
- The run ID already exists and the user has not explicitly approved reinitialization.
- The task is to resume, checkpoint, schedule resources, or complete an existing run.
</Do_Not_Use_When>

<Inputs>
Use the validated values from the preflight and the user's explicit request:

- target repository;
- target idea or idea batch, including stable idea IDs;
- mode: `scientist`, `engineer`, or `custom`;
- frozen research contract or custom criteria;
- resource policy, if supplied;
- ranking and active-node limits, if supplied.
</Inputs>

<Workflow>
1. Choose a stable run ID. Resolve `.ai-scientist/runs/<run-id>/` under the target repository.
2. Fail immediately if that run directory or its `config.md` already exists. Never overwrite an existing run during bootstrap.
3. Create the run directory and `logs/` directory.
4. Write `config.md` with YAML frontmatter containing the immutable startup values. Include the full idea identities and binding contract in the Markdown body or as clearly referenced artifacts.
5. Write `loop-state.json` with the initial state below:

   - phase: `research`;
   - status: `active`;
   - next action: `plan`;
   - empty nodes, work items, tasks, resource queue, and selection;
   - baseline status: `not_required` unless the contract requires setup;
   - links to `config.md`, `discovery-notes.md`, and `learning-notes.md`.

6. Create empty `learning-notes.md` and a starter `discovery-notes.md` with sections for current understanding, what worked, what failed, data/evaluation findings, transferable insights, branch seeds, and things to avoid repeating.
7. Create `.ai-scientist/active-run.json` with the active research phase and append a `research bootstrap` entry to `journal.jsonl`. These compatibility files let state, resource, and Stop-hook utilities continue to work.
8. Report the created paths and the next action: start the orchestrator-led research loop using `$research-loop`.
</Workflow>

<Config_Rules>
`config.md` is immutable run configuration. Do not put changing checkpoints, worker progress, resource leases, or selection decisions in it. Record those in `loop-state.json` and linked evidence files.

The frozen configuration must include enough information to resume without conversational memory: run ID, target repository, mode, Python environment, idea IDs and seed identities, contract or custom criteria, resource policy, active-node cap, ranking top `N`, and prompt/skill references.

Do not claim that the run is started until `config.md`, `loop-state.json`, `active-run.json`, and the notes files exist. Do not create nodes, spawn agents, run experiments, acquire resources, or modify the target implementation during bootstrap.
</Config_Rules>
