---
name: local-literature-search
description: Search a target repo's local `papers/` corpus for AI Scientist ideation or research-loop revision brainstorming. Use alongside `skills/literature-search/SKILL.md` when brainstorming needs literature grounding from local paper index JSONL, detail JSON, metadata, or original PDFs, especially for bottleneck diagnosis, branch candidates, priors, baselines, reusable components, source-code hooks, or related biomedical methods.
---

# Local Literature Search

<Purpose>
Use this skill to search the target repo's local `papers/` directory before or during brainstorming. It complements `skills/literature-search/SKILL.md`: external search finds broader/current evidence, while local search mines the curated project corpus for task-specific priors, methods, datasets, reusable components, limitations, and source-code links.
</Purpose>

<Corpus_Contract>
Assume the target repo may contain:

- `papers/README.md`: corpus layout and retrieval policy.
- `papers/tag_vocab.json`: controlled enum vocabulary. Read this first.
- `papers/index.jsonl`: compact retrieval index. Scan this before opening details.
- `papers/details/<paper-id>.json`: detailed summaries, methods, limitations, reusable components, source-code/data availability, and `pdf_local_path`.
- `papers/metadata.full.json`: full canonical metadata. Query selectively by paper id; do not load the full file into context unless auditing metadata.
- `papers/pdfs/`: original PDFs when downloaded. Some `pdf_local_path` entries may point to missing files; report that instead of pretending the PDF was inspected.
</Corpus_Contract>

<Workflow>
Run local literature search whenever revision brainstorming runs literature search, unless the target repo has no `papers/` directory.

1. Confirm corpus presence: check `<target-repo>/papers/README.md`, `tag_vocab.json`, and `index.jsonl`.
2. Read `tag_vocab.json` to learn valid enum tags. Treat tags as enums; do not invent new tag values when filtering.
3. Search `index.jsonl` first. Filter by overlap with the bottleneck and contract: `task_tags`, `dataset_tags`, `label_tags`, `method_tags`, `entity_tags`, `disease_tags`, `input_tags`, `output_tags`, and `metric_tags`.
4. Open only the most relevant `papers/details/*.json` files. Prefer detail fields that explain mechanisms: `problem_statement`, `core_claim`, `methods`, `limitations`, `failure_modes`, `extension_hooks`, `reusable_components`, and `code_or_data_availability`.
5. Query `metadata.full.json` only for missing metadata such as authors, venue, DOI, field, datasets, source URL, or PDF status. Use a small Python filter by paper id.
6. Inspect original PDFs only when detail JSON is insufficient for a mechanism, ablation, metric definition, benchmark protocol, or implementation detail. Use `pdf_local_path` from the detail JSON and verify the file exists before reading.
7. Write local evidence into the brainstorm report with paper ids, detail paths, metadata/PDF refs, and the specific mechanism or bottleneck lesson each paper contributes.
</Workflow>

<Search_Patterns>
Use fast text search for first-pass retrieval:

```bash
rg -n '"drug_response_prediction"|"GDSC"|"IC50"|"cell_line"|"pathway"|"knowledge_graph"' papers/index.jsonl
rg -n '"reusable_components"|"extension_hooks"|"failure_modes"|"code_or_data_availability"' papers/details
```

Use structured Python when tag overlap matters:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

root = Path("papers")
wanted_tags = {
    "drug_response_prediction",
    "GDSC",
    "IC50",
    "knowledge_graph",
    "multi_omics_integration",
    "pathway_enrichment_analysis",
}
wanted_terms = ["bottleneck", "sparse", "cold", "prior", "pathway", "target"]

rows = []
for line in (root / "index.jsonl").read_text().splitlines():
    item = json.loads(line)
    tag_values = []
    for key, value in item.items():
        if key.endswith("_tags") and isinstance(value, list):
            tag_values.extend(str(x) for x in value)
    text = json.dumps(item, ensure_ascii=False).lower()
    score = len(wanted_tags.intersection(tag_values))
    score += sum(1 for term in wanted_terms if term.lower() in text)
    if score:
        rows.append((score, item["id"], item.get("year"), item.get("title"), item.get("detail_path")))

for score, paper_id, year, title, detail_path in sorted(rows, reverse=True)[:20]:
    print(score, paper_id, year, title, detail_path, sep="\t")
PY
```

After selecting ids, open details directly:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

repo = Path(".")
for paper_id in ["2025-mixingdta-improved-drug-target-affinity-prediction-by-extending-mixup-with-guilt-by-associ"]:
    detail = json.loads(next((repo / "papers" / "details").glob(f"{paper_id}.json")).read_text())
    print(json.dumps({
        "id": detail.get("id"),
        "title": detail.get("title"),
        "problem_statement": detail.get("problem_statement"),
        "core_claim": detail.get("core_claim"),
        "limitations": detail.get("limitations"),
        "extension_hooks": detail.get("extension_hooks"),
        "reusable_components": detail.get("reusable_components"),
        "code_or_data_availability": detail.get("code_or_data_availability"),
        "pdf_local_path": detail.get("pdf_local_path"),
        "pdf_source_url": detail.get("pdf_source_url"),
    }, indent=2))
PY
```
</Search_Patterns>

<Metadata_Search>
Use `metadata.full.json` selectively. Do not paste the whole file into context.

```bash
uv run python - <<'PY'
import json
from pathlib import Path

paper_ids = {
    "2025-mixingdta-improved-drug-target-affinity-prediction-by-extending-mixup-with-guilt-by-associ",
}
metadata = json.loads((Path("papers") / "metadata.full.json").read_text())
papers = metadata.get("papers", [])
for paper in papers:
    if paper.get("id") in paper_ids:
        print(json.dumps({
            "id": paper.get("id"),
            "title": paper.get("title"),
            "authors": paper.get("authors"),
            "venue": paper.get("venue"),
            "doi": paper.get("doi"),
            "url": paper.get("url"),
            "field": paper.get("field"),
            "datasets": paper.get("datasets"),
            "pdf_local_path": paper.get("pdf_local_path"),
            "pdf_download_status": paper.get("pdf_download_status"),
            "pdf_source_url": paper.get("pdf_source_url"),
        }, indent=2))
PY
```
</Metadata_Search>

<PDF_Search>
Inspect PDFs only after checking `pdf_local_path`:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

detail = json.loads((Path("papers/details") / "<paper-id>.json").read_text())
pdf_ref = detail.get("pdf_local_path")
if not pdf_ref:
    raise SystemExit("detail has no pdf_local_path")
pdf_path = Path(pdf_ref)
if not pdf_path.exists():
    raise SystemExit(f"PDF not downloaded: {pdf_path}; source={detail.get('pdf_source_url')}")
print(pdf_path)
PY
```

For a downloaded PDF, extract targeted text with PyMuPDF:

```bash
uv run python - <<'PY'
import fitz
from pathlib import Path

pdf_path = Path("papers/pdfs/<paper>.pdf")
terms = ["ablation", "baseline", "split", "implementation", "limitation"]
doc = fitz.open(pdf_path)
for page_index, page in enumerate(doc, start=1):
    text = page.get_text()
    lower = text.lower()
    if any(term in lower for term in terms):
        print(f"--- page {page_index} ---")
        print(text[:2000])
PY
```

Keep PDF excerpts short. Summarize methods and implementation details in your own words, and cite page numbers or sections when available.
</PDF_Search>

<Brainstorming_Use>
Use local papers like a researcher mining a lab corpus:

- Find same-dataset or same-label methods for baselines and split risks.
- Find adjacent-task methods that address the bottleneck through a different representation, prior, objective, sampling strategy, or external information source.
- Extract reusable implementation components and source-code links, but adapt them to the frozen contract.
- Use limitations and future-work fields as branch seeds when they align with current failure evidence.
- Prefer local evidence that explains why a branch could overcome the bottleneck, not only papers with similar keywords.

Do not copy a local paper's entire end-to-end approach as the claimed novelty. Borrow mechanisms, priors, components, or diagnostics with provenance and local validation.
</Brainstorming_Use>

<Output>
In the revision brainstorm report, include a `Local Literature Search` subsection inside `Literature And Source Scan`:

- local query terms and tag filters;
- selected paper ids, titles, detail paths, and metadata/PDF refs;
- relevant mechanism, prior, baseline, implementation hook, limitation, or failure mode from each paper;
- how each local paper motivates or rejects an enhance/branch candidate;
- gaps where local corpus evidence was missing or PDFs were unavailable.
</Output>
