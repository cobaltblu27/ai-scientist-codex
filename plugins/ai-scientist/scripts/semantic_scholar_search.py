#!/usr/bin/env python3
"""One-shot Semantic Scholar search helper for ideation hooks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ideation_state import ai_dir, append_jsonl, utc_now, write_json


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def normalize_paper(paper: dict[str, Any]) -> dict[str, Any]:
    authors = paper.get("authors") or []
    return {
        "title": paper.get("title") or "Unknown title",
        "authors": [author.get("name", "Unknown") if isinstance(author, dict) else str(author) for author in authors],
        "venue": paper.get("venue") or "Unknown venue",
        "year": paper.get("year"),
        "abstract": paper.get("abstract") or "",
        "citationCount": paper.get("citationCount") or 0,
        "url": paper.get("url") or "",
    }


def fixture_results(fixture_path: Path, query: str, max_results: int) -> list[dict[str, Any]]:
    fixture = load_json(fixture_path)
    if isinstance(fixture, dict):
        raw = fixture.get(query, fixture.get("default", []))
    else:
        raw = fixture
    return [normalize_paper(paper) for paper in raw[:max_results]]


def live_results(query: str, max_results: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "limit": max_results,
            "fields": "title,authors,venue,year,abstract,citationCount,url",
        }
    )
    headers = {}
    api_key = os.environ.get("S2_API_KEY", "").strip()
    if api_key:
        headers["X-API-KEY"] = api_key
    request = urllib.request.Request(f"https://api.semanticscholar.org/graph/v1/paper/search?{params}", headers=headers)
    last_error: str | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed public API endpoint
                payload = json.loads(response.read().decode("utf-8"))
            papers = payload.get("data") or []
            papers.sort(key=lambda item: item.get("citationCount") or 0, reverse=True)
            return [normalize_paper(paper) for paper in papers[:max_results]]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"Semantic Scholar search failed after retries: {last_error}")


def search_and_record(
    target_repo: Path,
    run_id: str,
    query: str,
    idea_id: str,
    reflection_round: int,
    *,
    max_results: int = 10,
    fixture_path: Path | None = None,
) -> tuple[list[dict[str, Any]], Path]:
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    root = ai_dir(target_repo)
    cache_dir = root / "runs" / run_id / "semantic-scholar-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    cache_path = cache_dir / f"search_{cache_key}.json"
    cached = cache_path.exists()
    if cached:
        payload = load_json(cache_path)
        results = payload.get("results", [])
    else:
        results = fixture_results(fixture_path, query, max_results) if fixture_path else live_results(query, max_results)
        cache_payload = {"query": query, "results": results, "source": "fixture" if fixture_path else "semantic_scholar"}
        write_json(cache_path, cache_payload)
        write_json(root / "logs" / run_id / "semantic-scholar-cache" / cache_path.name, cache_payload)
    append_jsonl(
        root / "runs" / run_id / "api-ledger.jsonl",
        {
            "timestamp": utc_now(),
            "phase": "ideation",
            "provider": "semantic_scholar",
            "budget_key": "semantic_scholar",
            "cached": cached,
            "idea_id": idea_id,
            "reflection_round": reflection_round,
            "query": query,
            "result_count": len(results),
            "cache_file": str(cache_path.relative_to(root / "runs" / run_id)),
            "api_key_present": bool(os.environ.get("S2_API_KEY", "").strip()),
        },
    )
    return results, cache_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-repo", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--idea-id", required=True)
    parser.add_argument("--reflection-round", type=int, required=True)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    results, cache_path = search_and_record(
        args.target_repo,
        args.run_id,
        args.query,
        args.idea_id,
        args.reflection_round,
        max_results=args.max_results,
        fixture_path=args.fixture,
    )
    print(json.dumps({"cache_path": str(cache_path), "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
