---
name: literature-search
description: Find and use literature/source evidence for ideation or research-loop revision brainstorming without a fixed provider or CLI search command.
---

# Literature Search

<Purpose>
Use this skill when an ideation loop, generator, critic, or research-loop revision worker needs paper evidence, baseline references, novelty checks, benchmark context, source repositories, or related-work raw material. The agent using this skill owns query choice, source choice, evidence relevance, and citation quality. The AI Scientist CLI does not call literature APIs or cache provider responses.
</Purpose>

<Use_When>
- The ideation orchestrator needs an advisory preflight reference scan before generator subagents are spawned.
- A generator needs papers, benchmark references, source repositories, or novelty checks before drafting or revising an idea.
- A critic asks for missing reference, baseline, benchmark, or novelty evidence.
- A performance idea needs comparable papers, models, code, datasets, metrics, or benchmark protocols.
- A research-loop revision brainstorm needs approach families, priors, mechanisms, baselines, diagnostics, or implementation examples for overcoming a bottleneck.
</Use_When>

<Who_Uses_It>
Generator subagents should use this skill directly when they need literature raw material for an idea. Research-loop revision workers should use it before finalizing enhance/branch candidates when external evidence could sharpen the plan. The main ideation orchestrator may use it during preflight or as a prompt-level backstop when a draft has weak evidence.
</Who_Uses_It>

<Source_Flexibility>
Use the best available search surface for the question. Acceptable sources include scholarly search engines, venue pages, paper PDFs, arXiv pages, benchmark docs, dataset/model cards, GitHub repositories, local `papers/` corpora, existing repo docs, and general web search when it leads to primary sources.

When the target repo has a curated local paper corpus, use `skills/local-literature-search/SKILL.md` alongside external search so local priors and source hooks are not missed.

Do not force one provider. Prefer primary sources over summaries:

- paper PDF, DOI, arXiv/OpenReview/ACM/IEEE/PMLR page, or official proceedings page for paper claims;
- official benchmark, dataset, model, or evaluator docs for protocol claims;
- source repository, release, commit, or package docs for implementation claims;
- local `papers/` metadata/PDFs when the target repo curates a paper corpus.
</Source_Flexibility>

<Generator_Workflow>
When used by a generator subagent:

1. Start from the assigned topic, mode, idea id, frozen contract, and result path.
2. Form 1-3 targeted queries before drafting the final idea.
3. Search with any available reliable tools or local corpus; do not rely on a single provider when the result set is weak.
4. Use evidence to choose or reject baseline references, benchmark plans, novelty claims, and implementation hooks.
5. Put stable evidence refs in the returned draft JSON `evidence_refs` field, and include the reasoning in the draft log/report rather than persisted loop state.
6. Return the final idea JSON to the assigned generator result path.
</Generator_Workflow>

<Revision_Workflow>
When used by a research-loop revision worker:

1. Start from the bottleneck diagnosis, data-insight report, learning notes, critic verdict, and frozen contract.
2. Form 1-3 targeted searches for approach families, priors, architectures, objectives, data strategies, source components, or diagnostics that could overcome the bottleneck.
3. Use papers and source repos as motivation, not as an exact end-to-end recipe to copy as the claimed contribution.
4. It is allowed to download papers, inspect PDFs, clone source code, and borrow implementation components when useful. Record paper/source refs, repository URL or commit when available, visible license/provenance, and any local adaptation.
5. Preserve the frozen contract: do not change split, evaluator, target, acceptance criteria, or benchmark meaning to match a paper.
6. Carry evidence refs into the brainstorm report's literature/source scan and into any candidate materially motivated by the search.
</Revision_Workflow>

<Query_Guide>
Good literature/source search is targeted:

- include dataset/task name, metric, and method family when known;
- include "benchmark", "baseline", "state of the art", or the model family for performance ideas;
- include the failure mode or bottleneck for revision work;
- avoid long natural-language paragraphs;
- run multiple targeted queries rather than one broad query.

Good examples:

- `drug target affinity Davis KIBA baseline graph neural network`
- `ADMET benchmark data leakage scaffold split`
- `molecular property prediction scaffold split baseline graph transformer`
</Query_Guide>

<OpenAlex_API_Guide>
Use OpenAlex directly when broad scholarly discovery is useful and no better curated/local source is available. This is prompt-owned API usage: the AI Scientist CLI does not provide an OpenAlex command, cache, or provenance ledger.

Basics:

- Base URL: `https://api.openalex.org`
- Main endpoint for papers: `GET /works`
- Current OpenAlex API docs describe API keys as query parameters: `api_key=<OPENALEX_API_KEY>`. If no key is available in the environment or credential files, use other available search tools instead of blocking the loop.
- Use `select=` to keep responses small. For ideation, prefer fields like `id,doi,title,publication_year,cited_by_count,primary_location,open_access,authorships,abstract_inverted_index`.
- Use `per_page` between 1 and 100. For normal ideation, request a small page such as 5-25 results.

Good first query shape:

```text
https://api.openalex.org/works?search=<url-encoded-query>&filter=from_publication_date:2020-01-01&sort=cited_by_count:desc&per_page=10&select=id,doi,title,publication_year,cited_by_count,primary_location,authorships,abstract_inverted_index&api_key=<OPENALEX_API_KEY>
```

Use `search=` for broad full-text paper discovery across title, abstract, and full text. Use uppercase `AND`, `OR`, and `NOT` for Boolean queries, and quote exact phrases. Keep long Boolean URLs under roughly 4 KB by splitting large `OR` lists and deduplicating returned work IDs.

Use `filter=` for constraints that should not be relevance-ranked:

- `publication_year:2024`
- `from_publication_date:2020-01-01`
- `is_oa:true`
- `type:article`
- `cited_by_count:>100`

Use cursor paging only when you truly need more than the first page:

```text
https://api.openalex.org/works?search=<query>&per_page=100&cursor=*&api_key=<OPENALEX_API_KEY>
```

Then use `meta.next_cursor` exactly as returned until it is null or enough evidence has been gathered. Do not cursor-page through huge result sets during ideation; use a snapshot or a more targeted query for bulk work.

Evidence extraction:

- Treat `id`, `doi`, `title`, `publication_year`, `cited_by_count`, venue/source URL, and open-access landing URL as stable evidence metadata.
- Reconstruct `abstract_inverted_index` only when the abstract is needed for the claim.
- Do not cite a paper solely from title match. Open the landing page/PDF when the idea depends on a specific method, benchmark, or result.
- Put the OpenAlex URL/ID plus any DOI/PDF/source refs in `evidence_refs`, and summarize the supported claim in the draft or revision report.
</OpenAlex_API_Guide>

<Evidence_Use>
The literature search does not write the idea or revision for the agent. Use returned papers/sources as raw material:

- identify plausible baseline/reference papers;
- check whether the idea is already obvious or saturated;
- extract benchmark protocols and comparable metrics;
- identify mechanism families, priors, code patterns, or diagnostics that could address a diagnosed research-loop bottleneck;
- identify evidence that supports or challenges the run-owned baseline, benchmark plan, and target threshold;
- reject ideas whose only support is a weak title match.

Preflight references found before generator subagents exist are advisory only. Once a generator relies on a reference for novelty, baseline, benchmark, or contract support, the generator should include stable source refs in its draft/report `evidence_refs`.

For revision brainstorming, literature/source evidence is advisory: it can motivate a branch, justify a prior, identify a missing capability, or supply implementation pieces, but it must not replace local evidence, split-safe validation, or a run-owned scientific claim.
</Evidence_Use>

<Boundaries>
Do not invent citations. Do not treat search snippets as sufficient evidence for technical claims. Record provenance in the artifact that uses the evidence: title, authors/year when available, URL/DOI/arXiv/OpenReview/repository URL, accessed file path for local PDFs, and the specific claim supported. If sources disagree or are weak, say so and lower confidence instead of overfitting the idea around a convenient citation.
</Boundaries>
