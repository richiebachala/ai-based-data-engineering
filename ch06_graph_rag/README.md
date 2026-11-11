# Chapter 6: Context Graphs and GraphRAG for Enterprise Data
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `knowledge_graph_networkx.py` | Build lineage graph from dbt manifest + Snowflake ACCESS_HISTORY. Impact analysis, hallucination detection. |
| `neo4j_export.py` | Export NetworkX graph to Neo4j for production-scale traversal. Idempotent MERGE pattern. |
| `cypher_impact_query.cypher` | Cypher queries: blast radius, column-level lineage, team ownership, setup script |
| `graphrag_search.py` | GraphRAG 3.x local/global search via `graphrag.api`. Hybrid graph+vector retrieval. Grounding eval. |

## Key concepts

- **When graph > vector**: impact analysis (multi-hop), cross-entity joins, portfolio aggregations
- **Two graph backends**: NetworkX for development (<100K nodes); Neo4j for production (millions of edges)
- **GraphRAG**: Microsoft open-source (July 2024). Local search = entity-specific; global = community summaries
- **Hybrid retrieval**: Stage 1 graph traversal (structural); Stage 2 vector fill-in (semantic richness)
- **Relationship hallucination**: verify structural claims against the ground-truth graph

## Version

Targets `graphrag>=3.2,<4` (Python 3.11-3.13). Earlier revisions of this repo pinned 0.3.x and
built the search context by hand (`create_final_*.parquet`, `LanceDBVectorStore`, `ChatOpenAI`).
GraphRAG 3.x replaces all of that with `graphrag.api.local_search` / `global_search` plus
`settings.yaml`, and writes flat `output/*.parquet`. Note that GraphRAG ignores unknown
settings keys silently; a renamed key from an old guide simply has no effect.

## Setup

```bash
# NetworkX graph (no extra setup)
python knowledge_graph_networkx.py

# Neo4j (requires running Neo4j instance)
# Set NEO4J_URI=bolt://localhost:7687 and NEO4J_AUTH=neo4j/password
python neo4j_export.py

# GraphRAG indexing
pip install -r ../requirements-graphrag.txt   # separate venv; see top-level README
graphrag init --root ./opspu_graphrag --model gpt-6.1-terra --embedding text-embedding-3-small
# Add dbt descriptions, runbooks, incident post-mortems to opspu_graphrag/input/
graphrag index --root ./opspu_graphrag
```
