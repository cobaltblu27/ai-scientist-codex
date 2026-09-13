"""Stdlib HTTP server: JSON API over `.ai-scientist/` plus the built frontend."""
from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from core.plugin import plugin_root
from dashboard.scan import find_run, run_detail, scan_overview

DIST_DIR = plugin_root() / "src" / "frontend" / "dist"


def make_handler(target_repo: Path, dist_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _json(self, status: HTTPStatus, payload) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path) -> None:
            body = path.read_bytes()
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._route(urlparse(self.path).path)
            except Exception as exc:  # noqa: BLE001 - never take the server down on one bad artifact
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{exc.__class__.__name__}: {exc}"})

        def _route(self, route: str) -> None:
            if route == "/api/overview":
                return self._json(HTTPStatus.OK, scan_overview(target_repo))
            if route.startswith("/api/runs/"):
                run_id = route[len("/api/runs/"):].strip("/")
                run = find_run(target_repo, run_id)
                if run is None:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": f"unknown run: {run_id}"})
                return self._json(HTTPStatus.OK, run_detail(run))
            if route.startswith("/api/"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

            if not dist_dir.is_dir():
                return self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": f"frontend not built: run `npm install && npm run build` in {dist_dir.parent}"},
                )
            rel = route.lstrip("/") or "index.html"
            candidate = (dist_dir / rel).resolve()
            if candidate.is_file() and dist_dir.resolve() in candidate.parents:
                return self._file(candidate)
            return self._file(dist_dir / "index.html")  # SPA fallback

    return Handler


def serve(target_repo: Path, host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = False, dist_dir: Path | None = None) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(target_repo, dist_dir or DIST_DIR))
    url = f"http://{host}:{server.server_port}/"
    print(f"ai-scientist dashboard: {url}  (watching {target_repo}/.ai-scientist)", flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
