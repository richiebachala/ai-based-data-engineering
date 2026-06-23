# Chapter 6: Context Graphs and GraphRAG for Enterprise Data
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `knowledge_graph_networkx.py` | Build lineage graph from dbt manifest + Snowflake ACCESS_HISTORY. Impact analysis, hallucination detection. |
| `neo4j_export.py` | Export NetworkX graph to Neo4j for production-scale traversal. Idempotent MERGE pattern. |
| `cypher_impact_query.cypher` | Cypher queries: blast radius, column-level lineage, team ownership, setup script |
| `graphrag_search.py` | GraphRAG local/global search wrappers. Hybrid graph+vector retrieval. Grounding eval. |

## Key concepts

- **When graph > vector**: impact analysis (multi-hop), cross-entity joins, portfolio aggregations
- **Two graph backends**: NetworkX for development (<100K nodes); Neo4j for production (millions of edges)
- **GraphRAG**: Microsoft open-source (July 2024). Local search = entity-specific; global = community summaries
- **Hybrid retrieval**: Stage 1 graph traversal (structural); Stage 2 vector fill-in (semantic richness)
- **Relationship hallucination**: verify structural claims against the ground-truth graph

## Bug fixes applied

- **C6-1**: GraphRAG output paths corrected (`output/` not `artifacts/` in v0.3+)
- **C6-2**: `read_indexer_reports()` called with 3 args: `(reports_dir, entity_df, entity_embedding_df)`
- **C6-3**: `LocalSearchMixedContext` given the correct vector_store (not a DataFrame)
- **C6-4**: `ChatOpenAI()` includes `api_key` and `model` parameters
- **C6-5**: `LocalSearch()` includes `llm_params` and `context_builder_params`

## Setup

```bash
# NetworkX graph (no extra setup)
python knowledge_graph_networkx.py

# Neo4j (requires running Neo4j instance)
# Set NEO4J_URI=bolt://localhost:7687 and NEO4J_AUTH=neo4j/password
python neo4j_export.py

# GraphRAG indexing
pip install graphrag>=0.3
python -m graphrag init --root ./opspu_graphrag
# Add dbt descriptions, runbooks, incident post-mortems to opspu_graphrag/input/
python -m graphrag index --root ./opspu_graphrag
```
