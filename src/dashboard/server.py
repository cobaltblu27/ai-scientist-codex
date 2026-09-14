"""Stdlib HTTP server: JSON API over `.ai-scientist/` plus the built frontend."""
from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from core.message_box import MessageBoxError, add as add_message
from core.plugin import plugin_root
from dashboard.scan import find_run, find_run_file, node_detail, run_detail, scan_overview

DIST_DIR = plugin_root() / "src" / "frontend" / "dist"
MAX_POST_BYTES = 64 * 1024


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

        def _file(self, path: Path, ctype: str | None = None) -> None:
            body = path.read_bytes()
            ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._route(urlparse(self.path).path)
            except Exception as exc:  # noqa: BLE001 - never take the server down on one bad artifact
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{exc.__class__.__name__}: {exc}"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._route_post(urlparse(self.path).path)
            except Exception as exc:  # noqa: BLE001 - never take the server down on one bad request
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{exc.__class__.__name__}: {exc}"})

        def _read_json_body(self) -> tuple[dict | None, tuple[HTTPStatus, str] | None]:
            """The request body as a JSON object, or an (status, error) pair to send instead."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None, (HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            if length > MAX_POST_BYTES:
                return None, (HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"body larger than {MAX_POST_BYTES} bytes")
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return None, (HTTPStatus.BAD_REQUEST, "body must be a JSON object")
            if not isinstance(body, dict):
                return None, (HTTPStatus.BAD_REQUEST, "body must be a JSON object")
            return body, None

        def _route_post(self, route: str) -> None:
            # POST /api/runs/<run-id>/messages  {node_id, kind, prompt}
            if route.startswith("/api/runs/"):
                parts = [unquote(p) for p in route[len("/api/runs/"):].strip("/").split("/")]
                if len(parts) == 2 and parts[1] == "messages":
                    run = find_run(target_repo, parts[0])
                    if run is None:
                        return self._json(HTTPStatus.NOT_FOUND, {"error": f"unknown run: {parts[0]}"})
                    body, failure = self._read_json_body()
                    if failure is not None:
                        return self._json(failure[0], {"error": failure[1]})
                    try:
                        record = add_message(
                            target_repo,
                            parts[0],
                            str(body.get("node_id") or ""),
                            str(body.get("kind") or ""),
                            str(body.get("prompt") or ""),
                        )
                    except MessageBoxError as exc:
                        return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return self._json(HTTPStatus.CREATED, record)
            return self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

        def _route(self, route: str) -> None:
            if route == "/api/overview":
                return self._json(HTTPStatus.OK, scan_overview(target_repo))
            if route.startswith("/api/runs/"):
                # /api/runs/<run-id>
                # /api/runs/<run-id>/nodes/<node-id>
                # /api/runs/<run-id>/files/<relative-path>
                parts = [unquote(p) for p in route[len("/api/runs/"):].strip("/").split("/")]
                run = find_run(target_repo, parts[0])
                if run is None:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": f"unknown run: {parts[0]}"})
                if len(parts) == 1:
                    return self._json(HTTPStatus.OK, run_detail(run))
                if len(parts) == 3 and parts[1] == "nodes":
                    node = node_detail(run, parts[2])
                    if node is None:
                        return self._json(HTTPStatus.NOT_FOUND, {"error": f"unknown node: {parts[2]}"})
                    return self._json(HTTPStatus.OK, node)
                if len(parts) >= 3 and parts[1] == "files":
                    relative = "/".join(parts[2:])
                    path = find_run_file(run, relative)
                    if path is None:
                        return self._json(HTTPStatus.FORBIDDEN, {"error": f"not a text file inside the run: {relative}"})
                    if not path.is_file():
                        return self._json(HTTPStatus.NOT_FOUND, {"error": f"no such file: {relative}"})
                    return self._file(path, "text/plain; charset=utf-8")
                return self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
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
