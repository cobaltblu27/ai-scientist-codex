from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import ResearchConfig


class AgentRunner:
    def run(self, prompt: dict[str, Any], config: ResearchConfig) -> dict[str, Any]:
        raise NotImplementedError


class FixtureRunner(AgentRunner):
    def run(self, prompt: dict[str, Any], config: ResearchConfig) -> dict[str, Any]:
        action = prompt["action"]
        metric_key = config.metric_key
        if config.fixture_scenario == "unsafe_manifest":
            return {"files": [{"path": "../escape.py", "content": "", "executable": False}], "command": [sys.executable, "experiment.py"], "expected_metrics": {"metric_key": metric_key, "metric_direction": config.metric_direction}, "mode_deliverables": {}}
        baseline = 1.0 if config.metric_direction == "maximize" else 1.0
        if config.fixture_scenario == "no_improvement":
            value = 0.5 if config.metric_direction == "maximize" else 1.5
        elif config.metric_direction == "minimize" or config.fixture_scenario == "minimize_success":
            value = 0.5
        else:
            value = 2.0
        mutation = "\nfrom pathlib import Path\nPath('../../../../../../MUTATION_SENTINEL.txt').write_text('mutated')\n" if config.fixture_scenario == "runtime_mutation" else ""
        deliverables = {
            "scientist": {"reproducibility_note": True, "experiment_rationale": True, "split_leakage_evidence": True, "ablation_summary": True, "tuning_summary": True, "limitations": True, "strictness_mode": "scientist"},
            "researcher": {"rationale": True, "reproducibility_note": True, "limitations": True, "sensitivity_evidence": True, "validation_evidence": True, "strictness_mode": "researcher"},
            "balanced": {"rationale": True, "split_leakage_evidence": True, "result_summary": True, "validation_deliverable": True, "strictness_mode": "balanced"},
            "builder": {"runnable_artifact_summary": True, "command_log": True, "metrics": True, "integration_notes": True, "known_risks": True, "strictness_mode": "builder"},
            "engineer": {"minimal_patch_summary": True, "command_log": True, "metrics": True, "rollback_notes": True, "strictness_mode": "engineer"},
        }
        code = f"""import json\nfrom pathlib import Path\nmetric_key={metric_key!r}\nvalue={value!r}\nPath('metrics.json').write_text(json.dumps({{metric_key: value, 'score': value}}, indent=2)+'\\n')\nPath('split_integrity.json').write_text(json.dumps({{'passed': True, 'action': {action!r}}}, indent=2)+'\\n')\nPath('leakage_check.json').write_text(json.dumps({{'passed': True, 'action': {action!r}}}, indent=2)+'\\n')\nPath('result_summary.json').write_text(json.dumps({{'summary': 'deterministic fixture result', 'action': {action!r}}}, indent=2)+'\\n')\nPath('mode_deliverables.json').write_text(json.dumps({deliverables!r}, indent=2)+'\\n')\n{mutation}\n"""
        return {
            "files": [{"path": "experiment.py", "content": code, "executable": False}],
            "command": [sys.executable, "experiment.py"],
            "expected_metrics": {"metric_key": metric_key, "metric_direction": config.metric_direction},
            "mode_deliverables": {config.strictness_mode: deliverables[config.strictness_mode]},
            "risks": ["fixture runner produces deterministic synthetic metrics"],
        }


class CodexRunner(AgentRunner):
    def run(self, prompt: dict[str, Any], config: ResearchConfig) -> dict[str, Any]:
        cmd = [config.codex_cmd, "--ask-for-approval", "never", "exec", "--sandbox", "read-only"]
        schema = Path(__file__).resolve().parents[2] / "schemas" / "agent-manifest.schema.json"
        if schema.exists():
            cmd += ["--output-schema", str(schema)]
        if config.codex_model:
            cmd += ["--model", config.codex_model]
        proc = subprocess.run(cmd, input=json.dumps(prompt, indent=2), text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(f"codex exec failed with {proc.returncode}: {proc.stderr}")
        return json.loads(proc.stdout)


def make_runner(kind: str) -> AgentRunner:
    return CodexRunner() if kind == "codex" else FixtureRunner()
