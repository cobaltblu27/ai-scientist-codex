# node-004 — worker result

**Status:** `rejected`

## Summary
Leakage: test images in augmentation cache

## Todos
- [x] Materialize workspace and verify the frozen split
- [x] Implement the change described in the seed idea
- [x] Run the evaluator command on the official split
- [ ] Sweep two more seeds if the first result holds

## Evidence
| metric | value |
|---|---|
| accuracy | 0.951 |
| trials | see `node.json` |

Commands and stdout live under `logs/workers/node-004/worker-node-004/`.
