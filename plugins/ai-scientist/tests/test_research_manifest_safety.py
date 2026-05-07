from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_support import import_planned_module


def call_manifest_sanitizer(manifest: dict, workspace: Path):
    module = import_planned_module("research_loop.manifests")
    for name in ("sanitize_manifest", "validate_manifest", "validate_and_materialize_manifest", "materialize_manifest"):
        func = getattr(module, name, None)
        if func is None:
            continue
        errors = []
        for args, kwargs in (
            ((manifest, workspace), {}),
            ((manifest, workspace, "accuracy", "maximize"), {}),
            ((manifest,), {"workspace": workspace, "metric_key": "accuracy", "metric_direction": "maximize"}),
            ((manifest,), {"node_workspace": workspace}),
        ):
            try:
                return func(*args, **kwargs)
            except TypeError as exc:
                errors.append(exc)
        raise AssertionError(f"{name} exists but did not accept a manifest/workspace call shape: {errors}")
    raise AssertionError("research_loop.manifests must expose a manifest sanitizer/materializer function")


class ManifestSafetyTests(unittest.TestCase):
    def test_manifest_sanitizer_rejects_traversal_and_absolute_paths(self) -> None:
        for unsafe_path in ["../escape.py", "nested/../../escape.py", "/tmp/absolute-escape.py"]:
            with self.subTest(unsafe_path=unsafe_path), TemporaryDirectory() as td:
                tmp_path = Path(td)
                workspace = tmp_path / "run" / "nodes" / "node-001" / "workspace"
                workspace.mkdir(parents=True)
                manifest = {"files": [{"path": unsafe_path, "content": "bad = True\n"}], "command": ["python", "experiment.py"]}

                with self.assertRaises(Exception):
                    call_manifest_sanitizer(manifest, workspace)

                self.assertFalse((tmp_path / "escape.py").exists())
                self.assertFalse(Path("/tmp/absolute-escape.py").exists())

    def test_manifest_sanitizer_accepts_safe_node_relative_paths(self) -> None:
        with TemporaryDirectory() as td:
            workspace = Path(td) / "run" / "nodes" / "node-001" / "workspace"
            workspace.mkdir(parents=True)
            manifest = {
                "files": [
                    {"path": "experiment.py", "content": "print('ok')\n"},
                    {"path": "package/helpers.py", "content": "VALUE = 1\n"},
                ],
                "command": ["python", "experiment.py", "--metrics-out", "metrics.json"],
                "expected_metrics": {"metric_key": "accuracy", "metric_direction": "maximize"},
            }

            call_manifest_sanitizer(manifest, workspace)
            if (workspace / "experiment.py").exists():
                self.assertTrue((workspace / "package" / "helpers.py").exists())


if __name__ == "__main__":
    unittest.main()
