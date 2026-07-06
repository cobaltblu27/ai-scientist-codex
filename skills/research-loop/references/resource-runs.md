# Resource Runs

Use `resource run` for official or heavy benchmark evidence. The orchestrator owns queue decisions; workers execute released jobs.

## Policy

- Read resource caps from run config. Do not infer hardware.
- Execution backend is separate from orchestrator scheduling and resource caps.
- Use `resource status` to inspect active leases and available capacity.
- The orchestrator must not run long official benchmark commands itself.
- A Codex worker invokes `resource run` only after the orchestrator assigns or releases the queued job to that worker.
- Official GPU benchmark and final-validation commands must go through `resource run`; do not run raw `python`, `uv run`, `conda run`, or ad hoc `sbatch --wrap` for official evidence.
- Record resource decisions and outcomes in worker reports or checkpoints so critics can distinguish scientific failure from resource/environment failure.

## Local Example

```bash
ai-scientist --target-repo <target-repo> resource run \
  --run-id <run-id> \
  --task-id <work-id> \
  --cwd .ai-scientist/runs/<run-id>/nodes/<node-id>/workspace \
  --purpose benchmark \
  --gpus 1 \
  --cpu-cores 4 \
  --memory-mb 8192 \
  --timeout-sec 3600 \
  --poll-sec 30 \
  -- <command ...>
```

`resource run` acquires a lease, writes `logs/resources/<work-id>/<lease-id>/command.json`, `stdout.log`, and `stderr.log`, executes through the configured scheduler backend, then releases the lease in `finally`.

## Slurm Example

HPC runs should freeze `resources.scheduler.type: "slurm"` and explicit Slurm options in run config, or pass matching `resource run` flags.

```bash
ai-scientist --target-repo <target-repo> resource run \
  --run-id <run-id> \
  --task-id <work-id> \
  --cwd .ai-scientist/runs/<run-id>/nodes/<node-id>/workspace \
  --purpose benchmark \
  --gpus 1 \
  --cpu-cores 8 \
  --memory-mb 32768 \
  --scheduler slurm \
  --partition gpu \
  --time 7-00:00:00 \
  --gres gpu:1 \
  --cpus-per-task 8 \
  --mem 32G \
  -- <command ...>
```

The Slurm backend writes a generated job script under the resource log directory and records the `sbatch` argv, Slurm job id, stdout/stderr paths, and exit code in `command.json`.

## Queue Handling

- If resources are not available, checkpoint the job in `state.resource_queue.pending`, sweep other nodes, and retry queue triage on the next resume.
- If resources are available, assign the job to the node worker and checkpoint it in `state.resource_queue.released` with `job_id`, `agent_thread_id`, `assignment_ref`, and `result_ref`.
- When the worker returns terminal benchmark evidence, integrate evidence refs and move the queue item to `state.resource_queue.completed`.

## Failure Handling

- If the heavy run fails with OOM/resource exhaustion while resources were busy or uncertain, wait for resources to free and retry once when justified.
- If OOM/resource exhaustion persists when resources are free and the request fits configured caps, prompt the worker to reduce memory pressure, batch work, checkpoint, or otherwise fix the implementation.
- If the request cannot ever fit configured caps, record a blocker or revise the implementation plan; do not spin.
