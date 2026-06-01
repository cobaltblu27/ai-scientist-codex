from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_support import AI_SCIENTIST_CMD, VALIDATE_RUN_ARGS, read_json, run_python, write_json, write_minimal_research_run

CLI_ARGS = AI_SCIENTIST_CMD
PLOT_DEPS_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ["matplotlib", "numpy", "PIL"])


def run_cli(target: Path, *args: str | Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI_ARGS, "--target-repo", str(target), *map(str, args)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )



def fake_tex_env(target: Path) -> dict[str, str]:
    fake_bin = target / "fake-tex-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    pdflatex = fake_bin / "pdflatex"
    pdflatex.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import sys\n"
        "tex = Path(sys.argv[-1])\n"
        "tex.with_suffix('.pdf').write_bytes(b'%PDF-1.4 fixture\\n%%EOF\\n')\n"
    )
    bibtex = fake_bin / "bibtex"
    bibtex.write_text("#!/usr/bin/env python3\n")
    pdflatex.chmod(0o755)
    bibtex.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    return env

def add_review_to_writeup_gate(run: Path) -> None:
    write_json(
        run / "review" / "structured-review.json",
        {
            "verdict": {"decision": "accept", "summary": "evidence supports writeup"},
            "leakage": {"passed": True},
            "split_integrity": {"passed": True},
            "baseline_comparison": {"passed": True},
            "strictness_mode_criteria": {"passed": True},
        },
    )
    status_path = run / "run-status.json"
    status = read_json(status_path)
    review_validation = {"gate": "review_to_writeup", "exit_code": 0, "validator_exit_code": 0}
    validations = status.setdefault("last_validations", {})
    validations["review_to_writeup"] = review_validation
    status["last_validation"] = review_validation
    write_json(status_path, status)
    with (run / "handoff.jsonl").open("a") as handle:
        handle.write(json.dumps({
            "gate": "review_to_writeup",
            "from_phase": "review",
            "to_phase": "writeup",
            "approved": True,
            "validator_exit_code": 0,
            "approved_at": "2026-05-30T00:00:00Z",
        }) + "\n")



def write_manual_figure_manifest(run: Path) -> None:
    figure_path = run / "writeup" / "figures" / "generated" / "baseline-vs-selected.png"
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    figure_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lxRERQAAAABJRU5ErkJggg=="))
    write_json(
        run / "writeup" / "figures" / "figure-manifest.json",
        {
            "schema_version": 1,
            "created_at": "2026-05-30T00:00:00Z",
            "required": True,
            "figures": [
                {
                    "id": "fig-baseline-vs-selected",
                    "path": "writeup/figures/generated/baseline-vs-selected.png",
                    "caption": "Fixture metric comparison.",
                    "source_artifacts": ["baseline/metrics.json", "nodes/node-001/metrics.json"],
                }
            ],
        },
    )

def write_reports(run: Path) -> None:
    figure = "writeup/figures/generated/baseline-vs-selected.png"
    (run / "writeup" / "latex").mkdir(parents=True, exist_ok=True)
    (run / "writeup" / "report.md").write_text(
        "# Fixture Report\n\n"
        "## AI Scientist disclosure\n\nCodex assisted the AI Scientist workflow.\n\n"
        "## Results\n\nSee figure writeup/figures/generated/baseline-vs-selected.png.\n\n"
        "## Limitations\n\nThis is a fixture report with limited external validity.\n"
    )
    (run / "writeup" / "latex" / "template.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage{graphicx}\n"
        "\\begin{document}\n"
        "\\section{AI Scientist disclosure} Codex assisted the workflow.\n"
        "\\section{Limitations} Fixture limitations are disclosed.\n"
        "\\includegraphics{baseline-vs-selected.png}\n"
        "\\end{document}\n"
    )
    assert (run / figure).exists()


class WriteupStateTests(unittest.TestCase):

    def test_writeup_pdf_pipeline_accepts_manual_figure_manifest_and_clears_after_launch_handoff(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.mkdir()
            run = write_minimal_research_run(target)
            add_review_to_writeup_gate(run)

            started = run_cli(target, "writeup", "start", "--run-id", "run-001")
            self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
            write_manual_figure_manifest(run)
            write_reports(run)
            recorded = run_cli(target, "writeup", "record-reports", "--run-id", "run-001")
            self.assertEqual(recorded.returncode, 0, recorded.stderr + recorded.stdout)
            compile_result = run_cli(target, "writeup", "compile", "--run-id", "run-001", env=fake_tex_env(target))
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr + compile_result.stdout)
            audit = run_cli(target, "writeup", "audit-complete", "--run-id", "run-001", "--json", json.dumps({"verdict": "ACCEPT", "summary": "ready"}))
            self.assertEqual(audit.returncode, 0, audit.stderr + audit.stdout)
            complete = run_cli(target, "writeup", "complete", "--run-id", "run-001")
            self.assertEqual(complete.returncode, 0, complete.stderr + complete.stdout)

            validation = run_python([*VALIDATE_RUN_ARGS, target, "--gate", "launch", "--run-id", "run-001"])
            self.assertEqual(validation.returncode, 0, validation.stderr + validation.stdout)
            record_validation = run_cli(target, "validation", "record", "--run-id", "run-001", "--gate", "launch", "--exit-code", "0")
            self.assertEqual(record_validation.returncode, 0, record_validation.stderr + record_validation.stdout)
            record_handoff = run_cli(target, "handoff", "record", "--run-id", "run-001", "--gate", "launch", "--exit-code", "0", "--approved")
            self.assertEqual(record_handoff.returncode, 0, record_handoff.stderr + record_handoff.stdout)
            self.assertFalse((target / ".ai-scientist" / "active-run.json").exists())

    @unittest.skipUnless(PLOT_DEPS_AVAILABLE, "plot dependencies are not installed")
    def test_collect_figures_generates_metric_plot_when_plot_dependencies_available(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.mkdir()
            run = write_minimal_research_run(target)
            add_review_to_writeup_gate(run)

            self.assertEqual(run_cli(target, "writeup", "start", "--run-id", "run-001").returncode, 0)
            figures = run_cli(target, "writeup", "collect-figures", "--run-id", "run-001")
            self.assertEqual(figures.returncode, 0, figures.stderr + figures.stdout)
            self.assertTrue((run / "writeup" / "figures" / "generated" / "baseline-vs-selected.png").exists())
            manifest = read_json(run / "writeup" / "figures" / "figure-manifest.json")
            self.assertEqual(len(manifest["figures"]), 1)

    def test_launch_validation_fails_without_writeup_manifest(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.mkdir()
            write_minimal_research_run(target)

            result = run_python([*VALIDATE_RUN_ARGS, target, "--gate", "launch", "--run-id", "run-001"])

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("writeup", (result.stderr + result.stdout).lower())

    def test_writeup_doctor_reports_missing_tex_tools(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.mkdir()
            result = run_cli(target, "writeup", "doctor")
            payload = json.loads(result.stdout)
            if result.returncode == 0:
                self.assertEqual(payload["status"], "ok")
            else:
                self.assertEqual(payload["status"], "error")
                self.assertIn("Install the missing dependency", payload["error"])


if __name__ == "__main__":
    unittest.main()
