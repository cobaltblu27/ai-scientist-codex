from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .journal import append_jsonl, utc_now


@dataclass
class NodeTask:
    node_id: str
    action: str
    parent_node_id: str | None = None
    gpus: int = 0
    cpu_cores: int = 0
    memory_mb: int = 0


class ResourceLimiter:
    def __init__(self, max_parallel: int, max_gpus: int | None = None, max_cpu_cores: int | None = None, max_memory_mb: int | None = None) -> None:
        self.max_parallel = max_parallel
        self.max_gpus = max_gpus
        self.max_cpu_cores = max_cpu_cores
        self.max_memory_mb = max_memory_mb
        self.running = 0
        self.gpus = 0
        self.cpu_cores = 0
        self.memory_mb = 0

    def can_ever_fit(self, gpus: int = 0, cpu_cores: int = 0, memory_mb: int = 0) -> bool:
        if self.max_gpus is not None and gpus > self.max_gpus:
            return False
        if self.max_cpu_cores is not None and cpu_cores > self.max_cpu_cores:
            return False
        if self.max_memory_mb is not None and memory_mb > self.max_memory_mb:
            return False
        return True

    def acquire(self, gpus: int = 0, cpu_cores: int = 0, memory_mb: int = 0) -> bool:
        if not self.can_ever_fit(gpus, cpu_cores, memory_mb):
            return False
        if self.running >= self.max_parallel:
            return False
        if self.max_gpus is not None and self.gpus + gpus > self.max_gpus:
            return False
        if self.max_cpu_cores is not None and self.cpu_cores + cpu_cores > self.max_cpu_cores:
            return False
        if self.max_memory_mb is not None and self.memory_mb + memory_mb > self.max_memory_mb:
            return False
        self.running += 1
        self.gpus += gpus
        self.cpu_cores += cpu_cores
        self.memory_mb += memory_mb
        return True

    def release(self, gpus: int = 0, cpu_cores: int = 0, memory_mb: int = 0) -> None:
        self.running = max(0, self.running - 1)
        self.gpus = max(0, self.gpus - gpus)
        self.cpu_cores = max(0, self.cpu_cores - cpu_cores)
        self.memory_mb = max(0, self.memory_mb - memory_mb)


class FifoDispatcher:
    def __init__(self, events_path: Path, max_parallel: int, max_gpus: int | None = None, max_cpu_cores: int | None = None, max_memory_mb: int | None = None) -> None:
        self.events_path = events_path
        self.queue: deque[NodeTask] = deque()
        self.resources = ResourceLimiter(max_parallel, max_gpus, max_cpu_cores, max_memory_mb)

    def enqueue_many(self, tasks: Iterable[NodeTask]) -> None:
        for task in tasks:
            self.queue.append(task)
            self.event("enqueue", task)

    def event(self, event: str, task: NodeTask, **extra: Any) -> None:
        append_jsonl(self.events_path, {"at": utc_now(), "event": event, "node_id": task.node_id, "action": task.action, **extra})

    def run(self, handler) -> list[Any]:
        results = []
        while self.queue:
            task = self.queue.popleft()
            if not self.resources.acquire(task.gpus, task.cpu_cores, task.memory_mb):
                if not self.resources.can_ever_fit(task.gpus, task.cpu_cores, task.memory_mb):
                    self.event("blocked_resource_cap", task, gpus=task.gpus, cpu_cores=task.cpu_cores, memory_mb=task.memory_mb)
                    raise RuntimeError(f"node {task.node_id} requests resources beyond configured caps")
                self.queue.append(task)
                continue
            self.event("start", task, gpus=task.gpus, cpu_cores=task.cpu_cores, memory_mb=task.memory_mb)
            try:
                result = handler(task)
                results.append(result)
                self.event("finish", task, status=result.get("status") if isinstance(result, dict) else "unknown")
            except Exception as exc:  # fail-closed but keep deterministic event trail
                self.event("error", task, error=str(exc))
                raise
            finally:
                self.resources.release(task.gpus, task.cpu_cores, task.memory_mb)
        return results
