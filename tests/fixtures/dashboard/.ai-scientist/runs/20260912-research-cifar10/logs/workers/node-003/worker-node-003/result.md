# node-003 — worker result

**Status:** `invalid`

## Summary
OOM during squeeze-excite training at batch 512

## Todos
- [x] Materialize workspace and verify the frozen split
- [x] Implement the change described in the seed idea
- [ ] Run the evaluator command on the official split
- [ ] Sweep two more seeds if the first result holds

## Evidence
| metric | value |
|---|---|
| accuracy | — |
| trials | see `node.json` |

Commands and stdout live under `logs/workers/node-003/worker-node-003/`.
