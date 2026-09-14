# Frontend Dashboard
Frontend is managed using auxiliary cli.
Running `ai-scientist dashboard` launches a dashboard that watches and visualizes runs and nodes inside `./.ai-scientist`.

## Stack
React, TypeScript and Vite. Built artifact is served by the Python CLI.

## Layout
- `src/dashboard/` — Python side. `scan.py` reads `.ai-scientist/` into plain JSON (read-only, lenient to half-written artifacts). `server.py` is a stdlib HTTP server exposing `/api/overview`, `/api/runs/<run-id>`, `/api/runs/<run-id>/nodes/<node-id>` and the built frontend.
- `src/frontend/` — Vite app. Left sidebar lists loop runs (active / finished) and contracts; main pane shows the overview or one run (node tree, journal tail, next action, selection, phase progress). Polls the API every 3s.
  - `components/NodeGraph.tsx` + `lib/graph.ts` — the node tree. SVG on a dotted whiteboard, left to right, one column per depth, orthogonal edges with rounded corners. Edges on a branch with live work are green with a flowing dash; closed branches are grey. Node ring/fill animates per status kind (`lib/format.ts: statusKind`). Hover shows a summary card, click opens the modal.
  - `components/NodeModal.tsx` — status (official + node.json), result/metrics/checks, report tabs (Markdown via `marked`), and the per-node history built from journal events, `state.work` items and report files.

## Artifact contract the dashboard reads
Everything below is written by agents; the dashboard only reads it. Paths are relative to `.ai-scientist/runs/<run-id>/`.

| what | file | fields used |
|---|---|---|
| node | `nodes/<node-id>/node.json` | `node_id`, `status`, `parent_node_id` (null/absent = root), `metrics`, `result_summary`, `current_claim`, `outcome_type`, `trials`, `split_integrity`, `leakage_check`, `novelty`, `rejection_reason`, `failure_signature`, `worker_recommendation` |
| official node ledger | `loop-state.json` → `state.nodes.<node-id>` | `status` (wins over node.json for colouring/liveness), `parent_node_id` (fallback), `updated_at` |
| work ledger | `loop-state.json` → `state.work.<work-id>` | `node_id` (ties the row to a node), `status`, `updated_at`, `result_ref` |
| worker report | `logs/workers/<node-id>/<worker-id>/result.md` | rendered as Markdown; `<worker-id>` is shown as the agent name |
| revision report | `logs/revisions/<node-id>/<revision-id>/result.md` | same |
| history | `journal.jsonl` | records with `node_id == <node-id>`, or `subagent_id` equal to one of the node's work ids; `details.status` |

Liveness: a node is live when its effective status is one of `planned pending queued implementing running experimenting buggy repairing revising candidate validating`. An edge is live when anything in the child's subtree is live.
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
`tests/fixtures/dashboard/.ai-scientist` holds a generated tree with 7 runs (ideation, live research campaign, blocked research, review, completed writeup, cancelled, half-written) and 3 contracts (one malformed). Regenerate with fresh timestamps:
```sh
python3 tests/fixtures/dashboard/make_fixture.py
ai-scientist --target-repo tests/fixtures/dashboard dashboard --open
```
