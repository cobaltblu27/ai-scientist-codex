"""The CLI as an installable wheel: bundled assets, plugin resolution, version, doctor, packaging."""
from __future__ import annotations

import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from cli.main import main as cli_main
from core import plugin as core_plugin
from core.assets import SCHEMA_NAMES, frontend_dist_dir, frontend_source_dir, schemas_dir
from core.plugin import PluginNotFound, find_plugin_root, plugin_root, plugin_version
from core.version import cli_version
from test_support import REPO_ROOT
from validation.run import load_schema


# --- bundled assets ------------------------------------------------------------


def test_schemas_ship_inside_the_validation_package() -> None:
    assert schemas_dir() == REPO_ROOT / "src" / "validation" / "schemas"
    for name in SCHEMA_NAMES:
        assert isinstance(load_schema(name), dict), name  # load_schema fails soft, so assert the files really load


def test_frontend_paths_follow_the_vite_out_dir() -> None:
    assert frontend_dist_dir() == REPO_ROOT / "src" / "dashboard" / "dist"
    assert frontend_source_dir() == REPO_ROOT / "src" / "frontend"
    assert 'outDir: "../dashboard/dist"' in (REPO_ROOT / "src" / "frontend" / "vite.config.ts").read_text()


# --- plugin resolution ---------------------------------------------------------


def _plugin_dir(path: Path, version: str = "9.9.9") -> Path:
    (path / ".claude-plugin").mkdir(parents=True)
    (path / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "ai-scientist", "version": version}))
    return path


def test_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _plugin_dir(tmp_path / "plugin")
    monkeypatch.setenv("AI_SCIENTIST_PLUGIN_ROOT", str(fake))
    assert find_plugin_root() == (fake, "env") and plugin_root() == fake
    monkeypatch.setenv("AI_SCIENTIST_PLUGIN_ROOT", str(tmp_path / "not-a-plugin"))  # ignored: no manifest there
    assert find_plugin_root() == (REPO_ROOT, "checkout")
    assert plugin_version(fake) == "9.9.9" and plugin_version(tmp_path) is None


def test_installed_plugin_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in core_plugin.PLUGIN_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    installed = _plugin_dir(tmp_path / "cache" / "0.2.0")
    registry = config / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({
        "version": 2,
        "plugins": {
            core_plugin.INSTALLED_PLUGIN_KEY: [
                {"scope": "user", "installPath": str(tmp_path / "gone")},  # stale entry: directory removed
                {"scope": "user", "installPath": str(installed)},
            ]
        },
    }))
    assert core_plugin.installed_plugin_dir() == installed
    # from a wheel there is no checkout above core/plugin.py, so the registry is the answer
    assert find_plugin_root(start=tmp_path / "site-packages" / "core" / "plugin.py") == (installed, "installed")
    registry.write_text("{}")
    assert find_plugin_root(start=tmp_path / "site-packages") is None
    with pytest.raises(PluginNotFound, match="claude plugin install"):
        plugin_root(start=tmp_path / "site-packages")


# --- version -------------------------------------------------------------------


def test_versions_stay_in_sync(capsys: pytest.CaptureFixture[str]) -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    version = cli_version()
    assert f'version = "{version}"' in pyproject
    assert json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())["version"] == version
    assert json.loads((REPO_ROOT / ".codex-plugin" / "plugin.json").read_text())["version"].startswith(f"{version}+codex.")
    with pytest.raises(SystemExit) as exit_:
        cli_main(["--version"])
    assert exit_.value.code == 0 and capsys.readouterr().out.strip() == f"ai-scientist {version}"


# --- doctor --------------------------------------------------------------------


def test_doctor_reports_this_checkout(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["doctor"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok" and out["problems"] == []
    assert out["plugin_dir"] == str(REPO_ROOT) and out["plugin_source"] == "checkout" and out["version_skew"] is False
    assert all(out["schemas"][name] for name in SCHEMA_NAMES)
    assert out["frontend"]["dist_dir"] == str(REPO_ROOT / "src" / "dashboard" / "dist")
    assert out["frontend"]["state"] in {"fresh", "stale", "missing"}  # dist is gitignored, so it may not be built here


def test_doctor_flags_skew_and_missing_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _plugin_dir(tmp_path / "plugin", "9.9.9")
    assert cli_main(["doctor", "--plugin-dir", str(fake)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["version_skew"] is True and out["plugin_source"] == "flag" and out["plugin_version"] == "9.9.9"
    assert any("differs from CLI version" in p for p in out["problems"])

    monkeypatch.setattr(core_plugin, "find_plugin_root", lambda start=None: None)
    monkeypatch.setattr("cli.doctor.find_plugin_root", lambda start=None: None)
    assert cli_main(["doctor"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["plugin_dir"] is None and any("claude plugin install" in p for p in out["problems"])


def test_install_script_parses_and_documents_itself() -> None:
    script = REPO_ROOT / "install.sh"
    assert os.access(script, os.X_OK)
    subprocess.run(["sh", "-n", str(script)], check=True)
    help_text = subprocess.run([str(script), "--help"], check=True, capture_output=True, text=True).stdout
    assert "--wheel" in help_text and "--no-plugin" in help_text and "--no-dashboard" in help_text


# --- packaging -----------------------------------------------------------------


@pytest.mark.skipif(os.environ.get("AI_SCIENTIST_PACKAGING_TESTS") != "1", reason="set AI_SCIENTIST_PACKAGING_TESTS=1 (CI does)")
def test_wheel_and_sdist_carry_schemas_and_dist(tmp_path: Path) -> None:
    assert (frontend_dist_dir() / "index.html").is_file(), "build the frontend first (npm run build)"
    subprocess.run(["uv", "build", "--out-dir", str(tmp_path)], cwd=REPO_ROOT, check=True, capture_output=True)
    version = cli_version()
    with zipfile.ZipFile(tmp_path / f"ai_scientist-{version}-py3-none-any.whl") as wheel:
        names = set(wheel.namelist())
    assert {"validation/schemas/loop-state.schema.json", "dashboard/dist/index.html"} <= names
    assert not any(n.startswith("frontend/") or "node_modules" in n for n in names)
    with tarfile.open(tmp_path / f"ai_scientist-{version}.tar.gz") as sdist:
        members = set(sdist.getnames())
    assert {f"ai_scientist-{version}/src/validation/schemas/loop-state.schema.json", f"ai_scientist-{version}/src/dashboard/dist/index.html"} <= members
