from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from test_support import read_json

from ideation import state as ideation_state


class IdeationStateTests(unittest.TestCase):
    def _start_run_with_drafts(self, target: Path, *, count: int = 1) -> None:
        (target / "README.md").write_text("fixture target\n")
        ideation_state.start_ideation(target, "run-001", "fixture", mode="engineer", num_ideas_required=count)
        for index in range(1, count + 1):
            idea_id = f"idea-{index:03d}"
            ideation_state.record_draft(
                target,
                "run-001",
                {
                    "id": idea_id,
                    "title": f"Fixture idea {index}",
                    "hypothesis": "Changing the update rule will improve held-out score.",
                    "smoke_runnable_now": False,
                },
                idea_id=idea_id,
            )

    def _loop_state(self, target: Path) -> dict:
        return read_json(target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json")

    def _openalex_evidence(self, title: str = "OpenAlex Paper") -> dict:
        return {
            "data": [
                {
                    "title": title,
                    "year": 2024,
                    "citationCount": 7,
                    "venue": "OpenAlex Venue",
                    "url": "https://openalex.org/W1",
                    "authors": ["Ada Lovelace"],
                    "openalex_id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.1234/example",
                    "abstract": "A compact abstract.",
                }
            ]
        }

    def test_explicit_command_detection_only(self) -> None:
        self.assertTrue(ideation_state.is_ideation_command("/ideate propose ideas"))
        self.assertTrue(ideation_state.is_ideation_command("$ai-scientist ideate propose ideas"))
        self.assertTrue(ideation_state.is_ideation_command("ai-scientist: ideate propose ideas"))
        self.assertFalse(ideation_state.is_ideation_command("please brainstorm research ideas"))

    def test_initialize_writes_state_and_artifacts(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            (target / "README.md").write_text("fixture target\n")
            state = ideation_state.initialize_ideation(target, "study benchmark-preserving ideas", run_id="ideation-test", target_num_ideas=2)

            self.assertEqual(state["status"], "active")
            self.assertEqual(state["current_idea_id"], "idea-001")
            self.assertEqual(state["max_stop_continuations"], 12)
            self.assertEqual(state["next_action"]["type"], "propose")
            self.assertTrue((target / ".ai-scientist" / "state" / "active-ideation.json").exists())
            self.assertTrue((target / ".ai-scientist" / "runs" / "ideation-test" / "filesystem-baseline.json").exists())
            pointer = read_json(target / ".ai-scientist" / "state" / "active-ideation.json")
            self.assertEqual(pointer["state_file"], ".ai-scientist/runs/ideation-test/ideation-state.json")

    def test_repeated_stop_block_becomes_user_blocker(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            state = ideation_state.initialize_ideation(
                target,
                "study ideas",
                run_id="ideation-test",
                max_stop_continuations=10,
                max_repeated_block_count=2,
            )
            state = ideation_state.register_stop_block(target, state, "missing_parseable_action")
            state = ideation_state.register_stop_block(target, state, "missing_parseable_action")
            state = ideation_state.register_stop_block(target, state, "missing_parseable_action")

            self.assertEqual(state["status"], "blocked")
            self.assertEqual(state["reason"], "repeated_stop_hook_block")
            self.assertTrue(state["next_user_action_required"])

    def test_stop_continuation_limit_blocks_cleanly(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            state = ideation_state.initialize_ideation(
                target,
                "study ideas",
                run_id="ideation-test",
                max_stop_continuations=2,
            )
            state = ideation_state.register_stop_continuation(target, state)
            state = ideation_state.register_stop_continuation(target, state)
            state = ideation_state.register_stop_continuation(target, state)

            self.assertEqual(state["status"], "blocked")
            self.assertEqual(state["reason"], "max_stop_continuations_exceeded")
            self.assertTrue(state["next_user_action_required"])

    def test_action_snapshot_points_state_to_file(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            state = ideation_state.initialize_ideation(target, "study ideas", run_id="ideation-test")
            state, action_path = ideation_state.record_action(
                target,
                state,
                'ACTION:\nSearchSemanticScholar\nARGUMENTS:\n{"query": "benchmark preserving ideas"}',
                {"turn_id": "turn-abc"},
            )

            self.assertTrue(action_path.exists())
            self.assertEqual(state["last_action_file"], "actions/turn-abc-0001.json")
            record = read_json(action_path)
            self.assertEqual(record["parsed_action"]["action"], "SearchSemanticScholar")

    def test_openalex_live_failures_fallback_to_s2(self) -> None:
        failures = [
            ("403", urllib.error.HTTPError("https://example.test", 403, "Forbidden", None, None)),
            ("429", urllib.error.HTTPError("https://example.test", 429, "Too Many Requests", None, None)),
            ("500", urllib.error.HTTPError("https://example.test", 500, "Server Error", None, None)),
            ("timeout", TimeoutError("timed out")),
            ("invalid_json", json.JSONDecodeError("bad json", "{", 0)),
            ("url_error", urllib.error.URLError("network down")),
        ]
        original_s2 = ideation_state.semantic_scholar_request
        original_openalex = ideation_state.openalex_request
        for label, exc in failures:
            with self.subTest(label=label), TemporaryDirectory() as td:
                target = Path(td)
                self._start_run_with_drafts(target)
                calls = {"s2": 0, "openalex": 0}

                def failing_openalex(query: str, limit: int, failure: BaseException = exc) -> dict:
                    calls["openalex"] += 1
                    self.assertEqual(query, "fallback query")
                    raise failure

                def successful_s2(query: str, limit: int) -> dict:
                    calls["s2"] += 1
                    return {"data": [{"title": f"S2 {label}", "citationCount": 1}]}

                ideation_state.semantic_scholar_request = successful_s2
                ideation_state.openalex_request = failing_openalex
                try:
                    ideation_state.record_semantic_scholar_search(target, "run-001", idea_id="idea-001", query="fallback query")
                finally:
                    ideation_state.semantic_scholar_request = original_s2
                    ideation_state.openalex_request = original_openalex

                evidence = self._loop_state(target)["state"]["idea_states"]["idea-001"]["literature_evidence"][-1]
                self.assertEqual(evidence["provider"], "semantic_scholar")
                self.assertEqual(evidence["fallback_from"], "openalex")
                self.assertTrue(evidence["fallback_reason"])
                self.assertEqual(evidence["result_count"], 1)
                self.assertEqual(calls, {"s2": 1, "openalex": 1})
                self.assertTrue(any((target / ".ai-scientist" / "evidence-cache" / "semantic-scholar").glob("*.json")))

    def test_openalex_zero_results_is_success_without_s2_fallback(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            self._start_run_with_drafts(target)
            original_s2 = ideation_state.semantic_scholar_request
            original_openalex = ideation_state.openalex_request
            calls = {"s2": 0}

            def empty_openalex(query: str, limit: int) -> dict:
                return {"data": []}

            def unexpected_s2(query: str, limit: int) -> dict:
                calls["s2"] += 1
                return self._openalex_evidence()

            ideation_state.semantic_scholar_request = unexpected_s2
            ideation_state.openalex_request = empty_openalex
            try:
                ideation_state.record_semantic_scholar_search(target, "run-001", idea_id="idea-001", query="empty query")
            finally:
                ideation_state.semantic_scholar_request = original_s2
                ideation_state.openalex_request = original_openalex

            evidence = self._loop_state(target)["state"]["idea_states"]["idea-001"]["literature_evidence"][-1]
            self.assertEqual(evidence["provider"], "openalex")
            self.assertEqual(evidence["result_count"], 0)
            self.assertIsNone(evidence["fallback_from"])
            self.assertEqual(calls["s2"], 0)

    def test_openalex_cache_hit_does_not_call_live_providers(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            self._start_run_with_drafts(target)
            cached = {"data": [{"title": "Cached Paper", "citationCount": 1}]}
            ideation_state.record_semantic_scholar_search(target, "run-001", idea_id="idea-001", query="cache query", evidence_payload=cached)
            original_s2 = ideation_state.semantic_scholar_request
            original_openalex = ideation_state.openalex_request
            calls = {"s2": 0, "openalex": 0}

            def unexpected_s2(query: str, limit: int) -> dict:
                calls["s2"] += 1
                raise AssertionError("S2 live request should not run on OpenAlex cache hit")

            def unexpected_openalex(query: str, limit: int) -> dict:
                calls["openalex"] += 1
                raise AssertionError("OpenAlex live request should not run on cache hit")

            ideation_state.semantic_scholar_request = unexpected_s2
            ideation_state.openalex_request = unexpected_openalex
            try:
                ideation_state.record_semantic_scholar_search(target, "run-001", idea_id="idea-001", query="cache query")
            finally:
                ideation_state.semantic_scholar_request = original_s2
                ideation_state.openalex_request = original_openalex

            evidence_records = self._loop_state(target)["state"]["idea_states"]["idea-001"]["literature_evidence"]
            self.assertEqual([item["provenance"] for item in evidence_records], ["precomputed", "cache"])
            self.assertEqual(calls, {"s2": 0, "openalex": 0})

    def test_semantic_scholar_provider_does_not_fallback(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            self._start_run_with_drafts(target)
            before = (target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text()
            original_s2 = ideation_state.semantic_scholar_request
            original_openalex = ideation_state.openalex_request
            calls = {"openalex": 0}

            def failing_s2(query: str, limit: int) -> dict:
                raise urllib.error.HTTPError("https://example.test", 403, "Forbidden", None, None)

            def unexpected_openalex(query: str, limit: int) -> dict:
                calls["openalex"] += 1
                return self._openalex_evidence()

            ideation_state.semantic_scholar_request = failing_s2
            ideation_state.openalex_request = unexpected_openalex
            try:
                with self.assertRaises(urllib.error.HTTPError):
                    ideation_state.record_semantic_scholar_search(target, "run-001", idea_id="idea-001", query="strict query", provider="semantic_scholar")
            finally:
                ideation_state.semantic_scholar_request = original_s2
                ideation_state.openalex_request = original_openalex

            self.assertEqual(calls["openalex"], 0)
            self.assertEqual((target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json").read_text(), before)

    def test_openalex_provider_skips_s2_and_records_evidence(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            self._start_run_with_drafts(target)
            original_s2 = ideation_state.semantic_scholar_request
            original_openalex = ideation_state.openalex_request
            calls = {"s2": 0, "openalex": 0}

            def unexpected_s2(query: str, limit: int) -> dict:
                calls["s2"] += 1
                raise AssertionError("S2 should not run for provider=openalex")

            def successful_openalex(query: str, limit: int) -> dict:
                calls["openalex"] += 1
                return self._openalex_evidence()

            ideation_state.semantic_scholar_request = unexpected_s2
            ideation_state.openalex_request = successful_openalex
            try:
                ideation_state.record_semantic_scholar_search(target, "run-001", idea_id="idea-001", query="openalex query", provider="openalex")
            finally:
                ideation_state.semantic_scholar_request = original_s2
                ideation_state.openalex_request = original_openalex

            state = self._loop_state(target)
            idea = state["state"]["idea_states"]["idea-001"]
            evidence = idea["literature_evidence"][-1]
            self.assertEqual(evidence["provider"], "openalex")
            self.assertIsNone(evidence["fallback_from"])
            self.assertEqual(idea["literature_search_count"], 1)
            self.assertEqual(state["state"]["s2_query_count"], 1)
            self.assertTrue(Path(evidence["evidence_ref"]).exists())
            self.assertTrue(any((target / ".ai-scientist" / "evidence-cache" / "openalex").glob("*.json")))
            self.assertEqual(calls, {"s2": 0, "openalex": 1})

    def test_both_provider_failure_leaves_state_unchanged(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            self._start_run_with_drafts(target)
            state_path = target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json"
            before = state_path.read_text()
            original_s2 = ideation_state.semantic_scholar_request
            original_openalex = ideation_state.openalex_request
            ideation_state.semantic_scholar_request = lambda query, limit: (_ for _ in ()).throw(urllib.error.URLError("S2 unavailable"))
            ideation_state.openalex_request = lambda query, limit: (_ for _ in ()).throw(TimeoutError("OpenAlex timeout"))
            try:
                with self.assertRaisesRegex(ideation_state.IdeationStateError, "openalex .* semantic_scholar"):
                    ideation_state.record_semantic_scholar_search(target, "run-001", idea_id="idea-001", query="doomed query")
            finally:
                ideation_state.semantic_scholar_request = original_s2
                ideation_state.openalex_request = original_openalex

            self.assertEqual(state_path.read_text(), before)

    def test_batch_validates_idea_ids_before_provider_calls(self) -> None:
        with TemporaryDirectory() as td:
            target = Path(td)
            self._start_run_with_drafts(target)
            state_path = target / ".ai-scientist" / "runs" / "run-001" / "loop-state.json"
            before = state_path.read_text()
            original_s2 = ideation_state.semantic_scholar_request
            original_openalex = ideation_state.openalex_request
            calls = {"s2": 0, "openalex": 0}
            ideation_state.semantic_scholar_request = lambda query, limit: calls.__setitem__("s2", calls["s2"] + 1) or {"data": []}
            ideation_state.openalex_request = lambda query, limit: calls.__setitem__("openalex", calls["openalex"] + 1) or self._openalex_evidence()
            try:
                with self.assertRaisesRegex(ideation_state.IdeationStateError, "unknown idea_ids: missing-idea"):
                    ideation_state.record_evidence_batch(target, "run-001", idea_ids=["idea-001", "missing-idea"], queries=["q1", "q2"])
            finally:
                ideation_state.semantic_scholar_request = original_s2
                ideation_state.openalex_request = original_openalex

            self.assertEqual(calls, {"s2": 0, "openalex": 0})
            self.assertEqual(state_path.read_text(), before)

    def test_openalex_normalization_matches_evidence_contract(self) -> None:
        evidence = ideation_state.normalize_openalex_evidence(
            {
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "doi": "https://doi.org/10.1234/example",
                        "title": "OpenAlex Contract Paper",
                        "publication_year": 2025,
                        "cited_by_count": 42,
                        "primary_location": {"landing_page_url": "https://example.test/paper", "source": {"display_name": "Venue"}},
                        "authorships": [{"author": {"display_name": "Grace Hopper"}}],
                        "abstract_inverted_index": {"A": [0], "paper": [1]},
                    }
                ]
            }
        )
        paper = evidence["data"][0]
        self.assertEqual(paper["title"], "OpenAlex Contract Paper")
        self.assertEqual(paper["year"], 2025)
        self.assertEqual(paper["citationCount"], 42)
        self.assertEqual(paper["venue"], "Venue")
        self.assertEqual(paper["url"], "https://example.test/paper")
        self.assertEqual(paper["authors"], ["Grace Hopper"])
        self.assertEqual(paper["doi"], "https://doi.org/10.1234/example")
        self.assertEqual(paper["openalex_id"], "https://openalex.org/W123")
        self.assertEqual(paper["abstract"], "A paper")



if __name__ == "__main__":
    unittest.main()
