#!/usr/bin/env python3
"""State and artifact helpers for the AI Scientist writeup phase."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.state import (
    ai_root,
    append_journal_event,
    atomic_write_json,
    clear_active_run,
    config_path,
    data_hash,
    journal_has_event,
    load_json_if_exists,
    load_loop_state,
    mutate_loop_state,
    node_json_path,
    run_dir,
    selection_path,
    set_active_run,
    start_phase,
    utc_now,
)

REQUIRED_PYTHON_DEPENDENCIES = {
    "matplotlib": "matplotlib",
    "numpy": "numpy",
    "Pillow": "PIL",
}
REQUIRED_TEX_EXECUTABLES = ("pdflatex", "bibtex")
DISCLOSURE_MARKER = "AI Scientist disclosure"
LIMITATIONS_MARKER = "limitations"
DEFAULT_REPORT_MARKDOWN = "writeup/report.md"
DEFAULT_REPORT_TEX = "writeup/latex/template.tex"
DEFAULT_REPORT_PDF = "writeup/report.pdf"


class WriteupStateError(Exception):
    pass


def dependency_status(*, include_tex: bool = True) -> dict[str, Any]:
    python_deps = [
        {
            "name": package,
            "module": module,
            "installed": importlib.util.find_spec(module) is not None,
        }
        for package, module in REQUIRED_PYTHON_DEPENDENCIES.items()
    ]
    executables = [
        {"name": name, "path": shutil.which(name), "installed": shutil.which(name) is not None}
        for name in REQUIRED_TEX_EXECUTABLES
    ] if include_tex else []
    missing_python = [item["name"] for item in python_deps if not item["installed"]]
    missing_executables = [item["name"] for item in executables if not item["installed"]]
    return {
        "ok": not missing_python and not missing_executables,
        "python": python_deps,
        "executables": executables,
        "missing_python": missing_python,
        "missing_executables": missing_executables,
    }


def require_writeup_dependencies(*, include_tex: bool = False) -> dict[str, Any]:
    status = dependency_status(include_tex=include_tex)
    missing = []
    if status["missing_python"]:
        missing.append("Python packages: " + ", ".join(status["missing_python"]))
    if status["missing_executables"]:
        missing.append("executables: " + ", ".join(status["missing_executables"]))
    if missing:
        raise WriteupStateError(
            "missing writeup dependency (" + "; ".join(missing) + "). Install the missing dependency and rerun this command."
        )
    return status



def require_tex_dependencies() -> None:
    missing = [name for name in REQUIRED_TEX_EXECUTABLES if shutil.which(name) is None]
    if missing:
        raise WriteupStateError(
            "missing writeup dependency (executables: " + ", ".join(missing) + "). Install the missing dependency and rerun this command."
        )

def _run_root(target_repo: Path, run_id: str) -> Path:
    return run_dir(target_repo, run_id)


def _writeup_root(target_repo: Path, run_id: str) -> Path:
    return _run_root(target_repo, run_id) / "writeup"


def _relative_to_run(path: Path, run: Path) -> str:
    try:
        return str(path.resolve().relative_to(run.resolve()))
    except ValueError:
        return str(path)


def _load_config(target_repo: Path, run_id: str) -> dict[str, Any]:
    cfg = load_json_if_exists(config_path(target_repo, run_id))
    if not isinstance(cfg, dict):
        cfg = load_json_if_exists(ai_root(target_repo) / "config.json")
    if not isinstance(cfg, dict):
        raise WriteupStateError("missing config.json for writeup")
    return cfg


def _load_review(run: Path) -> dict[str, Any]:
    review = load_json_if_exists(run / "review" / "structured-review.json")
    if not isinstance(review, dict):
        raise WriteupStateError("missing review/structured-review.json; run review_to_writeup before writeup")
    return review


def _journal_gate_ready(target_repo: Path, run_id: str, gate: str) -> bool:
    return journal_has_event(target_repo, run_id, "validation", gate=gate, exit_code=0) and journal_has_event(
        target_repo,
        run_id,
        "handoff",
        gate=gate,
        approved=True,
        exit_code=0,
    )


def _legacy_status_gate_ready(run: Path, gate: str) -> bool:
    status = load_json_if_exists(run / "run-status.json")
    if not isinstance(status, dict):
        return False
    validations = status.get("last_validations") if isinstance(status.get("last_validations"), dict) else {}
    validation = validations.get(gate) if isinstance(validations, dict) else None
    if not isinstance(validation, dict):
        validation = status.get("last_validation") if isinstance(status.get("last_validation"), dict) else None
    if not isinstance(validation, dict):
        return False
    return validation.get("gate") == gate and validation.get("exit_code", validation.get("validator_exit_code")) == 0


def _legacy_handoff_gate_ready(run: Path, gate: str) -> bool:
    path = run / "handoff.jsonl"
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            continue
        if record.get("gate") != gate:
            continue
        if record.get("approved") is True and record.get("validator_exit_code", record.get("exit_code")) == 0:
            return True
    return False


def review_to_writeup_ready(target_repo: Path, run_id: str) -> bool:
    run = _run_root(target_repo, run_id)
    _load_review(run)
    return _journal_gate_ready(target_repo, run_id, "review_to_writeup") or (
        _legacy_status_gate_ready(run, "review_to_writeup") and _legacy_handoff_gate_ready(run, "review_to_writeup")
    )


def _selection(target_repo: Path, run_id: str) -> dict[str, Any]:
    value = load_json_if_exists(selection_path(target_repo, run_id))
    return value if isinstance(value, dict) else {}


def _selected_node_id(target_repo: Path, run_id: str, selection: dict[str, Any]) -> str | None:
    selected = selection.get("selected_node")
    if isinstance(selected, str) and selected.strip():
        return selected
    state = load_loop_state(target_repo, run_id)
    phase_state = state.get("state") if isinstance(state, dict) and isinstance(state.get("state"), dict) else {}
    selection_state = phase_state.get("selection") if isinstance(phase_state.get("selection"), dict) else {}
    selected = selection_state.get("selected_node")
    return selected if isinstance(selected, str) and selected.strip() else None


def _load_node(target_repo: Path, run_id: str, node_id: str | None) -> dict[str, Any]:
    if not node_id:
        return {}
    node = load_json_if_exists(node_json_path(target_repo, run_id, node_id))
    if isinstance(node, dict):
        return node
    return {}


def _load_metrics(path: Path) -> dict[str, Any]:
    value = load_json_if_exists(path)
    return value if isinstance(value, dict) else {}


def _metric_value(metrics: dict[str, Any], key: str | None = None) -> float | None:
    candidates = [key, "score", "accuracy", "loss"]
    for candidate in candidates:
        if not candidate:
            continue
        value = metrics.get(candidate)
        if isinstance(value, int | float):
            return float(value)
    return None


def evidence_context(target_repo: Path, run_id: str) -> dict[str, Any]:
    run = _run_root(target_repo, run_id)
    cfg = _load_config(target_repo, run_id)
    review = _load_review(run)
    selection = _selection(target_repo, run_id)
    selected_node = _selected_node_id(target_repo, run_id, selection)
    node = _load_node(target_repo, run_id, selected_node)
    baseline_metrics = _load_metrics(run / "baseline" / "metrics.json")
    node_metrics = _load_metrics(run / "nodes" / str(selected_node) / "metrics.json") if selected_node else {}
    embedded_metrics = node.get("metrics") if isinstance(node.get("metrics"), dict) else {}
    if embedded_metrics and not node_metrics:
        node_metrics = embedded_metrics
    metric_key = selection.get("metric_key") if isinstance(selection.get("metric_key"), str) else None
    baseline_value = selection.get("baseline_metric") if isinstance(selection.get("baseline_metric"), int | float) else _metric_value(baseline_metrics, metric_key)
    selected_value = selection.get("selected_metric") if isinstance(selection.get("selected_metric"), int | float) else _metric_value(node_metrics, metric_key)
    return {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": utc_now(),
        "strictness_mode": cfg.get("strictness_mode"),
        "target_repo": cfg.get("target_repo"),
        "selected_node": selected_node,
        "metric_key": metric_key or "score",
        "metric_direction": selection.get("metric_direction"),
        "baseline_metric": baseline_value,
        "selected_metric": selected_value,
        "selection": selection,
        "baseline_metrics_path": "baseline/metrics.json" if (run / "baseline" / "metrics.json").exists() else None,
        "selected_metrics_path": f"nodes/{selected_node}/metrics.json" if selected_node and (run / "nodes" / selected_node / "metrics.json").exists() else None,
        "review_path": "review/structured-review.json",
        "review_verdict": review.get("verdict"),
        "review": review,
    }


def _evidence_pack_markdown(context: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# AI Scientist Writeup Evidence Pack",
            "",
            f"- Run: {context.get('run_id')}",
            f"- Strictness mode: {context.get('strictness_mode')}",
            f"- Selected node: {context.get('selected_node')}",
            f"- Metric: {context.get('metric_key')}",
            f"- Baseline metric: {context.get('baseline_metric')}",
            f"- Selected metric: {context.get('selected_metric')}",
            f"- Metric direction: {context.get('metric_direction')}",
            f"- Baseline metrics: {context.get('baseline_metrics_path')}",
            f"- Selected metrics: {context.get('selected_metrics_path')}",
            f"- Review artifact: {context.get('review_path')}",
            "",
            "## Required Disclosures",
            "",
            "The final report must include an AI Scientist disclosure, limitations, split integrity, leakage evidence, and failed or negative findings.",
            "",
        ]
    )


def start_writeup(target_repo: Path, run_id: str, *, require_pdf: bool = True) -> dict[str, Any]:
    if not review_to_writeup_ready(target_repo, run_id):
        raise WriteupStateError("review_to_writeup validation and approved handoff are required before writeup")
    root = _writeup_root(target_repo, run_id)
    figures = root / "figures"
    latex = root / "latex"
    audit = root / "audit"
    for directory in (figures, latex, audit):
        directory.mkdir(parents=True, exist_ok=True)
    context = evidence_context(target_repo, run_id)
    atomic_write_json(root / "evidence-context.json", context)
    (root / "evidence-pack.md").write_text(_evidence_pack_markdown(context))
    figure_manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "figures": [],
        "required": True,
    }
    atomic_write_json(figures / "figure-manifest.json", figure_manifest)
    state = start_phase(
        target_repo,
        run_id,
        "writeup",
        {
            "orchestrator": {
                "next_action": "collect_figures",
                "next_action_details": {"reason": "writeup requires at least one final-paper plot"},
            },
            "selected_node": context.get("selected_node"),
            "strictness_mode": context.get("strictness_mode"),
            "require_pdf": require_pdf,
            "artifacts": {
                "evidence_context": "writeup/evidence-context.json",
                "evidence_pack": "writeup/evidence-pack.md",
                "figure_manifest": "writeup/figures/figure-manifest.json",
            },
        },
    )
    append_journal_event(
        target_repo,
        run_id,
        "state_transition",
        details={"command": "writeup start", "phase": "writeup", "require_pdf": require_pdf},
    )
    return state


def resume_writeup(target_repo: Path, run_id: str) -> dict[str, Any]:
    state = load_loop_state(target_repo, run_id)
    if not isinstance(state, dict) or state.get("phase") != "writeup":
        raise WriteupStateError("active loop-state is not in writeup phase")
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    orchestrator = phase_state.get("orchestrator") if isinstance(phase_state.get("orchestrator"), dict) else {}
    return {
        "run_id": run_id,
        "phase_status": state.get("phase_status"),
        "next_action": orchestrator.get("next_action") or "inspect_writeup_state",
        "next_action_details": orchestrator.get("next_action_details") if isinstance(orchestrator.get("next_action_details"), dict) else {},
        "state_path": str(_run_root(target_repo, run_id) / "loop-state.json"),
        "writeup_dir": str(_writeup_root(target_repo, run_id)),
    }


def _set_next_action(target_repo: Path, run_id: str, next_action: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    def mutator(state: dict[str, Any]) -> None:
        phase_state = state.setdefault("state", {})
        orchestrator = phase_state.setdefault("orchestrator", {})
        orchestrator["next_action"] = next_action
        orchestrator["next_action_details"] = details or {}

    return mutate_loop_state(
        target_repo,
        run_id,
        "state_transition",
        {"command": "writeup set next action", "next_action": next_action},
        mutator,
    )


def collect_figures(target_repo: Path, run_id: str) -> dict[str, Any]:
    require_writeup_dependencies(include_tex=False)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from PIL import Image

    root = _writeup_root(target_repo, run_id)
    context = load_json_if_exists(root / "evidence-context.json")
    if not isinstance(context, dict):
        context = evidence_context(target_repo, run_id)
        atomic_write_json(root / "evidence-context.json", context)
    baseline = context.get("baseline_metric")
    selected = context.get("selected_metric")
    if not isinstance(baseline, int | float) or not isinstance(selected, int | float):
        raise WriteupStateError("cannot generate plot: baseline_metric and selected_metric must be numeric")
    out_dir = root / "figures" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_path = out_dir / "baseline-vs-selected.png"
    values = np.array([float(baseline), float(selected)], dtype=float)
    fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=160)
    bars = ax.bar(["Baseline", "Selected"], values, color=["#4C78A8", "#F58518"])
    ax.set_ylabel(str(context.get("metric_key") or "score"))
    ax.set_title("Baseline vs selected result")
    ax.grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, values, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2.0, value, f"{value:.4g}", ha="center", va="bottom")
    fig.tight_layout()
    fig.savefig(fig_path)
    plt.close(fig)
    with Image.open(fig_path) as image:
        width, height = image.size
    figure = {
        "id": "fig-baseline-vs-selected",
        "path": _relative_to_run(fig_path, _run_root(target_repo, run_id)),
        "kind": "bar",
        "caption": "Comparison between the baseline metric and the selected node metric.",
        "source_artifacts": [item for item in [context.get("baseline_metrics_path"), context.get("selected_metrics_path")] if item],
        "width_px": width,
        "height_px": height,
        "sha256": data_hash({"bytes_sha256": fig_path.read_bytes().hex()}),
        "generated_at": utc_now(),
    }
    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "figures": [figure],
        "required": True,
    }
    atomic_write_json(root / "figures" / "figure-manifest.json", manifest)
    _set_next_action(target_repo, run_id, "draft_reports", {"reason": "figures are available; draft markdown and latex reports"})
    append_journal_event(target_repo, run_id, "note", details={"command": "writeup collect-figures", "figure_count": 1})
    return manifest


def _read_text(path: Path, label: str) -> str:
    if not path.exists():
        raise WriteupStateError(f"missing required {label}: {path}")
    return path.read_text()


def _manifest_figures(target_repo: Path, run_id: str) -> list[dict[str, Any]]:
    manifest = load_json_if_exists(_writeup_root(target_repo, run_id) / "figures" / "figure-manifest.json")
    figures = manifest.get("figures") if isinstance(manifest, dict) else None
    if not isinstance(figures, list) or not figures:
        raise WriteupStateError("writeup requires at least one figure in writeup/figures/figure-manifest.json")
    for figure in figures:
        if not isinstance(figure, dict) or not isinstance(figure.get("path"), str):
            raise WriteupStateError("each figure manifest entry must include a path")
        if not (_run_root(target_repo, run_id) / figure["path"]).exists():
            raise WriteupStateError(f"figure file does not exist: {figure['path']}")
    return figures


def _validate_report_content(markdown: str, latex: str, figures: list[dict[str, Any]]) -> None:
    markdown_lower = markdown.lower()
    latex_lower = latex.lower()
    if DISCLOSURE_MARKER.lower() not in markdown_lower and DISCLOSURE_MARKER.lower() not in latex_lower:
        raise WriteupStateError("final report must include an AI Scientist disclosure section")
    if LIMITATIONS_MARKER not in markdown_lower and LIMITATIONS_MARKER not in latex_lower:
        raise WriteupStateError("final report must include limitations")
    for figure in figures:
        figure_path = str(figure.get("path") or "")
        if figure_path and figure_path not in markdown and Path(figure_path).name not in latex:
            raise WriteupStateError(f"final report must reference figure: {figure_path}")


def record_reports(target_repo: Path, run_id: str, markdown_path: Path, latex_path: Path) -> dict[str, Any]:
    run = _run_root(target_repo, run_id)
    markdown_path = markdown_path if markdown_path.is_absolute() else run / markdown_path
    latex_path = latex_path if latex_path.is_absolute() else run / latex_path
    figures = _manifest_figures(target_repo, run_id)
    markdown = _read_text(markdown_path, "markdown report")
    latex = _read_text(latex_path, "latex report")
    _validate_report_content(markdown, latex, figures)
    state = load_loop_state(target_repo, run_id) or {}
    phase_state = state.get("state") if isinstance(state.get("state"), dict) else {}
    require_pdf = bool(phase_state.get("require_pdf", True))
    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "report_md": _relative_to_run(markdown_path, run),
        "report_tex": _relative_to_run(latex_path, run),
        "report_pdf": DEFAULT_REPORT_PDF if require_pdf else None,
        "require_pdf": require_pdf,
        "figures": figures,
        "disclosure_present": True,
        "limitations_present": True,
        "hashes": {
            "report_md": data_hash({"text": markdown}),
            "report_tex": data_hash({"text": latex}),
            "figures": data_hash(figures),
        },
    }
    atomic_write_json(_writeup_root(target_repo, run_id) / "manifest.json", manifest)
    _set_next_action(target_repo, run_id, "compile_pdf" if require_pdf else "audit_report", {"reason": "report manifest recorded"})
    append_journal_event(target_repo, run_id, "note", details={"command": "writeup record-reports", "manifest": "writeup/manifest.json"})
    return manifest


def compile_pdf(target_repo: Path, run_id: str, *, tex_path: Path | None = None) -> dict[str, Any]:
    require_tex_dependencies()
    run = _run_root(target_repo, run_id)
    manifest = load_json_if_exists(_writeup_root(target_repo, run_id) / "manifest.json")
    if not isinstance(manifest, dict):
        raise WriteupStateError("missing writeup/manifest.json; record reports before compiling")
    tex_rel = str(tex_path or manifest.get("report_tex") or DEFAULT_REPORT_TEX)
    tex = tex_path if tex_path is not None and tex_path.is_absolute() else run / tex_rel
    if not tex.exists():
        raise WriteupStateError(f"missing LaTeX report: {tex}")
    workdir = tex.parent
    stem = tex.stem
    logs = []
    for argv in (["pdflatex", "-interaction=nonstopmode", tex.name], ["bibtex", stem], ["pdflatex", "-interaction=nonstopmode", tex.name], ["pdflatex", "-interaction=nonstopmode", tex.name]):
        proc = subprocess.run(argv, cwd=workdir, text=True, capture_output=True, check=False)
        log = {
            "argv": argv,
            "exit_code": proc.returncode,
            "stdout_path": _relative_to_run(workdir / f"{stem}.{argv[0]}.stdout", run),
            "stderr_path": _relative_to_run(workdir / f"{stem}.{argv[0]}.stderr", run),
        }
        (workdir / f"{stem}.{argv[0]}.stdout").write_text(proc.stdout)
        (workdir / f"{stem}.{argv[0]}.stderr").write_text(proc.stderr)
        logs.append(log)
        if proc.returncode != 0:
            atomic_write_json(_writeup_root(target_repo, run_id) / "compile-log.json", {"logs": logs, "status": "failed"})
            raise WriteupStateError(f"PDF compile command failed: {' '.join(argv)}")
    pdf = workdir / f"{stem}.pdf"
    if not pdf.exists():
        raise WriteupStateError(f"PDF compile finished but output is missing: {pdf}")
    final_pdf = _writeup_root(target_repo, run_id) / "report.pdf"
    shutil.copyfile(pdf, final_pdf)
    compile_log = {"logs": logs, "status": "ok", "report_pdf": _relative_to_run(final_pdf, run), "completed_at": utc_now()}
    atomic_write_json(_writeup_root(target_repo, run_id) / "compile-log.json", compile_log)
    manifest["report_pdf"] = _relative_to_run(final_pdf, run)
    manifest.setdefault("hashes", {})["report_pdf"] = data_hash({"bytes_sha256": final_pdf.read_bytes().hex()})
    atomic_write_json(_writeup_root(target_repo, run_id) / "manifest.json", manifest)
    _set_next_action(target_repo, run_id, "audit_report", {"reason": "PDF compiled; run final independent audit"})
    append_journal_event(target_repo, run_id, "note", details={"command": "writeup compile", "report_pdf": str(final_pdf)})
    return compile_log


def start_audit(target_repo: Path, run_id: str) -> dict[str, Any]:
    root = _writeup_root(target_repo, run_id)
    manifest = load_json_if_exists(root / "manifest.json")
    if not isinstance(manifest, dict):
        raise WriteupStateError("missing writeup/manifest.json; record reports before audit")
    prompt = {
        "schema_version": 1,
        "run_id": run_id,
        "role": "writeup_final_auditor",
        "instructions": [
            "Return JSON with verdict ACCEPT, REVISE, or REJECT.",
            "Check claim fidelity, disclosure, limitations, split/leakage evidence, figure references, and reproducibility artifacts.",
        ],
        "artifacts": manifest,
    }
    path = root / "audit" / "pending-final-audit.json"
    atomic_write_json(path, prompt)
    _set_next_action(target_repo, run_id, "complete_final_audit", {"pending_audit": _relative_to_run(path, _run_root(target_repo, run_id))})
    append_journal_event(target_repo, run_id, "critic_event", details={"command": "writeup audit-start", "pending_audit": str(path)})
    return prompt


def complete_audit(target_repo: Path, run_id: str, audit: dict[str, Any]) -> dict[str, Any]:
    verdict = audit.get("verdict")
    if verdict not in {"ACCEPT", "REVISE", "REJECT"}:
        raise WriteupStateError("audit verdict must be ACCEPT, REVISE, or REJECT")
    payload = {**audit, "completed_at": utc_now()}
    path = _writeup_root(target_repo, run_id) / "audit" / "final-audit.json"
    atomic_write_json(path, payload)
    next_action = "complete_writeup" if verdict == "ACCEPT" else "revise_reports"
    _set_next_action(target_repo, run_id, next_action, {"audit_verdict": verdict, "audit_path": _relative_to_run(path, _run_root(target_repo, run_id))})
    append_journal_event(target_repo, run_id, "critic_event", details={"command": "writeup audit-complete", "verdict": verdict})
    return payload


def _completion_audit(target_repo: Path, run_id: str) -> dict[str, Any]:
    run = _run_root(target_repo, run_id)
    manifest = load_json_if_exists(_writeup_root(target_repo, run_id) / "manifest.json")
    if not isinstance(manifest, dict):
        raise WriteupStateError("missing writeup/manifest.json")
    figures = _manifest_figures(target_repo, run_id)
    audit = load_json_if_exists(_writeup_root(target_repo, run_id) / "audit" / "final-audit.json")
    if not isinstance(audit, dict) or audit.get("verdict") != "ACCEPT":
        raise WriteupStateError("writeup requires final audit verdict ACCEPT")
    report_md = run / str(manifest.get("report_md") or "")
    report_tex = run / str(manifest.get("report_tex") or "")
    if not report_md.exists() or not report_tex.exists():
        raise WriteupStateError("writeup report markdown and tex files must exist")
    if manifest.get("require_pdf") is not False:
        report_pdf = run / str(manifest.get("report_pdf") or DEFAULT_REPORT_PDF)
        if not report_pdf.exists():
            raise WriteupStateError("writeup requires compiled report PDF")
    return {
        "passed": True,
        "checks": {
            "manifest_present": True,
            "report_markdown_present": True,
            "report_latex_present": True,
            "report_pdf_present": manifest.get("require_pdf") is False or (run / str(manifest.get("report_pdf") or DEFAULT_REPORT_PDF)).exists(),
            "figures_present": bool(figures),
            "disclosure_present": manifest.get("disclosure_present") is True,
            "limitations_present": manifest.get("limitations_present") is True,
            "final_audit_accept": True,
        },
        "manifest_hash": data_hash(manifest),
        "audit_hash": data_hash(audit),
        "verification_evidence": ["ai-scientist validate run --gate launch"],
    }


def complete_writeup(target_repo: Path, run_id: str) -> dict[str, Any]:
    completion_audit = _completion_audit(target_repo, run_id)

    def mutator(state: dict[str, Any]) -> None:
        state["active"] = False
        state["phase_status"] = "complete"
        state["completed_at"] = utc_now()
        state["completion_audit"] = completion_audit
        completed = state.setdefault("completed_phases", {})
        if isinstance(completed, dict):
            completed["writeup"] = {key: value for key, value in state.items() if key != "completed_phases"}

    state = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "writeup complete"}, mutator)
    set_active_run(target_repo, run_id, "writeup", "validating")
    return state


def negative_complete(target_repo: Path, run_id: str, reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise WriteupStateError("negative writeup completion requires a reason")

    def mutator(state: dict[str, Any]) -> None:
        state["active"] = False
        state["phase_status"] = "failed"
        state["run_outcome"] = "negative_or_blocked_writeup"
        state["failure_reason"] = reason
        state["completed_at"] = utc_now()

    state = mutate_loop_state(target_repo, run_id, "state_transition", {"command": "writeup negative-complete", "reason": reason}, mutator)
    clear_active_run(target_repo, run_id)
    return state
