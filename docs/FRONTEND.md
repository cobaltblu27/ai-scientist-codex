# Frontend Dashboard
Frontend is managed using auxiliary cli.
Running `ai-scientist dashboard` launches a dashboard that watches and visualizes runs and nodes inside `./.ai-scientist`.

## Stack
React, TypeScript and Vite. Built artifact is served by the Python CLI.

## Layout
- `src/dashboard/` — Python side. `scan.py` reads `.ai-scientist/` into plain JSON (read-only, lenient to half-written artifacts). `server.py` is a stdlib HTTP server exposing the API below and the built frontend.
- `src/frontend/` — Vite app. Left sidebar lists loop runs (active / finished) and contracts; main pane shows the overview or one run (node tree, journal tail, next action, selection, phase progress). Polls the API every 3s.
  - `components/NodeGraph.tsx` + `lib/graph.ts` — the node tree. SVG on a dotted whiteboard, left to right, one column per depth, orthogonal edges with rounded corners. Edges on a branch with live work are green with a flowing dash; closed branches are grey. Node ring/fill animates per status kind (`lib/format.ts: statusKind`). Hover shows a summary card, click opens the modal.
  - `components/NodeModal.tsx` — status, result metric, assignment / evidence / next action, work items, leftover ledger keys, report tabs (Markdown via `marked`), and the per-node history built from journal events, `state.work` items and report files.
  - `components/ReportPane.tsx` — run-level Markdown reports, opened on demand through the files route. Ideation runs show `ideas.json` and `run.md` instead of the node tree.

## Artifacts the dashboard reads
Everything is agent-written; the dashboard only reads. Shapes and required keys are defined in [`SCHEMA.md`](SCHEMA.md), section 4 lists what each view uses. Summary:

| view | files | uses |
|---|---|---|
| overview | `loop-state.json` (research family) or `run.md` (ideation); `config.md` frontmatter; contract file; `ideas.json`; `contracts/*/research-contract.json` | phase, `phase_status`, `active`, `next_action`, `selection.selected_node`, `primary_metric`, `success_threshold`, goal, idea and node counts |
| run | above plus `journal.jsonl`, `selection.json`, `baseline/baseline.json`, `links`, every `*.md` under the run root and `logs/` | node ledger (`state.nodes`) with depth from `parent_node_id`, work grouped by `node`, raw `resources` / `resource_queue` / `open_questions`, report list, journal tail |
| node | ledger entry, `state.work` entries whose `node` matches, journal records whose `node_id` matches, files named by `result_ref` | status, assignment, evidence summary, metrics, work list, history, report contents |

Liveness: a node or work item is live when its `status` is not one of `completed cancelled failed abandoned accepted rejected`. The graph animates a few conventional live words (`planned`, `queued`, `implementing`, `revising`, `blocked`, `candidate`) and treats any other live word as "experimenting". An edge is live when anything in the child's subtree is live.

API: `/api/overview`, `/api/runs/<run-id>`, `/api/runs/<run-id>/nodes/<node-id>`, `/api/runs/<run-id>/files/<run-relative-path>` (text files only, path-checked to stay inside the run).
- `references/ui-reference.jpg` — visual reference for the design language (cream ground, ink sidebar, lime / pink / orange accents, rounded tiles).

## Commands
```sh
# build once (required before `ai-scientist dashboard` can serve the UI)
cd src/frontend && npm install && npm run build

# serve a target repo's artifacts
ai-scientist --target-repo <repo> dashboard [--host 127.0.0.1] [--port 8765] [--open]

# frontend dev loop: hot reload, /api proxied to the Python server on :8765
ai-scientist --target-repo <repo> dashboard   # terminal 1
cd src/frontend && npm run dev                # terminal 2
```

## Plans
- Node detail view (trials, critic reviews, metrics history).
- Human-in-the-loop actions (approve / reject / annotate) wired to CLI commands.
- Live updates via file watching instead of polling.

## Dummy data
`tests/fixtures/dashboard/.ai-scientist` is generated from `make_fixture.py` following `SCHEMA.md`: a research run mid-loop with branches, one `success` with `selection.json`, one `exhausted`, one `blocked`, one ideation run, one broken `loop-state.json`, and contracts including a malformed one. Timestamps are pinned so the tree is deterministic.
```sh
python3 tests/fixtures/dashboard/make_fixture.py
ai-scientist --target-repo tests/fixtures/dashboard dashboard --open
```
