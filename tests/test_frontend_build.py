"""`ai-scientist dashboard` as the frontend launcher: staleness check, build, and the --dev / --build-only flags."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from cli.main import build_parser, main as cli_main
from dashboard import frontend
from dashboard.frontend import FrontendBuildError, dist_state, ensure_built


def _touch(path: Path, when: float, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (when, when))


@pytest.fixture
def fe(tmp_path: Path) -> tuple[Path, Path]:
    front = tmp_path / "frontend"
    now = time.time()
    _touch(front / "src" / "App.tsx", now - 100)
    _touch(front / "index.html", now - 100)
    _touch(front / "package.json", now - 100, "{}")
    return front, front / "dist"


def test_dist_state(fe: tuple[Path, Path]) -> None:
    front, dist = fe
    assert dist_state(front, dist) == "missing"
    _touch(dist / "index.html", time.time() - 50)
    assert dist_state(front, dist) == "fresh"
    _touch(front / "src" / "components" / "New.tsx", time.time())  # a nested source newer than the build
    assert dist_state(front, dist) == "stale"


def test_ensure_built_runs_npm(fe: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    front, dist = fe
    calls: list[list[str]] = []

    def fake_run(cmd, cwd):
        calls.append(cmd)
        assert cwd == front
        if cmd[1:] == ["run", "build"]:
            _touch(dist / "index.html", time.time() + 1)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(frontend, "npm_path", lambda: "/usr/bin/npm")
    monkeypatch.setattr(frontend.subprocess, "run", fake_run)
    logged: list[str] = []
    assert ensure_built(frontend_dir=front, dist_dir=dist, log=logged.append) == "built"
    assert calls == [["/usr/bin/npm", "install"], ["/usr/bin/npm", "run", "build"]]  # no node_modules yet
    assert any("npm run build" in line for line in logged)

    calls.clear()
    assert ensure_built(frontend_dir=front, dist_dir=dist) == "fresh"  # up to date: nothing runs
    assert calls == []

    (front / "node_modules").mkdir()
    assert ensure_built(force=True, frontend_dir=front, dist_dir=dist, log=logged.append) == "built"
    assert calls == [["/usr/bin/npm", "run", "build"]]


def test_ensure_built_failure_and_missing_npm(fe: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    front, dist = fe
    monkeypatch.setattr(frontend, "npm_path", lambda: None)
    with pytest.raises(FrontendBuildError, match="not on PATH"):
        ensure_built(frontend_dir=front, dist_dir=dist)
    _touch(dist / "index.html", time.time() - 500)  # stale but present: served as is
    logged: list[str] = []
    assert ensure_built(frontend_dir=front, dist_dir=dist, log=logged.append) == "fresh"
    assert any("existing build" in line for line in logged)

    (front / "node_modules").mkdir()
    monkeypatch.setattr(frontend, "npm_path", lambda: "/usr/bin/npm")
    monkeypatch.setattr(frontend.subprocess, "run", lambda cmd, cwd: subprocess.CompletedProcess(cmd, 2))
    with pytest.raises(FrontendBuildError, match="exit code 2"):
        ensure_built(force=True, frontend_dir=front, dist_dir=dist)


def test_dashboard_flags() -> None:
    args = build_parser().parse_args(["dashboard", "--dev", "--dev-port", "5200", "--no-build", "--build-only", "--port", "9000"])
    assert (args.dev, args.dev_port, args.no_build, args.build_only, args.port, args.host) == (True, 5200, True, True, 9000, "127.0.0.1")
    defaults = build_parser().parse_args(["dashboard"])
    assert (defaults.dev, defaults.dev_port, defaults.no_build, defaults.build_only) == (False, 5173, False, False)


def test_cli_build_only(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(frontend, "ensure_built", lambda force=False, **kw: "built")
    assert cli_main(["dashboard", "--build-only"]) == 0
    assert json.loads(capsys.readouterr().out) == {"frontend": "built", "status": "ok"}

    def boom(force=False, **kw):
        raise FrontendBuildError("no npm")

    monkeypatch.setattr(frontend, "ensure_built", boom)
    assert cli_main(["dashboard", "--build-only"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "no npm"


def test_dev_server_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--dev spawns npm in its own process group with the proxy target in the environment, and stop ends the group."""
    front = tmp_path / "frontend"
    (front / "node_modules").mkdir(parents=True)
    fake_npm = tmp_path / "npm"
    fake_npm.write_text("#!/bin/sh\necho \"$VITE_API_PROXY $*\" > \"$FAKE_NPM_LOG\"\nsleep 30\n")
    fake_npm.chmod(0o755)
    log = tmp_path / "npm.log"
    monkeypatch.setenv("FAKE_NPM_LOG", str(log))
    monkeypatch.setattr(frontend, "npm_path", lambda: str(fake_npm))

    proc = frontend.start_dev_server(api_url="http://127.0.0.1:8999", port=5200, frontend_dir=front)
    try:
        deadline = time.time() + 5
        while not log.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert log.read_text().strip() == "http://127.0.0.1:8999 run dev -- --port 5200 --strictPort --host 127.0.0.1"
        assert os.getpgid(proc.pid) == proc.pid  # own process group
    finally:
        frontend.stop_dev_server(proc)
    assert proc.poll() is not None
    frontend.stop_dev_server(proc)  # idempotent
