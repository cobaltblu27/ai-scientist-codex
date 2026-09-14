---
name: research-loop-bootstrap
description: Initializes a new AI Scientist research-loop run by freezing validated startup inputs into Markdown and creating its durable run artifacts. Use only when explicitly called after research-loop-preflight; never invoke implicitly or for an existing run.
---

# Research Loop Bootstrap

<Purpose>
Replace command-based bootstrap with a small, human-readable run initializer. Freeze the validated startup contract in Markdown and create the durable files needed to resume the `/goal` research campaign.
</Purpose>

<Use_When>
- The research-loop invokes `ai-scientist:research-loop-bootstrap` after `ai-scientist:research-loop-preflight` passes.
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
- frozen research contract;
- resource policy, if supplied;
- ranking and active-node limits, if supplied.
</Inputs>

<Workflow>
1. Choose a stable run ID. Resolve `.ai-scientist/runs/<run-id>/` under the target repository.
2. Fail immediately if that run directory or its `config.md` already exists. Never overwrite an existing run during bootstrap.
3. Create the run directory and `logs/` directory.
4. Write `config.md` with YAML frontmatter containing the immutable startup values; the frontmatter carries at least `run_id`, `contract_path`, `idea_batch`, `primary_metric`, and `success_threshold`. Include the full idea identities and binding contract in the Markdown body or as clearly referenced artifacts.
5. Write `loop-state.json` with the schema-required top-level fields and initial state below:

   - `schema_version: 1`, the run ID, `active: true`, `phase: research`, `phase_status: running`, and UTC `updated_at`;
   - `state.orchestrator.next_action: plan`;
   - `state.nodes`, `state.work`, `state.tasks`, `state.resources`, `state.resource_queue`, and `state.selection` as empty objects;
   - `state.baseline.status`: `not_required` unless the contract requires setup;
   - `links` with `config`, `contract`, `idea_batch`, `discovery_notes`, and `learning_notes`.

   Artifact shapes are defined in `docs/SCHEMA.md` (plugin repo); honor its required keys, everything else is free.

6. Create empty `learning-notes.md` and a starter `discovery-notes.md` with sections for current understanding, what worked, what failed, data/evaluation findings, transferable insights, branch seeds, and things to avoid repeating.
7. Create `.ai-scientist/active-run.json` with schema version 1, run ID, phase `research`, status `active`, UTC `updated_at`, and absolute target repository. Append an `event_type: setup` entry to `journal.jsonl` with `details.command: research-loop-bootstrap`.
8. Report the created paths and the next action: continue the already active `ai-scientist:research-loop` orchestration.
</Workflow>

<Config_Rules>
`config.md` is immutable run configuration. Do not put changing checkpoints, worker progress, resource leases, or selection decisions in it. Record those in `loop-state.json` and linked evidence files.

The frozen configuration must include enough information to resume without conversational memory: run ID, target repository, Python environment, idea IDs and seed identities, research contract, resource policy, active-node cap, ranking top `N`, and prompt/skill references.

Do not claim that the run is started until `config.md`, `loop-state.json`, `active-run.json`, and the notes files exist. Do not create nodes, spawn agents, run experiments, acquire resources, or modify the target implementation during bootstrap.
</Config_Rules>
