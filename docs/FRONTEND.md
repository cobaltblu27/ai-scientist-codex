# Frontend Dashboard
Frontend is managed using auxiliary cli.
Running `ai-scientist dashboard` launches a dashboard that watches and visualizes runs and nodes inside `./.ai-scientist`.

## Stack
React, TypeScript and Vite. `npm run build` writes `src/dashboard/dist/`, package data of the `dashboard` Python package, so the release wheel ships the built dashboard and the Python CLI serves it from wherever it is installed.

## Layout
- `src/dashboard/` — Python side. `scan.py` reads `.ai-scientist/` into plain JSON (read-only, lenient to half-written artifacts). `server.py` is a stdlib HTTP server exposing the API below and the built frontend.
- `src/frontend/` — Vite app. Left sidebar lists loop runs (active / finished) and contracts; main pane shows the overview or one run (node tree, journal tail, next action, selection, phase progress). Polls the API every 3s.
  - `components/NodeGraph.tsx` + `lib/graph.ts` — the node tree. SVG on a dotted whiteboard, left to right, one column per depth, orthogonal edges with rounded corners. Edges on a branch with live work are green with a flowing dash; closed branches are grey. Node ring/fill animates per status kind (`lib/format.ts: statusKind`). Hover shows a summary card, click opens the modal.
  - `components/NodeModal.tsx` — status, result metric, assignment / evidence / next action, work items, leftover ledger keys, report tabs (Markdown via `marked`), and the per-node history built from journal events, `state.work` items and report files.
  - `components/MessageBox.tsx` — the human steering form inside the node modal: pick `revision` or `branch`, write a prompt, and `POST` it; below it the node's `message-box/*.json` records with status, kind, work id and result node. The run rail shows the run-wide queue and every run tile carries a pending count.
  - `components/ReportPane.tsx` — run-level Markdown reports, opened on demand through the files route. Ideation runs show `ideas.json` and `run.md` instead of the node tree.
  - `components/StartResearchModal.tsx` — the **Start research** button (topbar and the empty Home state). Pick one contract from `contracts/`, tick ideas from any ideation run's `ideas.json`, add free-text instructions, optionally edit the run id, then **Launch**. `POST /api/sessions` answers with the session record and the view returns to Home, where the new run shows as a `starting` card (the scanner synthesizes it from the live session, `pending: true`) until the orchestrator creates `runs/<run-id>`. Opening the card shows the session console and a "Starting" banner.
  - `components/SessionBadge.tsx` / `components/SessionConsole.tsx` / `components/UsageMeter.tsx` — the Claude session id with a copy button (tooltip `claude --resume <id>`), and the rail card on a run with a session: status, turns, subscription usage per rate-limit window (`5h 42%`, `7d 12%`, colored by headroom), a compose box that sends straight into the session, Interrupt and Stop, and the event tail. Home lists every session with its usage and shows the peak window of the newest live session as a head stat. Cost is deliberately not shown: campaigns run on a subscription, and the CLI's `rate_limit` events are what say how much of it is left.

## Dashboard-launched sessions
`src/dashboard/sessions.py` owns Claude Code sessions started from the modal. Launch writes `sessions/<session-id>/{session.json, ideas.json}` (SCHEMA 3.12), builds a prompt that names the run id, the contract, the idea batch and the user's instructions, and starts a daemon thread running `ClaudeSDKClient` from `claude-agent-sdk` with `cwd` = target repo, the plugin checkout as a local plugin (`--plugin-dir` of `dashboard`, else this checkout, else the install recorded in `~/.claude/plugins/installed_plugins.json`), and `permission_mode=bypassPermissions`. Every SDK message becomes a row in `events.jsonl`; `init` and `result` messages update the record. Messages from the console go to `client.query()` immediately (the CLI queues mid-turn input), Interrupt calls `client.interrupt()`, Stop cancels the session task, which ends the subprocess.

Things to know:
- The session runs unattended with permissions bypassed inside the target repo. Stop kills the orchestrator process, not experiment jobs it started through resource leases or Slurm.
- The launch prompt starts with `/goal`, whose stop hook keeps the turn open until the campaign reaches a terminal outcome. A campaign session therefore stays `running` and only shows `idle` after Interrupt or once the goal is met; Interrupt is the way to get a `result` out of a long turn.
- Usage comes from the CLI's `rate_limit_event` stream (subscription accounts). An API-key session never reports one and the console shows "usage: not reported yet".
- The dashboard process is the owner. If it dies, `reconcile()` at the next start marks its live records `detached`; the `claude` subprocess may still be running.
- `claude --resume <claude_session_id>` is the way to take over from a terminal after Stop or on a detached record, and the dashboard's own Resume does the same thing in-process. Either way, driving a session the dashboard still holds opens a second driver on one transcript.
- Requires `claude-agent-sdk`: the `dashboard` extra of the wheel (`uv tool install "ai-scientist[dashboard] @ <wheel url>"`) or `uv sync --extra dashboard` in a checkout. The SDK bundles its own `claude` binary. Without the SDK, or without a plugin checkout to load the skills from, the launch route answers 503 with the install hint.
- The skills come from the plugin checkout and the CLI from the wheel. When their versions differ, launch writes a `dashboard` event with subtype `version_skew` so the mismatch is visible in the console; `ai-scientist doctor` reports the same.
- TODO(codex): a `CodexBackend` behind the same `SessionBackend` protocol; only the Claude backend exists.

## Artifacts the dashboard reads
Everything is agent-written; the dashboard only reads. Shapes and required keys are defined in [`SCHEMA.md`](SCHEMA.md), section 4 lists what each view uses. Summary:

| view | files | uses |
|---|---|---|
| overview | `loop-state.json` (research family) or `run.md` (ideation); `config.md` frontmatter; contract file; `ideas.json`; `contracts/*/research-contract.json` | phase, `phase_status`, `active`, `next_action`, `selection.selected_node`, `primary_metric`, `success_threshold`, goal, idea and node counts |
| run | above plus `journal.jsonl`, `selection.json`, `baseline/baseline.json`, `links`, every `*.md` under the run root and `logs/` | node ledger (`state.nodes`) with depth from `parent_node_id`, work grouped by `node`, raw `resources` / `resource_queue` / `open_questions`, report list, journal tail |
| node | ledger entry, `state.work` entries whose `node` matches, journal records whose `node_id` matches, files named by `result_ref`, `message-box/*.json` for the node | status, assignment, evidence summary, metrics, work list, history, report contents, messages |
| message box | `POST /api/runs/<run-id>/messages` writes one `message-box/<id>.json` through `core.message_box.add`; run and node views list `message-box/*.json` | pending counts on tiles, nodes and the run header, message rows |
| sessions | `sessions/*/session.json` + `events.jsonl`; ideation `ideas.json` files for the modal | session badge on tiles and run headers, console, Start-research choices |

Liveness: a node or work item is live when its `status` is not one of `completed cancelled failed abandoned accepted rejected`. The graph animates a few conventional live words (`planned`, `queued`, `implementing`, `revising`, `blocked`, `candidate`) and treats any other live word as "experimenting". An edge is live when anything in the child's subtree is live.

API: `/api/overview` (adds `ideas` and `sessions`; each run carries `session`), `/api/runs/<run-id>`, `/api/runs/<run-id>/nodes/<node-id>`, `/api/runs/<run-id>/files/<run-relative-path>` (text files only, path-checked to stay inside the run), `POST /api/runs/<run-id>/messages` with `{node_id, kind, prompt}` (201 with the message record; 400 on validation failure, 404 unknown run, 413 oversized). The dashboard never edits a message after creating it; status moves through `ai-scientist message-box update`.

Sessions: `GET /api/sessions` (records, newest first), `GET /api/sessions/<id>` (record plus the last 200 events), `POST /api/sessions` with `{contract_id, idea_ids, prompt, run_id?}` (201 record; 400 bad input, 409 run id taken or already has a live session, 503 SDK missing), `POST /api/sessions/<id>/messages` with `{text}` (202 with the event row; 409 when the session is not live or not owned by this process), `POST /api/sessions/<id>/resume` with `{note?}` (202 with the event row: the nudge for a live session, the `relaunch` row for a halted one, see below; 400 when a reopen arrives without a note, 409 when another dashboard process owns the record or the session never reported a Claude session id, 503 SDK missing), `POST /api/sessions/<id>/interrupt` and `.../stop` (200 record).

Resume: one textarea and one button cover every way a campaign halts. What the server does depends on the session and on the run's `loop-state.json`.

- **Stalled** — the session is `idle` while the run is still `active`, so the orchestrator declared the campaign done too early or is waiting for an answer. Tiles and the run header show `stalled`. The process is alive, so Resume sends one message that re-arms `/goal`, states that `loop-state.json` is still `running`, and asks the orchestrator to re-check the terminal conditions against the artifacts. The note is optional.
- **Halted** — the session is `stopped`, `failed` or `detached`, so there is no process to message. Resume starts one again with `ClaudeAgentOptions(resume=<claude_session_id>)`, in the same session directory and on the same transcript, and opens it with the resume prompt. `events.jsonl` gains a `dashboard` row with subtype `relaunch` at the seam and then reads as one continuous console. The note is optional. The button reads **Relaunch**.
- **Finished** — the run's `phase_status` is terminal. Resuming means reopening the run, so the note is required and is the new bar: a stricter threshold, an added criterion, or a comparison the contract did not require. The prompt asks the orchestrator to judge that bar against the evidence the run already produced and, if it reopens, to record the bar as a `binding_amendment`, put `phase_status` back to `running` with `active` true, and journal the transition. The dashboard writes no run artifacts; `skills/research-loop/SKILL.md` and `skills/research-loop-checkpoint/SKILL.md` own that.

A relaunch takes `owner_pid` over and refuses when another dashboard process is still running with that record, or when the session never reported a Claude session id. The user event that opens a resumed session carries `origin: resume`.
- `references/ui-reference.jpg` — visual reference for the design language (cream ground, ink sidebar, lime / pink / orange accents, rounded tiles).

## Commands
```sh
# build the frontend once (npm install on first use, then npm run build); needs npm on PATH
ai-scientist dashboard --build-only

# serve a target repo's artifacts from src/dashboard/dist; errors when dist/ is missing, warns when sources are newer
ai-scientist --target-repo <repo> dashboard [--host 127.0.0.1] [--port 8765] [--open]

# rebuild, then serve
ai-scientist --target-repo <repo> dashboard --build --open

# frontend dev loop in one command: API server plus Vite hot reload, browser opens on the Vite port
ai-scientist --target-repo <repo> dashboard --dev [--dev-port 5173] [--open]

# optional, in a checkout: let the dashboard launch Claude sessions (Start research); the wheel's `dashboard` extra does the same
uv sync --extra dashboard
```
Plain `dashboard` never runs npm. `--build`, `--build-only` and `--dev` do, and say so on stderr before each command. The release wheel ships `dist/` without the Vite sources and is served as is, never rebuilt. A checkout has the sources but no `dist/` (it is gitignored), so the first run there is `ai-scientist dashboard --build-only`. `--dev` runs `npm run dev` as a child process in its own process group and stops it with the server; `vite.config.ts` reads `VITE_API_PROXY` so the proxy follows `--host`/`--port`.

## Plans
- Node detail view (trials, critic reviews, metrics history).
- Human-in-the-loop actions (approve / reject / annotate) wired to CLI commands.
- Codex backend for dashboard-launched sessions.
- Live updates via file watching instead of polling.

## Dummy data
`tests/fixtures/dashboard/.ai-scientist` is generated from `make_fixture.py` following `SCHEMA.md`: a research run mid-loop with branches, one `success` with `selection.json`, one `exhausted`, one `blocked`, one ideation run, one broken `loop-state.json`, contracts including a malformed one, and one `detached` dashboard session bound to the research run. Timestamps are pinned so the tree is deterministic.
```sh
python3 tests/fixtures/dashboard/make_fixture.py
ai-scientist --target-repo tests/fixtures/dashboard dashboard --open
```
