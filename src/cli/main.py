#!/usr/bin/env python3
"""Agent-facing helper CLI for the active AI Scientist workflows."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core import agents as core_agents
from core.state import (
    TERMINAL_PHASE_STATUSES,
    append_journal_event,
    audit_block_reason,
    clear_active_run,
    has_release_evidence,
    load_active_run,
    load_loop_state,
    run_dir,
    validate_active_run_contract,
)
from research import workflow as research_workflow
from writeup.state import (
    collect_figures as writeup_collect_figures,
    compile_pdf as writeup_compile_pdf,
    complete_audit as writeup_complete_audit,
    complete_writeup as writeup_complete_writeup,
    dependency_status as writeup_dependency_status,
    negative_complete as writeup_negative_complete,
    record_reports as writeup_record_reports,
    start_audit as writeup_start_audit,
    start_writeup,
)


class CliError(Exception):
    pass


def target_repo(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "target_repo", None) or Path.cwd()).resolve()


def active_run(target: Path, run_id: str | None = None) -> tuple[str, dict[str, Any] | None]:
    if run_id:
        state = load_loop_state(target, run_id)
        if state:
            reason = audit_block_reason(target, run_id, state)
            if reason:
                raise CliError(reason)
        return run_id, state
    active = load_active_run(target)
    if not isinstance(active, dict) or not isinstance(active.get("run_id"), str):
        raise CliError("no active AI Scientist run; pass --run-id")
    reason = validate_active_run_contract(active)
    if reason:
        raise CliError(f"active-run.json invalid: {reason}")
    rid = active["run_id"]
    state = load_loop_state(target, rid)
    if state:
        block_reason = audit_block_reason(target, rid, state)
        if block_reason:
            raise CliError(block_reason)
    return rid, state


def response(status: str, **fields: Any) -> int:
    sys.stdout.write(json.dumps({"status": status, **fields}, indent=2, sort_keys=True) + "\n")
    return 0 if status == "ok" else 1


def inline_json_payload(args: argparse.Namespace) -> dict[str, Any]:
    value = json.loads(args.json)
    if not isinstance(value, dict):
        raise CliError("payload must be a JSON object")
    return value


def cmd_validate_run(args: argparse.Namespace) -> int:
    from validation.run import main as validate_run_main

    argv = [str(args.target), "--gate", args.gate]
    if args.run_id:
        argv.extend(["--run-id", args.run_id])
    return validate_run_main(argv)


def cmd_validate_loop_state(args: argparse.Namespace) -> int:
    from validation.run import ValidationError, ai_root, pick_run, validate_loop_state_run

    target = Path(args.target) if args.target else target_repo(args)
    try:
        root = ai_root(target)
        run = pick_run(root, args.run_id)
    except ValidationError as exc:
        return response("error", error=str(exc), problems=[str(exc)])
    problems = validate_loop_state_run(root, run)
    return response("ok" if not problems else "error", run_id=run.name, run_dir=str(run), problems=problems)


def cmd_agents_install(args: argparse.Namespace) -> int:
    installed = core_agents.install_agents(
        codex_home=args.codex_home,
        target_repo=args.agent_target_repo,
        force=args.force,
    )
    agents_dir = core_agents.target_agents_dir(args.codex_home, args.agent_target_repo)
    return response("ok", agents_dir=str(agents_dir), installed=installed)


def _dependency_error_message(status: dict[str, Any]) -> str:
    missing = []
    if status.get("missing_python"):
        missing.append("Python packages: " + ", ".join(str(item) for item in status["missing_python"]))
    if status.get("missing_executables"):
        missing.append("executables: " + ", ".join(str(item) for item in status["missing_executables"]))
    return "missing writeup dependency (" + "; ".join(missing) + "). Install the missing dependency and rerun this command."


def cmd_writeup_doctor(_args: argparse.Namespace) -> int:
    status = writeup_dependency_status(include_tex=True)
    if not status.get("ok"):
        return response("error", error=_dependency_error_message(status), dependencies=status)
    return response("ok", dependencies=status)


def cmd_writeup_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    state = start_writeup(target, args.run_id, require_pdf=True)
    return response(
        "ok",
        run_id=args.run_id,
        state_path=str(run_dir(target, args.run_id) / "loop-state.json"),
        next_action=state.get("state", {}).get("orchestrator", {}).get("next_action"),
    )


def cmd_writeup_collect_figures(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    manifest = writeup_collect_figures(target, run_id)
    return response(
        "ok",
        run_id=run_id,
        figure_manifest="writeup/figures/figure-manifest.json",
        figure_count=len(manifest.get("figures", [])),
    )


def cmd_writeup_record_reports(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    manifest = writeup_record_reports(target, run_id, args.markdown, args.latex)
    return response("ok", run_id=run_id, manifest="writeup/manifest.json", require_pdf=manifest.get("require_pdf"))


def cmd_writeup_compile(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    log = writeup_compile_pdf(target, run_id, tex_path=args.tex)
    return response("ok", run_id=run_id, compile_log="writeup/compile-log.json", report_pdf=log.get("report_pdf"))


def cmd_writeup_audit_start(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    prompt = writeup_start_audit(target, run_id)
    return response("ok", run_id=run_id, pending_audit="writeup/audit/pending-final-audit.json", prompt=prompt)


def cmd_writeup_audit_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    audit = writeup_complete_audit(target, run_id, inline_json_payload(args))
    return response("ok", run_id=run_id, audit="writeup/audit/final-audit.json", verdict=audit.get("verdict"))


def cmd_writeup_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    state = writeup_complete_writeup(target, run_id)
    return response(
        "ok",
        run_id=run_id,
        state_path=str(run_dir(target, run_id) / "loop-state.json"),
        active=state.get("active"),
        phase_status=state.get("phase_status"),
        active_run_status="validating",
    )


def cmd_writeup_negative_complete(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    state = writeup_negative_complete(target, run_id, args.reason)
    return response("ok", run_id=run_id, active=state.get("active"), phase_status=state.get("phase_status"), reason=args.reason)


def cmd_validation_record(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, _ = active_run(target, args.run_id)
    append_journal_event(
        target,
        run_id,
        "validation",
        details={
            "gate": args.gate,
            "exit_code": args.exit_code,
            "validator_exit_code": args.exit_code,
            "command": args.command,
        },
    )
    return response("ok", run_id=run_id, gate=args.gate, exit_code=args.exit_code)


def cmd_handoff_record(args: argparse.Namespace) -> int:
    target = target_repo(args)
    run_id, state = active_run(target, args.run_id)
    append_journal_event(
        target,
        run_id,
        "handoff",
        details={
            "gate": args.gate,
            "approved": args.approved,
            "exit_code": args.exit_code,
            "validator_exit_code": args.exit_code,
            "reason": args.reason,
        },
    )
    if (
        args.approved
        and state
        and str(state.get("phase_status") or "") in TERMINAL_PHASE_STATUSES
        and has_release_evidence(target, run_id, str(state.get("phase") or "research"))
    ):
        clear_active_run(target, run_id)
    return response("ok", run_id=run_id, gate=args.gate, approved=args.approved)


def cmd_dashboard(args: argparse.Namespace) -> int:
    from dashboard.frontend import FrontendBuildError, ensure_built
    from dashboard.server import serve

    if args.build_only:
        try:
            state = ensure_built(force=True)
        except FrontendBuildError as exc:
            return response("error", error=str(exc))
        return response("ok", frontend=state)
    if not args.dev and not args.no_build:
        try:
            ensure_built()  # rebuild only when dist/ is missing or older than the sources
        except FrontendBuildError as exc:
            return response("error", error=str(exc))
    serve(target_repo(args), host=args.host, port=args.port, open_browser=args.open, dev=args.dev, dev_port=args.dev_port)
    return 0


def _message_box_run_id(args: argparse.Namespace, target: Path) -> str:
    if args.run_id:
        return args.run_id
    active = load_active_run(target)
    if not isinstance(active, dict) or not isinstance(active.get("run_id"), str):
        raise CliError("no active AI Scientist run; pass --run-id")
    return active["run_id"]


def cmd_message_box_add(args: argparse.Namespace) -> int:
    from core.message_box import MessageBoxError, add

    target = target_repo(args)
    prompt = args.prompt_file.read_text() if args.prompt_file else (args.prompt or "")
    try:
        record = add(target, _message_box_run_id(args, target), args.node_id, args.kind, prompt)
    except MessageBoxError as exc:
        return response("error", error=str(exc))
    return response("ok", message=record)


def cmd_message_box_list(args: argparse.Namespace) -> int:
    from core.message_box import list_messages

    target = target_repo(args)
    run_id = _message_box_run_id(args, target)
    messages = list_messages(target, run_id, status=args.status, node_id=args.node_id)
    return response("ok", run_id=run_id, count=len(messages), messages=messages)


def cmd_message_box_update(args: argparse.Namespace) -> int:
    from core.message_box import MessageBoxError, update

    target = target_repo(args)
    try:
        record = update(
            target,
            _message_box_run_id(args, target),
            args.id,
            args.status,
            work_id=args.work_id,
            result_node_id=args.result_node_id,
            note=args.note,
        )
    except MessageBoxError as exc:
        return response("error", error=str(exc))
    return response("ok", message=record)


def add_json_file_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json-file", type=Path, required=True, help="Path to a JSON object payload.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-repo", type=Path, help="Target repository. Defaults to current working directory.")
    sub = parser.add_subparsers(dest="area", required=True)

    validate = sub.add_parser("validate")
    validate_sub = validate.add_subparsers(dest="command", required=True)
    validate_run = validate_sub.add_parser("run")
    validate_run.add_argument("target", type=Path)
    validate_run.add_argument("--gate", choices=["research_to_review", "review_to_writeup", "launch"], required=True)
    validate_run.add_argument("--run-id")
    validate_run.set_defaults(func=cmd_validate_run)
    validate_loop_state = validate_sub.add_parser("loop-state", help="Check loop-state.json and journal.jsonl against docs/SCHEMA.md.")
    validate_loop_state.add_argument("target", nargs="?", type=Path, help="Target repo or .ai-scientist directory. Defaults to --target-repo.")
    validate_loop_state.add_argument("--run-id")
    validate_loop_state.set_defaults(func=cmd_validate_loop_state)

    agents = sub.add_parser("agents")
    agents_sub = agents.add_subparsers(dest="command", required=True)
    agents_install = agents_sub.add_parser("install")
    agents_install.add_argument("--codex-home", type=Path)
    agents_install.add_argument("--target-repo", dest="agent_target_repo", type=Path)
    agents_install.add_argument("--force", action="store_true")
    agents_install.set_defaults(func=cmd_agents_install)
    research = sub.add_parser("research")
    research_sub = research.add_subparsers(dest="command", required=True)
    research_resume = research_sub.add_parser("resume")
    research_resume.add_argument("--run-id")
    research_resume.set_defaults(func=research_workflow.cmd_research_resume)
    research_checkpoint = research_sub.add_parser("checkpoint")
    research_checkpoint.add_argument("--run-id")
    add_json_file_arg(research_checkpoint)
    research_checkpoint.set_defaults(func=research_workflow.cmd_research_checkpoint)
    research_select = research_sub.add_parser("select")
    research_select.add_argument("--run-id")
    research_select.add_argument("--node-id", required=True)
    research_select.add_argument("--summary")
    research_select.add_argument("--evidence-ref", action="append")
    research_select.add_argument("--acceptance-rationale")
    research_select.set_defaults(func=research_workflow.cmd_research_select)
    research_complete = research_sub.add_parser("complete")
    research_complete.add_argument("--run-id")
    add_json_file_arg(research_complete)
    research_complete.set_defaults(func=research_workflow.cmd_research_complete)
    research_cancel = research_sub.add_parser("cancel")
    research_cancel.add_argument("--run-id")
    research_cancel.add_argument("--reason", required=True)
    research_cancel.set_defaults(func=research_workflow.cmd_research_cancel)

    writeup = sub.add_parser("writeup")
    writeup_sub = writeup.add_subparsers(dest="command", required=True)
    writeup_doctor = writeup_sub.add_parser("doctor")
    writeup_doctor.set_defaults(func=cmd_writeup_doctor)
    writeup_start = writeup_sub.add_parser("start")
    writeup_start.add_argument("--run-id", required=True)
    writeup_start.set_defaults(func=cmd_writeup_start)
    writeup_figures = writeup_sub.add_parser("collect-figures")
    writeup_figures.add_argument("--run-id")
    writeup_figures.set_defaults(func=cmd_writeup_collect_figures)
    writeup_record = writeup_sub.add_parser("record-reports")
    writeup_record.add_argument("--run-id")
    writeup_record.add_argument("--markdown", type=Path, default=Path("writeup/report.md"))
    writeup_record.add_argument("--latex", type=Path, default=Path("writeup/latex/template.tex"))
    writeup_record.set_defaults(func=cmd_writeup_record_reports)
    writeup_compile = writeup_sub.add_parser("compile")
    writeup_compile.add_argument("--run-id")
    writeup_compile.add_argument("--tex", type=Path)
    writeup_compile.set_defaults(func=cmd_writeup_compile)
    writeup_audit_start = writeup_sub.add_parser("audit-start")
    writeup_audit_start.add_argument("--run-id")
    writeup_audit_start.set_defaults(func=cmd_writeup_audit_start)
    writeup_audit_complete = writeup_sub.add_parser("audit-complete")
    writeup_audit_complete.add_argument("--run-id")
    writeup_audit_complete.add_argument("--json", required=True, help="Inline JSON object payload.")
    writeup_audit_complete.set_defaults(func=cmd_writeup_audit_complete)
    writeup_complete = writeup_sub.add_parser("complete")
    writeup_complete.add_argument("--run-id")
    writeup_complete.set_defaults(func=cmd_writeup_complete)
    writeup_negative = writeup_sub.add_parser("negative-complete")
    writeup_negative.add_argument("--run-id")
    writeup_negative.add_argument("--reason", required=True)
    writeup_negative.set_defaults(func=cmd_writeup_negative_complete)

    release_gates = ["research_to_review", "review_to_writeup", "launch"]
    validation = sub.add_parser("validation")
    validation_sub = validation.add_subparsers(dest="command", required=True)
    validation_record = validation_sub.add_parser("record")
    validation_record.add_argument("--run-id")
    validation_record.add_argument("--gate", required=True, choices=release_gates)
    validation_record.add_argument("--exit-code", type=int, required=True)
    validation_record.add_argument("--command")
    validation_record.set_defaults(func=cmd_validation_record)

    handoff = sub.add_parser("handoff")
    handoff_sub = handoff.add_subparsers(dest="command", required=True)
    handoff_record = handoff_sub.add_parser("record")
    handoff_record.add_argument("--run-id")
    handoff_record.add_argument("--gate", required=True, choices=release_gates)
    handoff_record.add_argument("--exit-code", type=int, default=0)
    handoff_record.add_argument("--approved", action="store_true")
    handoff_record.add_argument("--reason")
    handoff_record.set_defaults(func=cmd_handoff_record)

    message_box = sub.add_parser("message-box", help="Human steering messages targeting one node of a research run (docs/SCHEMA.md 3.11).")
    message_box_sub = message_box.add_subparsers(dest="command", required=True)
    mb_add = message_box_sub.add_parser("add", help="Queue a message for the orchestrator.")
    mb_add.add_argument("--run-id")
    mb_add.add_argument("--node-id", required=True)
    mb_add.add_argument("--kind", choices=["revision", "branch"], required=True)
    mb_prompt = mb_add.add_mutually_exclusive_group(required=True)
    mb_prompt.add_argument("--prompt")
    mb_prompt.add_argument("--prompt-file", type=Path)
    mb_add.set_defaults(func=cmd_message_box_add)
    mb_list = message_box_sub.add_parser("list", help="List messages, optionally filtered by status or node.")
    mb_list.add_argument("--run-id")
    mb_list.add_argument("--status", choices=["pending", "acknowledged", "completed", "rejected", "cancelled"])
    mb_list.add_argument("--node-id")
    mb_list.set_defaults(func=cmd_message_box_list)
    mb_update = message_box_sub.add_parser("update", help="Record what the orchestrator did with a message.")
    mb_update.add_argument("--run-id")
    mb_update.add_argument("--id", required=True)
    mb_update.add_argument("--status", choices=["acknowledged", "completed", "rejected", "cancelled"], required=True)
    mb_update.add_argument("--work-id")
    mb_update.add_argument("--result-node-id")
    mb_update.add_argument("--note")
    mb_update.set_defaults(func=cmd_message_box_update)

    dashboard = sub.add_parser("dashboard", help="Serve the monitoring dashboard over .ai-scientist/ artifacts.")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--open", action="store_true", help="Open the dashboard in a browser.")
    dashboard.add_argument("--dev", action="store_true", help="Also run the Vite dev server (hot reload) and open that instead of the built frontend.")
    dashboard.add_argument("--dev-port", type=int, default=5173, help="Port for the Vite dev server with --dev.")
    dashboard.add_argument("--no-build", action="store_true", help="Serve dist/ as is, even when the frontend sources are newer.")
    dashboard.add_argument("--build-only", action="store_true", help="Build the frontend into src/frontend/dist and exit.")
    dashboard.set_defaults(func=cmd_dashboard)

    resource = sub.add_parser("resource")
    resource_sub = resource.add_subparsers(dest="command", required=True)
    resource_status = resource_sub.add_parser("status")
    resource_status.add_argument("--run-id")
    resource_status.set_defaults(func=research_workflow.cmd_resource_status)
    resource_acquire = resource_sub.add_parser("acquire")
    resource_acquire.add_argument("--run-id")
    resource_acquire.add_argument("--task-id", required=True)
    resource_acquire.add_argument("--gpus", type=int, default=0)
    resource_acquire.add_argument("--cpu-cores", type=int, default=0)
    resource_acquire.add_argument("--memory-mb", type=int, default=0)
    resource_acquire.add_argument("--timeout-sec", type=float, default=0.0)
    resource_acquire.add_argument("--poll-sec", type=float, default=5.0)
    resource_acquire.set_defaults(func=research_workflow.cmd_resource_acquire)
    resource_release = resource_sub.add_parser("release")
    resource_release.add_argument("--run-id")
    resource_release.add_argument("--lease-id", required=True)
    resource_release.set_defaults(func=research_workflow.cmd_resource_release)
    resource_run = resource_sub.add_parser("run")
    resource_run.add_argument("--run-id")
    resource_run.add_argument("--task-id", required=True)
    resource_run.add_argument("--purpose", default="benchmark")
    resource_run.add_argument("--cwd")
    resource_run.add_argument("--env-json")
    resource_run.add_argument("--metrics-path")
    resource_run.add_argument("--metrics-json")
    resource_run.add_argument("--notes", default="")
    resource_run.add_argument("--gpus", type=int, default=0)
    resource_run.add_argument("--cpu-cores", type=int, default=0)
    resource_run.add_argument("--memory-mb", type=int, default=0)
    resource_run.add_argument("--timeout-sec", type=float, default=0.0)
    resource_run.add_argument("--poll-sec", type=float, default=5.0)
    resource_run.add_argument("--scheduler", choices=["local", "slurm"])
    resource_run.add_argument("--partition")
    resource_run.add_argument("--time", dest="time_limit")
    resource_run.add_argument("--gres")
    resource_run.add_argument("--cpus-per-task")
    resource_run.add_argument("--mem")
    resource_run.add_argument("--job-name")
    resource_run.add_argument("--sbatch-arg", action="append")
    resource_run.add_argument("command", nargs=argparse.REMAINDER)
    resource_run.set_defaults(func=research_workflow.cmd_resource_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - helper CLI reports structured failures.
        return response("error", error=str(exc), error_type=exc.__class__.__name__)


if __name__ == "__main__":
    raise SystemExit(main())
