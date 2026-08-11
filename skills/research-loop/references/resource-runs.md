# Resource-Heavy Work

The orchestrator owns resource queue decisions; workers execute released jobs.

## Policy

- Read resource caps and scheduler constraints from the frozen `config.md`; do not infer hardware availability from assumptions.
- The orchestrator does not run long official benchmark commands itself.
- Before release, inspect recorded leases, the resource queue, and current host capacity.
- A worker receives a resource-heavy job only after the orchestrator records it as `released` with its worker/thread ID, assignment ref, result path, working directory, command, and requested resources.
- Record every official command under `logs/resources/<work-id>/<lease-id>/`: command specification, allocation, stdout, stderr, exit status, and release details.
- Record resource decisions and outcomes through `$research-loop-checkpoint` so workers, the orchestrator, and the ranker can distinguish scientific failure from environment or capacity failure.

## Queue Handling

- If capacity is unavailable, record the job in `state.resource_queue.pending`, continue independent work, and revisit it on the next scheduling sweep.
- If capacity is available, assign the job to its node worker and record it in `state.resource_queue.released`.
- When the worker returns terminal evidence, integrate the result and move the queue item to `state.resource_queue.completed`.

## Failure Handling

- If a job fails from OOM or exhaustion while capacity was uncertain, wait for capacity and retry once when justified.
- If failure persists while the request fits frozen caps, ask the worker to reduce memory pressure, batch work, checkpoint, or repair the implementation.
- If the request cannot fit the frozen caps, record a blocker or revise the implementation plan; do not spin.
