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
from dashboard.frontend import FrontendBuildError, build, check_built, dist_state


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


def test_check_built_never_runs_npm(fe: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    front, dist = fe
    monkeypatch.setattr(frontend, "npm_path", lambda: "/usr/bin/npm")
    monkeypatch.setattr(frontend.subprocess, "run", lambda cmd, cwd: pytest.fail("plain dashboard must not run npm"))
    with pytest.raises(FrontendBuildError, match="--build"):
        check_built(frontend_dir=front, dist_dir=dist)
    _touch(dist / "index.html", time.time() - 50)
    logged: list[str] = []
    assert check_built(frontend_dir=front, dist_dir=dist, log=logged.append) == "fresh" and logged == []
    _touch(front / "src" / "New.tsx", time.time())
    assert check_built(frontend_dir=front, dist_dir=dist, log=logged.append) == "stale"
    assert logged and "existing build" in logged[0]


def test_packaged_install_without_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A packaged CLI ships dist/ only: served as is, never rebuilt, and a missing dist is a clear error."""
    front = tmp_path / "frontend"
    dist = front / "dist"
    assert dist_state(front, dist) == "unavailable"
    with pytest.raises(FrontendBuildError, match="sources are not in this install"):
        check_built(frontend_dir=front, dist_dir=dist)
    with pytest.raises(FrontendBuildError, match="nothing to build"):
        build(frontend_dir=front, dist_dir=dist)
    _touch(dist / "index.html", time.time() - 10)
    assert dist_state(front, dist) == "fresh"
    monkeypatch.setattr(frontend, "npm_path", lambda: "/usr/bin/npm")
    monkeypatch.setattr(frontend.subprocess, "run", lambda cmd, cwd: pytest.fail("npm must not run without sources"))
    assert check_built(frontend_dir=front, dist_dir=dist) == "fresh"
    assert build(frontend_dir=front, dist_dir=dist) == "fresh"


def test_build_runs_npm(fe: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    front, dist = fe
    calls: list[list[str]] = []

    def fake_run(cmd, cwd):
        calls.append(cmd)
        assert cwd == front
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(frontend, "npm_path", lambda: "/usr/bin/npm")
    monkeypatch.setattr(frontend.subprocess, "run", fake_run)
    logged: list[str] = []
    assert build(frontend_dir=front, dist_dir=dist, log=logged.append) == "built"
    assert calls == [["/usr/bin/npm", "install"], ["/usr/bin/npm", "run", "build"]]  # no node_modules yet
    assert [line for line in logged if "npm install" in line] and [line for line in logged if "npm run build" in line]

    calls.clear()
    (front / "node_modules").mkdir()
    assert build(frontend_dir=front, dist_dir=dist) == "built"
    assert calls == [["/usr/bin/npm", "run", "build"]]


def test_build_failure_and_missing_npm(fe: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    front, dist = fe
    monkeypatch.setattr(frontend, "npm_path", lambda: None)
    with pytest.raises(FrontendBuildError, match="needs `npm`"):
        build(frontend_dir=front, dist_dir=dist)
    (front / "node_modules").mkdir()
    monkeypatch.setattr(frontend, "npm_path", lambda: "/usr/bin/npm")
    monkeypatch.setattr(frontend.subprocess, "run", lambda cmd, cwd: subprocess.CompletedProcess(cmd, 2))
    with pytest.raises(FrontendBuildError, match="exit code 2"):
        build(frontend_dir=front, dist_dir=dist)


def test_dashboard_flags() -> None:
    args = build_parser().parse_args(["dashboard", "--dev", "--dev-port", "5200", "--build", "--build-only", "--port", "9000"])
    assert (args.dev, args.dev_port, args.build, args.build_only, args.port, args.host) == (True, 5200, True, True, 9000, "127.0.0.1")
    defaults = build_parser().parse_args(["dashboard"])
    assert (defaults.dev, defaults.dev_port, defaults.build, defaults.build_only) == (False, 5173, False, False)


def test_cli_build_only_and_missing_dist(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(frontend, "build", lambda **kw: "built")
    assert cli_main(["dashboard", "--build-only"]) == 0
    assert json.loads(capsys.readouterr().out) == {"frontend": "built", "status": "ok"}

    def boom(**kw):
        raise FrontendBuildError("no npm")

    monkeypatch.setattr(frontend, "build", boom)
    assert cli_main(["dashboard", "--build-only"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "no npm"

    def missing(**kw):
        raise FrontendBuildError("frontend is not built; run --build")

    monkeypatch.setattr(frontend, "check_built", missing)
    assert cli_main(["dashboard"]) == 1  # plain dashboard stops before serving, without touching npm
    assert "not built" in json.loads(capsys.readouterr().out)["error"]


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
