"""Build and dev-serve the Vite frontend from the CLI.

`ai-scientist dashboard` serves `src/frontend/dist/`. This module reports on
that directory (`check_built`), builds it only on an explicit `--build` /
`--build-only` (`build`), and for `--dev` runs `npm run dev` as a child
process so one command gives the API server plus hot reload. Nothing here
runs npm unless the user asked for it with one of those flags.
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


def has_sources(frontend_dir: Path = FRONTEND_DIR) -> bool:
    """False for a packaged install that ships only dist/."""
    return (frontend_dir / "package.json").is_file()


def dist_state(frontend_dir: Path = FRONTEND_DIR, dist_dir: Path = DIST_DIR) -> str:
    """`missing`, `stale` (a source file is newer than dist/index.html), `fresh`, or `unavailable` (no dist and no sources)."""
    index = dist_dir / "index.html"
    if not index.is_file():
        return "missing" if has_sources(frontend_dir) else "unavailable"
    if not has_sources(frontend_dir):
        return "fresh"  # prebuilt package: nothing to compare against
    sources = _newest_mtime([frontend_dir / name for name in SOURCE_ROOTS])
    return "stale" if sources > index.stat().st_mtime else "fresh"


def _run(cmd: list[str], cwd: Path, log) -> None:
    log(f"ai-scientist dashboard: $ {' '.join(cmd)}  (in {cwd})")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise FrontendBuildError(f"`{' '.join(cmd)}` failed with exit code {result.returncode} in {cwd}")


def check_built(*, frontend_dir: Path = FRONTEND_DIR, dist_dir: Path = DIST_DIR, log=None) -> str:
    """Report on `dist/` without running anything. Raises when there is nothing to serve; warns when it is stale."""
    log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
    state = dist_state(frontend_dir, dist_dir)
    if state == "unavailable":
        raise FrontendBuildError(f"frontend is not built and its sources are not in this install ({frontend_dir}); install a build that ships dist/")
    if state == "missing":
        raise FrontendBuildError("frontend is not built; run `ai-scientist dashboard --build` (needs npm) or `--build-only`")
    if state == "stale":
        log("ai-scientist dashboard: frontend sources are newer than dist/; serving the existing build (rebuild with --build)")
    return state


def build(*, frontend_dir: Path = FRONTEND_DIR, dist_dir: Path = DIST_DIR, log=None) -> str:
    """Build `dist/` now. Installs node_modules first when missing. Only called on an explicit --build / --build-only."""
    log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
    if not has_sources(frontend_dir):
        if (dist_dir / "index.html").is_file():
            log("ai-scientist dashboard: this install ships a prebuilt frontend and no sources; nothing to build")
            return "fresh"
        raise FrontendBuildError(f"frontend sources are not in this install ({frontend_dir}); nothing to build")
    npm = npm_path()
    if npm is None:
        raise FrontendBuildError("building the frontend needs `npm` on PATH; install Node.js")
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
