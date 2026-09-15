"""Build and dev-serve the Vite frontend from the CLI.

`ai-scientist dashboard` serves `src/frontend/dist/`. This module keeps that
directory current (`ensure_built`) and, for `--dev`, runs `npm run dev` as a
child process so one command gives the API server plus hot reload.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from core.plugin import plugin_root

FRONTEND_DIR = plugin_root() / "src" / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
# Files whose change makes `dist/` stale. `src/` is walked recursively.
SOURCE_ROOTS = ("src", "index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json")
DEV_PORT = 5173


class FrontendBuildError(RuntimeError):
    pass


def npm_path() -> str | None:
    return shutil.which("npm")


def _newest_mtime(paths: list[Path]) -> float:
    newest = 0.0
    for base in paths:
        if base.is_file():
            newest = max(newest, base.stat().st_mtime)
        elif base.is_dir():
            for p in base.rglob("*"):
                if p.is_file():
                    newest = max(newest, p.stat().st_mtime)
    return newest


def dist_state(frontend_dir: Path = FRONTEND_DIR, dist_dir: Path = DIST_DIR) -> str:
    """`missing`, `stale` (a source file is newer than dist/index.html) or `fresh`."""
    index = dist_dir / "index.html"
    if not index.is_file():
        return "missing"
    sources = _newest_mtime([frontend_dir / name for name in SOURCE_ROOTS])
    return "stale" if sources > index.stat().st_mtime else "fresh"


def _run(cmd: list[str], cwd: Path, log) -> None:
    log(f"ai-scientist dashboard: $ {' '.join(cmd)}  (in {cwd})")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise FrontendBuildError(f"`{' '.join(cmd)}` failed with exit code {result.returncode} in {cwd}")


def ensure_built(*, force: bool = False, frontend_dir: Path = FRONTEND_DIR, dist_dir: Path = DIST_DIR, log=None) -> str:
    """Make `dist/` current. Returns `built` or `fresh`. Installs node_modules on first use."""
    log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
    state = dist_state(frontend_dir, dist_dir)
    if state == "fresh" and not force:
        return "fresh"
    npm = npm_path()
    if npm is None:
        if state == "missing":
            raise FrontendBuildError("frontend is not built and `npm` is not on PATH; install Node.js or build src/frontend elsewhere")
        log("ai-scientist dashboard: frontend sources changed but `npm` is not on PATH; serving the existing build")
        return "fresh"
    if not (frontend_dir / "node_modules").is_dir():
        _run([npm, "install"], frontend_dir, log)
    _run([npm, "run", "build"], frontend_dir, log)
    return "built"


def start_dev_server(*, api_url: str, port: int = DEV_PORT, frontend_dir: Path = FRONTEND_DIR) -> subprocess.Popen:
    """Run `npm run dev` proxying /api to the Python server. Own process group so `stop_dev_server` can end Vite and its children."""
    npm = npm_path()
    if npm is None:
        raise FrontendBuildError("`--dev` needs `npm` on PATH")
    if not (frontend_dir / "node_modules").is_dir():
        _run([npm, "install"], frontend_dir, lambda msg: print(msg, file=sys.stderr, flush=True))
    env = {**os.environ, "VITE_API_PROXY": api_url}
    return subprocess.Popen(
        [npm, "run", "dev", "--", "--port", str(port), "--strictPort", "--host", "127.0.0.1"],
        cwd=frontend_dir,
        env=env,
        start_new_session=True,
    )


def stop_dev_server(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout)
