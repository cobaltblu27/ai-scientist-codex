# Frontend Dashboard
Frontend is managed using auxiliary cli.
Running `ai-scientist dashboard` launches a dashboard that watches and visualizes runs and nodes inside `./.ai-scientist`.

## Stack
React, TypeScript and Vite. Built artifact is served by the Python CLI.

## Layout
- `src/dashboard/` — Python side. `scan.py` reads `.ai-scientist/` into plain JSON (read-only, lenient to half-written artifacts). `server.py` is a stdlib HTTP server exposing `/api/overview`, `/api/runs/<run-id>` and the built frontend.
- `src/frontend/` — Vite app. Left sidebar lists loop runs (active / finished) and contracts; main pane shows the overview or one run (nodes, journal tail, next action, selection, phase progress). Polls the API every 3s.
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
