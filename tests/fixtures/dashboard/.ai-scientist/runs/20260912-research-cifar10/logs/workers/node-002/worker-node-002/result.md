# node-002 — worker result

**Status:** `accepted`

## Summary
Label smoothing + cosine LR on top of mixup, +0.003

## Todos
- [x] Materialize workspace and verify the frozen split
- [x] Implement the change described in the seed idea
- [x] Run the evaluator command on the official split
- [ ] Sweep two more seeds if the first result holds

## Evidence
| metric | value |
|---|---|
| accuracy | 0.934 |
| trials | see `node.json` |

Commands and stdout live under `logs/workers/node-002/worker-node-002/`.
