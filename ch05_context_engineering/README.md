# Chapter 5: Context Engineering — Retrieval, Shaping, Provenance
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `context_sources.py` | Six context source categories: fetch schema, dbt artifacts, sample rows. Bug fix C5-2 (manifest column tests) and C5-3 (guarded fetchone). |
| `hybrid_retrieval.py` | BM25 + semantic + RRF hybrid retrieval. Contextual Retrieval prefix enrichment. Bug fix C5-1 (Cortex Search OBJECT_CONSTRUCT filter). |
| `context_shaping.py` | Token-budget assembly: deduplicate, prioritize by authority tier, fill greedily, track dropped sources. |
| `prompt_caching.py` | Anthropic ephemeral cache for stable schema preamble. 85% cost savings on high-frequency pipelines. |
| `provenance.py` | Source citations in structured outputs + JSONL audit log. Foundation for Chapter 11 observability. |

## Key concepts

- **Six source categories**: schema, dbt model, sample data, runbook, incident history, policy docs
- **Contextual Retrieval**: prepend a document-level context summary to each chunk before embedding (49% improvement in top-20 recall; 67% with BM25+RRF)
- **RRF (Reciprocal Rank Fusion)**: combine BM25 and semantic rankings with k=60 (Cormack et al., SIGIR 2009)
- **Token budget**: fill greedily by priority (schema > dbt > runbook > incident > policy > sample)
- **Prompt caching**: stable prefix cached at 10% cost after first write; profitable from call #2 onward
- **Provenance**: every chunk carries `retrieved_at` metadata; citations appear in structured outputs

## Bug fixes applied

- **C5-1**: Cortex Search filter uses `OBJECT_CONSTRUCT` (not `ARRAY_CONSTRUCT`)
- **C5-2**: dbt manifest column tests accessed via `manifest.nodes` where `resource_type='test'`
- **C5-3**: `fetch_table_context` guards `fetchone()` — raises `ValueError` with clear message if table not found

## Cache cost model

```
claude-sonnet-4-5 (approximate 2025 pricing):
  Standard input:  $3.00/M tokens
  Cache write:     $3.75/M tokens (1.25× — paid once per TTL)
  Cache read:      $0.30/M tokens (0.10× — 90% savings)

For 100 SQL calls/day with 4,000-token schema preamble:
  Without cache: $1.26/day
  With cache:    $0.195/day (85% reduction)
```
