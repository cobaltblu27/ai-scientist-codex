from __future__ import annotations

import unittest

from test_support import import_planned_module


def node_id(started):
    if started is None:
        return None
    if isinstance(started, str):
        return started
    if isinstance(started, dict):
        return started.get("node_id") or started.get("id")
    return getattr(started, "node_id", getattr(started, "id", None))


class DispatcherTests(unittest.TestCase):
    def test_dispatcher_starts_nodes_fifo_and_respects_parallel_resource_caps(self) -> None:
        module = import_planned_module("research_loop.dispatcher")
        if hasattr(module, "Dispatcher"):
            dispatcher = module.Dispatcher(max_parallel=1, max_gpus=1, max_cpu_cores=2, max_memory_mb=1024)
            dispatcher.enqueue("node-a", resources={"gpus": 1, "cpu_cores": 1, "memory_mb": 256})
            dispatcher.enqueue("node-b", resources={"gpus": 1, "cpu_cores": 1, "memory_mb": 256})
            first = dispatcher.start_next()
            self.assertEqual(node_id(first), "node-a")
            self.assertIsNone(dispatcher.start_next(), "resource cap should prevent node-b starting before node-a finishes")
            dispatcher.finish("node-a", status="completed")
            second = dispatcher.start_next()
            self.assertEqual(node_id(second), "node-b")
            dispatcher.finish("node-b", status="completed")
            events = getattr(dispatcher, "events", [])
            event_pairs = [(getattr(e, "event", e.get("event")), getattr(e, "node_id", e.get("node_id"))) for e in events]
        else:
            self.assertTrue(hasattr(module, "FifoDispatcher"), "research_loop.dispatcher must expose Dispatcher or FifoDispatcher")
            self.assertTrue(hasattr(module, "ResourceLimiter"), "research_loop.dispatcher must expose ResourceLimiter")
            limiter = module.ResourceLimiter(max_parallel=1, max_gpus=1)
            self.assertTrue(limiter.acquire(gpus=1))
            self.assertFalse(limiter.acquire(gpus=1), "resource cap should prevent a second concurrent GPU lease")
            limiter.release(gpus=1)
            self.assertTrue(limiter.acquire(gpus=1))
            limiter.release(gpus=1)
            limiter = module.ResourceLimiter(max_parallel=2, max_gpus=None, max_cpu_cores=2, max_memory_mb=1024)
            self.assertTrue(limiter.acquire(cpu_cores=2, memory_mb=512))
            self.assertFalse(limiter.acquire(cpu_cores=1, memory_mb=600), "CPU/memory caps should prevent overcommit")
            limiter.release(cpu_cores=2, memory_mb=512)
            from tempfile import TemporaryDirectory
            from pathlib import Path
            from test_support import read_jsonl
            with TemporaryDirectory() as td:
                events_path = Path(td) / "dispatcher-events.jsonl"
                dispatcher = module.FifoDispatcher(events_path, max_parallel=1, max_gpus=1)
                dispatcher.enqueue_many([module.NodeTask("node-a", "draft"), module.NodeTask("node-b", "improve")])
                dispatcher.run(lambda task: {"status": "completed", "node_id": task.node_id})
                event_pairs = [(e["event"], e["node_id"]) for e in read_jsonl(events_path)]
        self.assertIn(("start", "node-a"), event_pairs)
        self.assertIn(("start", "node-b"), event_pairs)
        self.assertLess(event_pairs.index(("start", "node-a")), event_pairs.index(("start", "node-b")))

    def test_planned_actions_include_debug_and_scientific_branches_when_requested(self) -> None:
        orchestrator = import_planned_module("research_loop.orchestrator")
        from types import SimpleNamespace
        config = SimpleNamespace(
            max_debug_attempts=1,
            max_improve_attempts=1,
            max_tuning_attempts=1,
            max_ablation_attempts=1,
            max_nodes=5,
            strictness_mode="balanced",
        )
        self.assertEqual(orchestrator.planned_actions(config), ["draft", "debug", "improve", "tuning", "ablation"])


if __name__ == "__main__":
    unittest.main()
