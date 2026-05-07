#!/usr/bin/env python3
"""Codex-native AI Scientist ideation orchestrator.

This script ports the reference ideation loop into a Codex plugin shape:
Python owns deterministic orchestration, Semantic Scholar lookup, and artifact IO;
Codex agent subprocesses own proposal, reflection/refinement, and finalization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODES = {"scientist", "researcher", "balanced", "builder", "engineer"}
ALLOWED_FINAL_DECISIONS = {"finalize", "continue", "skip"}
DEFAULT_CODEX_IDEATION_MODEL = "gpt-5.5"
DEFAULT_CODEX_IDEATION_REASONING_EFFORT = "xhigh"

IDEA_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "title",
        "hypothesis",
        "scientific_insight",
        "related_work",
        "abstract",
        "novelty_rationale",
        "required_data",
        "expected_metric",
        "execution_plan",
        "experiments",
        "risks",
        "minimum_evidence",
    ],
    "properties": {
        "id": {"type": "string", "description": "Stable idea identifier."},
        "title": {"type": "string", "minLength": 12, "description": "Catchy, specific research-proposal title."},
        "hypothesis": {
            "type": "string",
            "minLength": 80,
            "description": "Falsifiable central hypothesis, including why this setting tests it better than simpler alternatives.",
        },
        "scientific_insight": {
            "type": "string",
            "minLength": 120,
            "description": "The non-obvious mechanism, causal story, or conceptual reframing that makes the idea scientifically interesting.",
        },
        "related_work": {
            "type": "string",
            "minLength": 120,
            "description": "Concrete related work, what each line of work does, and how this idea is not a trivial extension.",
        },
        "abstract": {
            "type": "string",
            "minLength": 180,
            "description": "Conference-style proposal abstract summarizing problem, method, expected result, and why it matters.",
        },
        "novelty_rationale": {
            "type": "string",
            "minLength": 80,
            "description": "Specific novelty claim grounded in the related work and target benchmark/repository context.",
        },
        "required_data": {"type": "string", "minLength": 40},
        "expected_metric": {"type": "string", "minLength": 40},
        "execution_plan": {
            "type": "array",
            "minItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["step", "purpose", "method", "success_criteria"],
                "properties": {
                    "step": {"type": "string", "minLength": 8},
                    "purpose": {"type": "string", "minLength": 20},
                    "method": {"type": "string", "minLength": 40},
                    "success_criteria": {"type": "string", "minLength": 20},
                },
            },
        },
        "experiments": {
            "type": "array",
            "minItems": 3,
            "items": {"type": "string", "minLength": 40},
        },
        "risks": {
            "type": "array",
            "minItems": 3,
            "items": {"type": "string", "minLength": 20},
        },
        "minimum_evidence": {
            "type": "array",
            "minItems": 4,
            "items": {"type": "string", "minLength": 30},
        },
        "semantic_scholar_queries": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}
PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["idea", "search_queries", "agent_notes"],
    "properties": {
        "idea": IDEA_OUTPUT_SCHEMA,
        "search_queries": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {"type": "string"},
        },
        "agent_notes": {"type": "string"},
    },
}

REFLECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "critique",
        "literature_takeaways",
        "refined_idea",
        "next_search_query",
        "agent_notes",
    ],
    "properties": {
        "critique": {"type": "string"},
        "literature_takeaways": {
            "type": "array",
            "items": {"type": "string"},
        },
        "refined_idea": IDEA_OUTPUT_SCHEMA,
        "next_search_query": {"type": ["string", "null"]},
        "agent_notes": {"type": "string"},
    },
}

FINALIZATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reason", "final_idea", "agent_notes"],
    "properties": {
        "decision": {"enum": sorted(ALLOWED_FINAL_DECISIONS)},
        "reason": {"type": "string"},
        "final_idea": {"anyOf": [IDEA_OUTPUT_SCHEMA, {"type": "null"}]},
        "agent_notes": {"type": "string"},
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return (slug or "ideation")[:max_len].strip("-") or "ideation"


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return args.prompt.strip()
    if not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
        if prompt:
            return prompt
    raise SystemExit("ERROR: provide --prompt or pipe a prompt on stdin")


def ensure_s2_key() -> str:
    key = os.environ.get("S2_API_KEY", "").strip()
    if not key:
        raise SystemExit("ERROR: S2_API_KEY must be set before starting ideation")
    return key


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("empty agent output")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for candidate in fenced:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("agent output did not contain a JSON object")


def stable_query(prompt: str, idea: dict[str, Any]) -> str:
    parts = [
        idea.get("title", ""),
        idea.get("hypothesis", ""),
        idea.get("scientific_insight", ""),
        idea.get("related_work", ""),
        idea.get("expected_metric", ""),
        prompt,
    ]
    words = " ".join(str(p) for p in parts if p).split()
    return " ".join(words[:18]) or "machine learning research idea novelty"


def normalize_list(value: Any, fallback: list[str] | None = None) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return list(fallback or [])


def ensure_min_items(items: list[str], fallback_items: list[str], minimum: int) -> list[str]:
    result = [item for item in items if item.strip()]
    for fallback in fallback_items:
        if len(result) >= minimum:
            break
        if fallback not in result:
            result.append(fallback)
    return result


def normalize_execution_plan(value: Any, idea_id: str) -> list[dict[str, str]]:
    if isinstance(value, list):
        normalized: list[dict[str, str]] = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, dict):
                step = str(item.get("step") or f"Step {index}").strip()
                purpose = str(item.get("purpose") or "Advance the research hypothesis.").strip()
                method = str(item.get("method") or item.get("details") or "").strip()
                success_criteria = str(item.get("success_criteria") or item.get("success") or "").strip()
                if method:
                    normalized.append(
                        {
                            "step": step,
                            "purpose": purpose,
                            "method": method,
                            "success_criteria": success_criteria or "Produces auditable evidence for the declared metric and split policy.",
                        }
                    )
            elif str(item).strip():
                normalized.append(
                    {
                        "step": f"Step {index}",
                        "purpose": "Execute one concrete part of the proposed experiment.",
                        "method": str(item).strip(),
                        "success_criteria": "The step produces a logged artifact that can be compared against the declared baseline.",
                    }
                )
        if normalized:
            return normalized
    return [
        {
            "step": "Baseline reproduction",
            "purpose": "Establish the exact benchmark, split policy, and baseline metric before changing the method.",
            "method": f"Run the target repository's existing baseline for {idea_id}, record command logs, metric keys, split manifest, and leakage checks.",
            "success_criteria": "Baseline metrics and split/leakage evidence are recorded under the run artifacts.",
        },
        {
            "step": "Minimal intervention implementation",
            "purpose": "Test the central mechanism without changing the benchmark or adding confounding improvements.",
            "method": "Implement the smallest code or configuration change needed to isolate the proposed scientific insight.",
            "success_criteria": "The intervention runs end-to-end on the declared split and emits comparable metrics.",
        },
        {
            "step": "Ablation and control comparison",
            "purpose": "Separate the proposed mechanism from generic capacity, tuning, or data leakage effects.",
            "method": "Run at least one control that removes the new mechanism while keeping model capacity and data access comparable.",
            "success_criteria": "The mechanism-bearing variant improves over both the baseline and the matched control.",
        },
        {
            "step": "Failure and sensitivity analysis",
            "purpose": "Identify when the proposed mechanism does not hold and whether the result is scientifically interpretable.",
            "method": "Break down metrics by relevant regimes from the prompt, dataset, or literature and inspect representative failures.",
            "success_criteria": "The analysis reports where the effect appears, where it fails, and whether that pattern supports the hypothesis.",
        },
    ]


def normalize_idea(raw: dict[str, Any], idea_id: str) -> dict[str, Any]:
    idea = dict(raw or {})
    idea["id"] = idea_id
    hypothesis = str(idea.get("hypothesis") or idea.get("Short Hypothesis") or "").strip()
    title = str(idea.get("title") or idea.get("Title") or hypothesis[:80] or idea_id).strip()
    expected_metric = str(idea.get("expected_metric") or idea.get("Expected Metric") or "declared benchmark metric").strip()
    risks = ensure_min_items(
        normalize_list(idea.get("risks") or idea.get("Risk Factors and Limitations")),
        [
            "Novelty or feasibility may be insufficient without follow-up review.",
            "The measured gain may come from capacity, tuning, or data-processing changes rather than the proposed mechanism.",
            "The target benchmark split may be too narrow to support broad scientific claims.",
        ],
        3,
    )
    related_work = str(idea.get("related_work") or idea.get("Related Work") or "").strip()
    scientific_insight = str(idea.get("scientific_insight") or idea.get("Scientific Insight") or idea.get("insight") or "").strip()
    abstract = str(idea.get("abstract") or idea.get("Abstract") or "").strip()
    experiments = ensure_min_items(
        normalize_list(idea.get("experiments") or idea.get("Experiments")),
        [
            "Reproduce the declared baseline on the exact split and record metric, command, split-integrity, and leakage artifacts.",
            "Run the proposed mechanism-bearing intervention with the same data access and evaluation protocol as the baseline.",
            "Run a matched ablation that removes the claimed mechanism while preserving model capacity and training budget.",
        ],
        3,
    )
    minimum_evidence = ensure_min_items(
        normalize_list(idea.get("minimum_evidence")),
        [
            "Baseline comparison on the declared metric with command logs and deterministic artifact paths.",
            "Split integrity evidence showing no train/validation/test leakage or benchmark-policy changes.",
            "Ablation evidence isolating the scientific mechanism from generic capacity or tuning effects.",
            "Failure-mode analysis explaining where the hypothesized mechanism does and does not apply.",
        ],
        4,
    )
    normalized = {
        "id": idea_id,
        "title": title,
        "hypothesis": hypothesis or f"Investigate the research direction described by {idea_id}.",
        "scientific_insight": scientific_insight or f"The proposal should isolate a non-obvious mechanism for {idea_id} and make a falsifiable prediction beyond metric chasing.",
        "related_work": related_work or "Requires concrete Semantic Scholar-backed related work before research execution.",
        "abstract": abstract or f"This proposal studies {title} by testing a falsifiable mechanism on the declared benchmark, comparing against baseline-preserving controls, and reporting where the mechanism succeeds or fails.",
        "novelty_rationale": str(idea.get("novelty_rationale") or related_work or "Requires literature review.").strip(),
        "required_data": str(idea.get("required_data") or idea.get("Required Data") or "Target benchmark data as declared in config.").strip(),
        "expected_metric": expected_metric,
        "execution_plan": normalize_execution_plan(idea.get("execution_plan") or idea.get("Execution Plan") or idea.get("implementation_plan"), idea_id),
        "experiments": experiments,
        "risks": risks,
        "minimum_evidence": minimum_evidence,
        "semantic_scholar_queries": normalize_list(idea.get("semantic_scholar_queries")),
    }
    return normalized


@dataclass
class AgentResult:
    ok: bool
    payload: dict[str, Any] | None
    raw_output: str
    error: str | None = None
    command: list[str] = field(default_factory=list)
    returncode: int | None = None


class AgentRunner:
    def run(self, role: str, prompt: str, schema: dict[str, Any], log_path: Path) -> AgentResult:
        raise NotImplementedError


class CodexAgentRunner(AgentRunner):
    def __init__(
        self,
        codex_cmd: str,
        target_repo: Path,
        timeout_sec: int,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.codex_cmd = codex_cmd
        self.target_repo = target_repo
        self.timeout_sec = timeout_sec
        self.model = model
        self.reasoning_effort = reasoning_effort
        if shutil.which(codex_cmd) is None:
            raise SystemExit(f"ERROR: Codex CLI not found: {codex_cmd}")

    def run(self, role: str, prompt: str, schema: dict[str, Any], log_path: Path) -> AgentResult:
        schema_path = log_path.with_suffix(".schema.json")
        output_path = log_path.with_suffix(".last-message.json")
        write_json(schema_path, schema)
        cmd = [
            self.codex_cmd,
            "exec",
            "--cd",
            str(self.target_repo),
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        if self.model:
            cmd[2:2] = ["--model", self.model]
        if self.reasoning_effort:
            cmd[2:2] = ["--config", f'model_reasoning_effort="{self.reasoning_effort}"']
        started = utc_now()
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            record = {
                "role": role,
                "prompt": prompt,
                "command": cmd,
                "started_at": started,
                "completed_at": utc_now(),
                "ok": False,
                "error": f"timeout after {self.timeout_sec}s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }
            write_json(log_path, record)
            return AgentResult(False, None, exc.stdout or "", record["error"], cmd, None)

        raw_output = output_path.read_text() if output_path.exists() else proc.stdout
        try:
            payload = extract_json_object(raw_output)
        except Exception as exc:  # noqa: BLE001 - log parse failure verbatim
            record = {
                "role": role,
                "prompt": prompt,
                "command": cmd,
                "started_at": started,
                "completed_at": utc_now(),
                "ok": False,
                "returncode": proc.returncode,
                "error": str(exc),
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "raw_output": raw_output,
            }
            write_json(log_path, record)
            return AgentResult(False, None, raw_output, str(exc), cmd, proc.returncode)

        ok = proc.returncode == 0
        record = {
            "role": role,
            "prompt": prompt,
            "command": cmd,
            "started_at": started,
            "completed_at": utc_now(),
            "ok": ok,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "raw_output": raw_output,
            "payload": payload,
        }
        write_json(log_path, record)
        return AgentResult(ok, payload, raw_output, None if ok else proc.stderr, cmd, proc.returncode)


class FixtureAgentRunner(AgentRunner):
    """Deterministic subprocess-free runner for local smoke tests.

    Production defaults to CodexAgentRunner. This mode exists so the artifact and
    validation path can be tested without spending model calls.
    """

    def __init__(self) -> None:
        self.calls = 0

    def run(self, role: str, prompt: str, schema: dict[str, Any], log_path: Path) -> AgentResult:  # noqa: ARG002
        self.calls += 1
        idea_id_match = re.search(r"Idea id:\s*(idea-\d+)", prompt)
        idea_id = idea_id_match.group(1) if idea_id_match else f"idea-{self.calls:03d}"
        base_idea = normalize_idea(
            {
                "title": f"Fixture proposal {idea_id}",
                "hypothesis": f"A targeted intervention for {idea_id} improves the declared benchmark because it isolates one mechanism while preserving the split and data access policy.",
                "scientific_insight": "Fixture insight: a useful ideation output should explain why the proposed mechanism should change model behavior, not merely assert a metric target. The smoke runner keeps this synthetic but structurally proposal-grade.",
                "related_work": "Fixture related work summary: compare one baseline family, one mechanism-adjacent line of work, and one negative-control or leakage-risk line so the proposal can distinguish genuine novelty from a trivial extension.",
                "abstract": "This fixture proposal demonstrates the plugin's richer ideation contract. It frames a benchmark-preserving intervention, states why the mechanism should affect outcomes, names related work to compare against, and defines concrete execution and ablation evidence. The content is synthetic, but the artifact shape matches a proposal that a research-loop agent could execute and audit.",
                "novelty_rationale": "Fixture agent compares the proposal against Semantic Scholar summaries and requires the final idea to include mechanism-level novelty rather than only an expected metric.",
                "required_data": "Declared benchmark dataset, fixed split manifest, baseline command logs, and Semantic Scholar search summaries used to justify novelty.",
                "expected_metric": "Held-out accuracy on the declared split; success requires outperforming the baseline and a matched ablation without split or leakage violations.",
                "execution_plan": [
                    {
                        "step": "Reproduce baseline",
                        "purpose": "Establish the exact comparison point before any mechanism-bearing change.",
                        "method": "Run the existing baseline command on the declared split and log metrics, split integrity, leakage, and resource usage.",
                        "success_criteria": "Baseline artifacts exist and expose the metric key used by later comparisons.",
                    },
                    {
                        "step": "Implement targeted intervention",
                        "purpose": "Test the proposed mechanism with the smallest benchmark-preserving code change.",
                        "method": "Add the intervention in a node workspace while keeping data access, split policy, and training budget matched to the baseline.",
                        "success_criteria": "The intervention completes and writes comparable held-out metrics.",
                    },
                    {
                        "step": "Run matched ablation",
                        "purpose": "Check that any gain is caused by the mechanism rather than capacity or tuning.",
                        "method": "Disable the mechanism while preserving parameter budget and rerun the same evaluation command.",
                        "success_criteria": "The mechanism-bearing variant beats the matched ablation on the declared metric.",
                    },
                    {
                        "step": "Analyze failures",
                        "purpose": "Turn the result into scientific evidence rather than a leaderboard claim.",
                        "method": "Break down errors by relevant regimes and compare them to the hypothesis predictions.",
                        "success_criteria": "The report states where the mechanism helps, where it fails, and why that pattern supports or weakens the hypothesis.",
                    },
                ],
                "experiments": [
                    "Reproduce the baseline on the exact declared split and record command, metric, split-integrity, leakage, and resource artifacts.",
                    "Run the targeted intervention with the same data access and compare its held-out metric against the baseline.",
                    "Run a matched ablation that removes the proposed mechanism while preserving training budget and capacity.",
                ],
                "risks": [
                    "Synthetic fixture output is not scientific evidence.",
                    "A metric gain may come from capacity, tuning, or implementation artifacts rather than the mechanism.",
                    "The declared fixture split may be too small to support broad scientific claims.",
                ],
                "minimum_evidence": [
                    "Baseline comparison on the declared metric with command logs and artifact paths.",
                    "Split integrity and leakage checks showing no benchmark policy changes.",
                    "Matched ablation showing the proposed mechanism contributes beyond generic capacity.",
                    "Failure-mode analysis tied back to the stated scientific hypothesis.",
                ],
                "semantic_scholar_queries": [f"{idea_id} benchmark intervention"],
            },
            idea_id,
        )
        if role == "proposal":
            payload = {"idea": base_idea, "search_queries": base_idea["semantic_scholar_queries"], "agent_notes": "fixture proposal"}
        elif role == "reflection":
            payload = {
                "critique": "Fixture reflection: keep the proposal simple and benchmark-preserving.",
                "literature_takeaways": ["Search results should be used to distinguish the idea from prior work."],
                "refined_idea": base_idea,
                "next_search_query": None,
                "agent_notes": "fixture reflection",
            }
        else:
            payload = {
                "decision": "finalize",
                "reason": "Fixture finalizer accepts the schema-complete idea.",
                "final_idea": base_idea,
                "agent_notes": "fixture finalization",
            }
        write_json(
            log_path,
            {
                "role": role,
                "prompt": prompt,
                "ok": True,
                "fixture": True,
                "payload": payload,
                "completed_at": utc_now(),
            },
        )
        return AgentResult(True, payload, json.dumps(payload), None, [], 0)


class SemanticScholarClient:
    def __init__(
        self,
        api_key: str,
        ledger_path: Path,
        cache_dir: Path,
        max_results: int,
        fixture_path: Path | None = None,
    ) -> None:
        self.api_key = api_key
        self.ledger_path = ledger_path
        self.cache_dir = cache_dir
        self.max_results = max_results
        self.fixture = load_json(fixture_path) if fixture_path else None
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def search(self, query: str, idea_id: str, reflection_round: int) -> list[dict[str, Any]]:
        query = query.strip()
        cache_key = hashlib.sha256(query.encode()).hexdigest()[:16]
        cache_path = self.cache_dir / f"{cache_key}.json"
        base_record = {
            "timestamp": utc_now(),
            "phase": "ideation",
            "provider": "semantic_scholar",
            "idea_id": idea_id,
            "reflection_round": reflection_round,
            "query": query,
            "cache_key": cache_key,
            "max_results": self.max_results,
        }
        if cache_path.exists():
            cached = load_json(cache_path)
            append_jsonl(self.ledger_path, {**base_record, "ok": True, "from_cache": True, "result_count": len(cached.get("results", []))})
            return cached.get("results", [])

        if self.fixture is not None:
            results = self._fixture_results(query)
            write_json(cache_path, {"query": query, "results": results, "source": "fixture"})
            append_jsonl(self.ledger_path, {**base_record, "ok": True, "from_cache": False, "fixture": True, "result_count": len(results)})
            return results

        params = urllib.parse.urlencode(
            {
                "query": query,
                "limit": self.max_results,
                "fields": "title,authors,venue,year,abstract,citationCount,url",
            }
        )
        request = urllib.request.Request(
            f"https://api.semanticscholar.org/graph/v1/paper/search?{params}",
            headers={"X-API-KEY": self.api_key},
        )
        last_error = ""
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed official API endpoint
                    payload = json.loads(response.read().decode("utf-8"))
                papers = payload.get("data") or []
                papers.sort(key=lambda item: item.get("citationCount") or 0, reverse=True)
                results = [self._normalize_paper(paper) for paper in papers[: self.max_results]]
                write_json(cache_path, {"query": query, "results": results, "source": "semantic_scholar"})
                append_jsonl(self.ledger_path, {**base_record, "ok": True, "from_cache": False, "attempt": attempt, "result_count": len(results)})
                return results
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = str(exc)
                time.sleep(min(2 ** attempt, 8))
        append_jsonl(self.ledger_path, {**base_record, "ok": False, "from_cache": False, "error": last_error, "result_count": 0})
        return []

    def _fixture_results(self, query: str) -> list[dict[str, Any]]:
        if isinstance(self.fixture, dict):
            if query in self.fixture:
                raw = self.fixture[query]
            else:
                raw = self.fixture.get("default", [])
        else:
            raw = self.fixture or []
        return [self._normalize_paper(paper) for paper in raw[: self.max_results]]

    @staticmethod
    def _normalize_paper(paper: dict[str, Any]) -> dict[str, Any]:
        authors = paper.get("authors") or []
        return {
            "title": paper.get("title") or "Unknown title",
            "authors": [author.get("name", "Unknown") if isinstance(author, dict) else str(author) for author in authors],
            "venue": paper.get("venue") or "Unknown venue",
            "year": paper.get("year"),
            "abstract": paper.get("abstract") or "",
            "citationCount": paper.get("citationCount") or 0,
            "url": paper.get("url") or paper.get("externalIds", {}).get("CorpusId", ""),
        }


def build_proposal_prompt(prompt: str, idea_id: str, strictness_mode: str, previous_ideas: list[dict[str, Any]]) -> str:
    return f"""You are a Codex ideation subagent in a Codex-native AI Scientist plugin.
Do not edit files. Return only JSON matching the provided schema.

Think like a careful, creative research scientist writing the first draft of a grant-quality proposal.
The idea must contain an actual scientific insight: a falsifiable mechanism, causal story, or conceptual
reframing that explains why the intervention should work. Do not submit a thin metric-improvement ticket.

Goal prompt:
{prompt}

Strictness mode: {strictness_mode}
Idea id: {idea_id}
Already finalized ideas:
{json.dumps(previous_ideas, indent=2)}

Task:
Generate one distinct, feasible, proposal-grade research idea using the plugin idea schema.

Required qualities:
- Give a specific title, hypothesis, scientific_insight, related_work, abstract, novelty_rationale, required_data, expected_metric, execution_plan, experiments, risks, and minimum_evidence.
- Make the related_work concrete enough to compare against papers returned by Semantic Scholar; name the work areas or likely papers/classes of methods and explain the gap.
- Make execution_plan actionable for a later Codex research-loop agent: each step needs purpose, method, and success_criteria.
- Experiments must specify the baseline, proposed method, ablations/controls, metric, and split/leakage policy.
- Preserve the benchmark/split unless the prompt explicitly requests a new evaluation setting.
- Prefer simple, elegant interventions that isolate the insight over broad system rewrites.
- Include 1-3 Semantic Scholar search queries that Python should run before reflection.
"""


def build_reflection_prompt(
    prompt: str,
    idea_id: str,
    strictness_mode: str,
    current_idea: dict[str, Any],
    search_results: list[dict[str, Any]],
    reflection_round: int,
    num_reflections: int,
    previous_reflections: list[dict[str, Any]],
) -> str:
    return f"""You are a Codex reflection/refinement subagent in a Codex-native AI Scientist plugin.
Do not edit files. Return only JSON matching the provided schema.

Your job is to turn a rough idea into a detailed scientific proposal. Be skeptical but constructive:
strengthen the mechanism, sharpen the related-work distinction, and make the execution plan directly runnable.

Goal prompt:
{prompt}

Strictness mode: {strictness_mode}
Idea id: {idea_id}
Reflection round: {reflection_round}/{num_reflections}

Current idea:
{json.dumps(current_idea, indent=2)}

Semantic Scholar search results from Python:
{json.dumps(search_results, indent=2)}

Previous reflections:
{json.dumps(previous_reflections, indent=2)}

Task:
Critique and refine the idea while preserving the schema.

Required reflection checks:
- Scientific insight: is there a real mechanism or causal claim, not just "try feature X"?
- Related work: do the Semantic Scholar results suggest the idea is novel, duplicative, or a non-trivial adaptation?
- Execution detail: could a later agent implement the plan without inventing missing method details?
- Experiment design: are baseline, ablations, metrics, split integrity, leakage checks, and failure analysis explicit?
- Feasibility: does the idea fit an academic-lab budget and the target repository constraints?

If the idea is thin, rewrite it into a more specific proposal rather than merely criticizing it.
If another literature query would materially help, set next_search_query to that query; otherwise set it to null.
"""


def build_finalization_prompt(
    prompt: str,
    idea_id: str,
    strictness_mode: str,
    current_idea: dict[str, Any],
    reflection_history: list[dict[str, Any]],
    reflection_round: int,
    num_reflections: int,
) -> str:
    return f"""You are a Codex finalization subagent in a Codex-native AI Scientist plugin.
Do not edit files. Return only JSON matching the provided schema.

Only finalize proposal-grade ideas. A valid final idea must have a concrete scientific insight,
specific related work, a conference-style abstract, and an execution plan detailed enough for a
research-loop agent to implement without filling in major scientific blanks.

Goal prompt:
{prompt}

Strictness mode: {strictness_mode}
Idea id: {idea_id}
Reflection round: {reflection_round}/{num_reflections}

Current refined idea:
{json.dumps(current_idea, indent=2)}

Reflection history:
{json.dumps(reflection_history, indent=2)}

Task:
Decide whether this idea is ready to finalize, should continue reflection, or should be skipped.

Use "finalize" only if:
- the hypothesis is falsifiable and tied to the prompt's benchmark/scientific setting;
- scientific_insight explains why the method should work and what would falsify it;
- related_work names concrete nearby methods/papers/areas and explains the distinction;
- execution_plan has runnable steps with methods and success criteria;
- experiments include baseline, intervention, ablations/controls, metrics, split/leakage checks, and failure analysis;
- risks are substantive enough to guide review.

Use "continue" when rounds remain and the idea is promising but underspecified.
Use "skip" for incoherent, duplicative, unsafe, unsupported, or merely metric-chasing ideas.
"""


def write_static_run_artifacts(
    ai_dir: Path,
    run_dir: Path,
    run_id: str,
    target_repo: Path,
    strictness_mode: str,
    prompt: str,
    args: argparse.Namespace,
) -> None:
    write_json(
        ai_dir / "config.json",
        {
            "strictness_mode": strictness_mode,
            "target_repo": str(target_repo),
            "benchmark": args.benchmark,
            "split_policy": args.split_policy,
            "api_budgets": {
                "semantic_scholar": {
                    "phase": "ideation",
                    "max_queries": args.s2_max_queries,
                    "max_results_per_query": args.s2_max_results,
                }
            },
            "s2_enabled": True,
            "ideation": {
                "run_id": run_id,
                "num_ideas": args.num_ideas,
                "num_reflections": args.num_reflections,
                "agent_runner": args.agent_runner,
            },
        },
    )
    write_json(run_dir / "dependency-plan.json", {"planned_dependencies": []})
    write_json(
        run_dir / "journal.json",
        {
            "run_id": run_id,
            "phase": "ideation",
            "created_at": utc_now(),
            "entries": [
                {
                    "timestamp": utc_now(),
                    "event": "ideation_started",
                    "prompt": prompt,
                    "num_ideas": args.num_ideas,
                    "num_reflections": args.num_reflections,
                }
            ],
        },
    )
    write_json(
        run_dir / "principles.json",
        {
            "principles": [
                {
                    "name": "No leakage or split manipulation",
                    "gates": ["ideation_to_research", "research_to_review"],
                    "evidence_artifacts": [".ai-scientist/config.json", ".ai-scientist/runs/<run-id>/nodes/<node-id>/split_integrity.json", ".ai-scientist/runs/<run-id>/nodes/<node-id>/leakage_check.json"],
                },
                {
                    "name": "Dependency/API governance",
                    "gates": ["ideation_to_research"],
                    "evidence_artifacts": [".ai-scientist/runs/<run-id>/dependency-plan.json", ".ai-scientist/runs/<run-id>/api-ledger.jsonl"],
                },
                {
                    "name": "Auditable agent orchestration",
                    "gates": ["ideation_to_research"],
                    "evidence_artifacts": [".ai-scientist/logs/<run-id>/ideation-run.json"],
                },
            ]
        },
    )
    (run_dir / "api-ledger.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "api-ledger.jsonl").touch()


def update_journal(run_dir: Path, event: str, **fields: Any) -> None:
    journal_path = run_dir / "journal.json"
    journal = load_json(journal_path)
    journal.setdefault("entries", []).append({"timestamp": utc_now(), "event": event, **fields})
    write_json(journal_path, journal)


def run_validator(plugin_root: Path, target_repo: Path, run_id: str) -> int:
    validator = plugin_root / "scripts" / "validate_run.py"
    proc = subprocess.run(
        [sys.executable, str(validator), str(target_repo), "--gate", "ideation_to_research", "--run-id", run_id],
        text=True,
        capture_output=True,
    )
    return proc.returncode


def finalize_gate_artifacts(run_dir: Path, run_id: str, strictness_mode: str, validator_exit_code: int) -> None:
    now = utc_now()
    write_json(
        run_dir / "run-status.json",
        {
            "run_id": run_id,
            "phase": "ideation",
            "status": "validated" if validator_exit_code == 0 else "validation_failed",
            "strictness_mode": strictness_mode,
            "last_validation": {
                "gate": "ideation_to_research",
                "validated_at": now,
                "exit_code": validator_exit_code,
                "validator_exit_code": validator_exit_code,
            },
        },
    )
    handoff = {
        "run_id": run_id,
        "from_phase": "ideation",
        "to_phase": "research",
        "gate": "ideation_to_research",
        "owner": "ideation_orchestrator.py",
        "reviewer": "codex-finalizer-agent",
        "verifier": "validate_run.py",
        "evidence_path": ".ai-scientist/ideas/ideas.json",
        "validator_exit_code": validator_exit_code,
        "approved": validator_exit_code == 0,
        "approved_at": now if validator_exit_code == 0 else None,
    }
    handoff_path = run_dir / "handoff.jsonl"
    handoff_path.write_text(json.dumps(handoff, sort_keys=True) + "\n")


def choose_runner(args: argparse.Namespace, target_repo: Path) -> AgentRunner:
    if args.agent_runner == "fixture":
        return FixtureAgentRunner()
    return CodexAgentRunner(args.codex_cmd, target_repo, args.agent_timeout_sec, args.codex_model, args.codex_reasoning_effort)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", help="Research prompt to start ideation from. If omitted, stdin is used.")
    parser.add_argument("--target-repo", type=Path, default=Path.cwd(), help="Target repository where .ai-scientist artifacts are written.")
    parser.add_argument("--run-id", help="Optional run id. Defaults to ideation-<timestamp>-<prompt-slug>.")
    parser.add_argument("--num-ideas", type=int, default=10, help="Number of finalized ideas to attempt. Default: 10.")
    parser.add_argument("--num-reflections", type=int, default=5, help="Reflection/refinement rounds per idea. Default: 5.")
    parser.add_argument("--strictness-mode", choices=sorted(MODES), default="scientist")
    parser.add_argument("--benchmark", default="unspecified", help="Declared benchmark or evaluation setting.")
    parser.add_argument("--split-policy", default="Preserve the declared benchmark split; clarify before research if unspecified.")
    parser.add_argument("--s2-max-results", type=int, default=10)
    parser.add_argument("--s2-max-queries", type=int, default=None)
    parser.add_argument("--semantic-scholar-fixture", type=Path, help="Optional JSON fixture for Semantic Scholar results; still requires S2_API_KEY.")
    parser.add_argument("--agent-runner", choices=["codex", "fixture"], default="codex", help="Use codex for production; fixture is for local smoke tests.")
    parser.add_argument("--codex-cmd", default=os.environ.get("CODEX_CLI", "codex"))
    parser.add_argument("--codex-model", default=os.environ.get("CODEX_IDEATION_MODEL", DEFAULT_CODEX_IDEATION_MODEL))
    parser.add_argument("--codex-reasoning-effort", default=os.environ.get("CODEX_IDEATION_REASONING_EFFORT", DEFAULT_CODEX_IDEATION_REASONING_EFFORT))
    parser.add_argument("--agent-timeout-sec", type=int, default=900)
    args = parser.parse_args()

    if args.num_ideas <= 0:
        raise SystemExit("ERROR: --num-ideas must be positive")
    if args.num_reflections <= 0:
        raise SystemExit("ERROR: --num-reflections must be positive")
    if args.s2_max_results <= 0:
        raise SystemExit("ERROR: --s2-max-results must be positive")

    prompt = read_prompt(args)
    s2_key = ensure_s2_key()
    target_repo = args.target_repo.resolve()
    plugin_root = Path(__file__).resolve().parents[1]
    if args.s2_max_queries is None:
        args.s2_max_queries = args.num_ideas * args.num_reflections

    run_id = args.run_id or f"ideation-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{slugify(prompt)}"
    ai_dir = target_repo / ".ai-scientist"
    ideas_dir = ai_dir / "ideas"
    run_dir = ai_dir / "runs" / run_id
    logs_dir = ai_dir / "logs" / run_id
    agents_dir = logs_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    ideas_dir.mkdir(parents=True, exist_ok=True)

    write_static_run_artifacts(ai_dir, run_dir, run_id, target_repo, args.strictness_mode, prompt, args)
    runner = choose_runner(args, target_repo)
    scholar = SemanticScholarClient(
        api_key=s2_key,
        ledger_path=run_dir / "api-ledger.jsonl",
        cache_dir=logs_dir / "semantic-scholar-cache",
        max_results=args.s2_max_results,
        fixture_path=args.semantic_scholar_fixture,
    )

    finalized: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    s2_query_count = 0
    run_log: dict[str, Any] = {
        "run_id": run_id,
        "started_at": utc_now(),
        "prompt": prompt,
        "target_repo": str(target_repo),
        "num_ideas": args.num_ideas,
        "num_reflections": args.num_reflections,
        "strictness_mode": args.strictness_mode,
        "agent_runner": args.agent_runner,
        "ideas": [],
    }

    for idea_index in range(1, args.num_ideas + 1):
        idea_id = f"idea-{idea_index:03d}"
        idea_record: dict[str, Any] = {"id": idea_id, "started_at": utc_now(), "reflections": [], "status": "started"}
        run_log["ideas"].append(idea_record)
        proposal_prompt = build_proposal_prompt(prompt, idea_id, args.strictness_mode, finalized)
        proposal_result = runner.run("proposal", proposal_prompt, PROPOSAL_SCHEMA, agents_dir / f"{idea_id}-00-proposal.json")
        if not proposal_result.ok or not proposal_result.payload:
            idea_record.update({"status": "skipped", "reason": "proposal_agent_failed", "error": proposal_result.error})
            skipped.append({"id": idea_id, "reason": "proposal_agent_failed", "error": proposal_result.error})
            update_journal(run_dir, "idea_skipped", idea_id=idea_id, reason="proposal_agent_failed")
            continue

        proposal_payload = proposal_result.payload
        current_idea = normalize_idea(proposal_payload.get("idea", {}), idea_id)
        search_queries = normalize_list(proposal_payload.get("search_queries"), [stable_query(prompt, current_idea)])
        current_idea["semantic_scholar_queries"] = search_queries
        next_query = search_queries[0]
        reflection_history: list[dict[str, Any]] = []
        finalized_this_idea = False

        for reflection_round in range(1, args.num_reflections + 1):
            if s2_query_count >= args.s2_max_queries:
                search_results: list[dict[str, Any]] = []
            else:
                search_results = scholar.search(next_query, idea_id, reflection_round)
                s2_query_count += 1
            reflection_prompt = build_reflection_prompt(
                prompt,
                idea_id,
                args.strictness_mode,
                current_idea,
                search_results,
                reflection_round,
                args.num_reflections,
                reflection_history,
            )
            reflection_result = runner.run(
                "reflection",
                reflection_prompt,
                REFLECTION_SCHEMA,
                agents_dir / f"{idea_id}-{reflection_round:02d}-reflection.json",
            )
            if not reflection_result.ok or not reflection_result.payload:
                idea_record["reflections"].append({"round": reflection_round, "status": "agent_failed", "error": reflection_result.error})
                break

            reflection_payload = reflection_result.payload
            current_idea = normalize_idea(reflection_payload.get("refined_idea", current_idea), idea_id)
            if next_query and next_query not in current_idea["semantic_scholar_queries"]:
                current_idea["semantic_scholar_queries"].append(next_query)
            next_query = str(reflection_payload.get("next_search_query") or stable_query(prompt, current_idea)).strip()
            reflection_entry = {
                "round": reflection_round,
                "critique": reflection_payload.get("critique", ""),
                "literature_takeaways": reflection_payload.get("literature_takeaways", []),
                "search_query": next_query,
            }
            reflection_history.append(reflection_entry)
            idea_record["reflections"].append(reflection_entry)

            finalization_prompt = build_finalization_prompt(
                prompt,
                idea_id,
                args.strictness_mode,
                current_idea,
                reflection_history,
                reflection_round,
                args.num_reflections,
            )
            finalization_result = runner.run(
                "finalization",
                finalization_prompt,
                FINALIZATION_SCHEMA,
                agents_dir / f"{idea_id}-{reflection_round:02d}-finalization.json",
            )
            if not finalization_result.ok or not finalization_result.payload:
                idea_record["reflections"][-1]["finalization_status"] = "agent_failed"
                continue
            final_payload = finalization_result.payload
            decision = final_payload.get("decision")
            if decision not in ALLOWED_FINAL_DECISIONS:
                decision = "continue"
            idea_record["reflections"][-1]["finalization_decision"] = decision
            idea_record["reflections"][-1]["finalization_reason"] = final_payload.get("reason", "")
            if decision == "skip":
                idea_record.update({"status": "skipped", "reason": final_payload.get("reason", "finalizer skipped idea")})
                skipped.append({"id": idea_id, "reason": idea_record["reason"], "round": reflection_round})
                update_journal(run_dir, "idea_skipped", idea_id=idea_id, reason=idea_record["reason"])
                finalized_this_idea = True
                break
            if decision == "finalize":
                final_idea_raw = final_payload.get("final_idea") or current_idea
                final_idea = normalize_idea(final_idea_raw, idea_id)
                final_idea["source_run_id"] = run_id
                final_idea["reflection_count"] = reflection_round
                finalized.append(final_idea)
                idea_record.update({"status": "finalized", "finalized_at": utc_now(), "reflection_count": reflection_round})
                update_journal(run_dir, "idea_finalized", idea_id=idea_id, reflection_count=reflection_round)
                finalized_this_idea = True
                break

        if not finalized_this_idea:
            idea_record.update({"status": "skipped", "reason": "not_finalized_within_reflection_budget"})
            skipped.append({"id": idea_id, "reason": "not_finalized_within_reflection_budget"})
            update_journal(run_dir, "idea_skipped", idea_id=idea_id, reason="not_finalized_within_reflection_budget")

        write_json(logs_dir / "ideation-run.json", run_log)
        write_json(logs_dir / "skipped-ideas.json", {"skipped": skipped})
        write_json(ideas_dir / "ideas.json", {"ideas": finalized})

    run_log["completed_at"] = utc_now()
    run_log["finalized_count"] = len(finalized)
    run_log["skipped_count"] = len(skipped)
    run_log["semantic_scholar_query_count"] = s2_query_count
    write_json(logs_dir / "ideation-run.json", run_log)
    write_json(logs_dir / "final-ideas.json", {"ideas": finalized})
    write_json(logs_dir / "skipped-ideas.json", {"skipped": skipped})
    write_json(ideas_dir / "ideas.json", {"ideas": finalized})

    if not finalized:
        finalize_gate_artifacts(run_dir, run_id, args.strictness_mode, 1)
        update_journal(run_dir, "ideation_failed", reason="no_finalized_ideas")
        print(f"ERROR: no ideas finalized; see {logs_dir}", file=sys.stderr)
        return 1

    # Write optimistic gate artifacts, run the validator, then persist the real validator result.
    finalize_gate_artifacts(run_dir, run_id, args.strictness_mode, 0)
    validator_exit = run_validator(plugin_root, target_repo, run_id)
    finalize_gate_artifacts(run_dir, run_id, args.strictness_mode, validator_exit)
    update_journal(run_dir, "ideation_validation_completed", validator_exit_code=validator_exit)

    print(json.dumps({"run_id": run_id, "finalized_count": len(finalized), "skipped_count": len(skipped), "logs_dir": str(logs_dir), "ideas_path": str(ideas_dir / "ideas.json"), "validator_exit_code": validator_exit}, indent=2))
    return validator_exit


if __name__ == "__main__":
    raise SystemExit(main())
