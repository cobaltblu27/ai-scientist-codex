from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_support import import_planned_module


def detect_mutations(target: Path, before=None):
    module = import_planned_module("research_loop.executor")
    if hasattr(module, "RuntimeMutationDetector"):
        detector = module.RuntimeMutationDetector(target_repo=target, allowed_root=target / ".ai-scientist")
        return detector.snapshot() if before is None else detector.diff(before)
    if hasattr(module, "snapshot_repo") and hasattr(module, "detect_runtime_mutations"):
        if before is None:
            return module.snapshot_repo(target, ignore_dirs={".ai-scientist"})
        return module.detect_runtime_mutations(target, before, allowed_root=target / ".ai-scientist")
    integrity = import_planned_module("research_loop.integrity")
    if hasattr(integrity, "snapshot_tree") and hasattr(integrity, "diff_snapshots"):
        if before is None:
            return integrity.snapshot_tree(target)
        changes = integrity.diff_snapshots(before, integrity.snapshot_tree(target))
        return {"passed": not changes, "changed_paths": changes, "block_reason": None if not changes else "runtime mutation outside .ai-scientist detected"}
    raise AssertionError("research_loop.executor/integrity must expose runtime mutation snapshot/detect functions")


def changed_paths(result) -> list[str]:
    if isinstance(result, dict):
        return [str(p) for p in result.get("changed_paths", result.get("changes", []))]
    changes = getattr(result, "changed_paths", getattr(result, "changes", []))
    return [str(getattr(change, "path", change)) for change in changes]


def passed(result):
    return result.get("passed") if isinstance(result, dict) else getattr(result, "passed", None)


class RuntimeMutationTests(unittest.TestCase):
    def test_runtime_mutation_detector_blocks_writes_outside_ai_scientist(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.mkdir()
            (target / ".ai-scientist" / "runs" / "run-001").mkdir(parents=True)
            (target / "source.py").write_text("VALUE = 1\n")

            before = detect_mutations(target)
            (target / "MUTATION_SENTINEL.txt").write_text("generated command escaped workspace\n")
            result = detect_mutations(target, before)

            self.assertTrue(any("MUTATION_SENTINEL.txt" in path for path in changed_paths(result)))
            self.assertIs(passed(result), False)
            self.assertTrue("outside" in str(result).lower() or "mutation" in str(result).lower())


if __name__ == "__main__":
    unittest.main()
