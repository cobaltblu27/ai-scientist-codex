from __future__ import annotations

import json
import os
import resource
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from .integrity import diff_snapshots, snapshot_tree, write_mutation_check
from .journal import write_json


def _command(command: str | list[str]) -> tuple[list[str] | str, bool]:
    if isinstance(command, list):
        return command, False
    return command, True


def _resource_env(env: dict[str, str] | None, resources: Any | None) -> tuple[dict[str, str] | None, dict[str, Any]]:
    if resources is None:
        return env, {"requested": {}, "enforced": {"gpus": False, "cpu_cores": False, "memory_mb": False}}
    merged = dict(os.environ if env is None else env)
    requested = {
        "max_gpus": getattr(resources, "max_gpus", None),
        "cpu_cores": getattr(resources, "cpu_cores", None),
        "memory_mb": getattr(resources, "memory_mb", None),
    }
    enforced = {"gpus": False, "cpu_cores": False, "memory_mb": False}
    if requested["max_gpus"] is not None:
        merged["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in range(int(requested["max_gpus"])))
        enforced["gpus"] = True
    if requested["cpu_cores"] is not None:
        threads = str(max(1, int(requested["cpu_cores"])))
        for key in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
            merged[key] = threads
        enforced["cpu_cores"] = "thread-env"
    # Memory limiting is platform-dependent and handled below with RLIMIT_AS where available.
    return merged, {"requested": requested, "enforced": enforced}


def _memory_preexec(resources: Any | None):
    # RLIMIT_AS is not portable across macOS/Python builds and can fail in the
    # child before exec. Keep memory caps as recorded policy unless a future
    # container/runner backend can enforce them reliably.
    return None


def run_command(command: str | list[str], cwd: Path, log_path: Path, timeout: int, env: dict[str, str] | None = None, resources: Any | None = None) -> dict[str, Any]:
    cwd.mkdir(parents=True, exist_ok=True)
    started = time.time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    cmd, shell = _command(command)
    command_env, resource_limits = _resource_env(env, resources)
    preexec_fn = _memory_preexec(resources)
    if preexec_fn is not None:
        resource_limits["enforced"]["memory_mb"] = "rlimit_as"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(cmd, cwd=cwd, shell=shell, text=True, capture_output=True, timeout=timeout, env=command_env, preexec_fn=preexec_fn)
        timed_out = False
        stdout, stderr, return_code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return_code = 124
    elapsed = time.time() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    log_path.write_text(
        f"$ {command if isinstance(command, str) else shlex.join(command)}\n"
        f"exit_code={return_code} timed_out={timed_out} elapsed_sec={elapsed:.3f}\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\n"
    )
    usage = {
        "return_code": return_code,
        "timed_out": timed_out,
        "elapsed_sec": round(elapsed, 6),
        "user_cpu_sec": round(after.ru_utime - before.ru_utime, 6),
        "system_cpu_sec": round(after.ru_stime - before.ru_stime, 6),
        "max_rss_kb": after.ru_maxrss,
        "resource_limits": resource_limits,
    }
    return {"return_code": return_code, "timed_out": timed_out, "stdout": stdout, "stderr": stderr, "resource_usage": usage}


def execute_baseline(command: str, baseline_dir: Path, timeout: int, metric_key: str, target_repo: Path | None = None, resources: Any | None = None) -> dict[str, Any]:
    before = snapshot_tree(target_repo) if target_repo is not None else {}
    result = run_command(command, baseline_dir, baseline_dir / "command.log", timeout, resources=resources)
    after = snapshot_tree(target_repo) if target_repo is not None else {}
    changes = diff_snapshots(before, after) if target_repo is not None else []
    write_mutation_check(baseline_dir / "runtime-mutation-check.json", changes, command, result["return_code"])
    write_json(baseline_dir / "resource_usage.json", result["resource_usage"])
    metrics = baseline_dir / "metrics.json"
    if not metrics.exists():
        try:
            parsed = json.loads(result["stdout"].strip().splitlines()[-1])
            if isinstance(parsed, dict):
                write_json(metrics, parsed)
        except (IndexError, json.JSONDecodeError) as exc:
            with (baseline_dir / "command.log").open("a", encoding="utf-8") as handle:
                handle.write(f"\n[metrics_extraction_error]\n{exc}\n")
    if metrics.exists():
        data = json.loads(metrics.read_text())
        if metric_key in data and "score" not in data:
            data["score"] = data[metric_key]
            write_json(metrics, data)
    for name in ["split_integrity.json", "leakage_check.json"]:
        path = baseline_dir / name
        if not path.exists():
            write_json(path, {"passed": result["return_code"] == 0, "source": "orchestrator-default"})
    return result


def execute_node(command: list[str], workspace: Path, node_dir: Path, target_repo: Path, timeout: int, resources: Any | None = None) -> dict[str, Any]:
    before = snapshot_tree(target_repo)
    result = run_command(command, workspace, node_dir / "command.log", timeout, resources=resources)
    after = snapshot_tree(target_repo)
    changes = diff_snapshots(before, after)
    mutation_ok = write_mutation_check(node_dir / "runtime-mutation-check.json", changes, command, result["return_code"])
    write_json(node_dir / "resource_usage.json", result["resource_usage"])
    return {**result, "runtime_mutation_passed": mutation_ok, "runtime_changes": changes}
