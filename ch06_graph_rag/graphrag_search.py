# Chapter 6: Context Graphs and GraphRAG for Enterprise Data
# Section: 6.3 GraphRAG local and global search
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
GraphRAG search integration for OpsPulse.

Microsoft GraphRAG (open-source, July 2024):
  - Extracts a knowledge graph from unstructured documentation
  - Local search: entity-specific questions (use the entity neighborhood)
  - Global search: portfolio questions (use community summaries)

Entity types for data engineering:
  table, column, metric, team, process, policy, failure_mode

Version note: targets graphrag 3.x. Search goes through the public graphrag.api
(local_search / global_search); models, retrieval tuning, and the vector store are
configured in settings.yaml, and the index is written as flat output/*.parquet files.
Models are called through LiteLLM, so model_provider: anthropic works without a proxy.
"""

import os
import pandas as pd
from pathlib import Path
from typing import Optional
import anthropic
import json

client = anthropic.Anthropic()


# ============================================================
# GraphRAG indexing configuration
# ============================================================

GRAPHRAG_CONFIG = """
# GraphRAG 3.x: values to change in the settings.yaml written by
#   graphrag init --root opspu_graphrag --model gpt-6.1-terra --embedding text-embedding-3-small
# Keep the generated keys (auth_method, retry, storage). Unknown keys are ignored
# silently, so check spelling: load_config(...) and print the section you edited.

chunking:
  size: 300
  overlap: 50

extract_graph:
  entity_types: [table, column, metric, data_product, team, process, policy, failure_mode]
  max_gleanings: 1

local_search:
  text_unit_prop: 0.5
  community_prop: 0.1
  top_k_entities: 10
  top_k_relationships: 10
  max_context_tokens: 12000
"""


# ============================================================
# GraphRAG query wrappers (graphrag 3.x public API)
# ============================================================

INDEX_TABLES = ["entities", "relationships", "communities", "community_reports", "text_units"]
COMMUNITY_LEVEL = 2


def load_graphrag_index(graphrag_root: str) -> dict:
    """Load the flat parquet tables written by `graphrag index` (output/*.parquet)."""
    out_dir = Path(graphrag_root) / "output"
    missing = [t for t in INDEX_TABLES if not (out_dir / f"{t}.parquet").exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing {missing} under {out_dir}. Run 'graphrag index --root {graphrag_root}' first."
        )
    tables = {t: pd.read_parquet(out_dir / f"{t}.parquet") for t in INDEX_TABLES}
    cov = out_dir / "covariates.parquet"   # present only when extract_claims is enabled
    tables["covariates"] = pd.read_parquet(cov) if cov.exists() else None
    return tables


async def run_graphrag_local_search(
    query: str,
    graphrag_root: str = "./opspu_graphrag",
) -> str:
    """
    Local search: best for entity-specific questions
    ("What columns does fct_device_anomalies expose?")
    """
    import graphrag.api as api
    from graphrag.config.load_config import load_config

    config = load_config(Path(graphrag_root))
    t = load_graphrag_index(graphrag_root)
    response, _context = await api.local_search(
        config=config,
        entities=t["entities"],
        communities=t["communities"],
        community_reports=t["community_reports"],
        text_units=t["text_units"],
        relationships=t["relationships"],
        covariates=t["covariates"],
        community_level=COMMUNITY_LEVEL,
        response_type="single paragraph",
        query=query,
    )
    return str(response)


async def run_graphrag_global_search(
    query: str,
    graphrag_root: str = "./opspu_graphrag",
    dynamic_selection: bool = True,
) -> str:
    """
    Global search: best for portfolio-level questions
    ("What are the main failure modes in the OpsPulse data platform?")
    """
    import graphrag.api as api
    from graphrag.config.load_config import load_config

    config = load_config(Path(graphrag_root))
    t = load_graphrag_index(graphrag_root)
    response, _context = await api.global_search(
        config=config,
        entities=t["entities"],
        communities=t["communities"],
        community_reports=t["community_reports"],
        community_level=COMMUNITY_LEVEL,
        dynamic_community_selection=dynamic_selection,
        response_type="multiple paragraphs",
        query=query,
    )
    return str(response)


# ============================================================
# Hybrid retrieval: graph traversal + vector fill-in
# ============================================================

def hybrid_graph_vector_retrieve(
    query: str,
    G,             # networkx DiGraph from knowledge_graph_networkx.py
    vector_chunks: list,
    entity_name: str,
    max_hops: int = 2,
    top_k_vector: int = 5,
) -> dict:
    """
    Stage 1: Graph traversal to get the structural entity neighborhood.
    Stage 2: Vector search within the neighborhood for semantic richness.

    Returns a combined context dict for the LLM.
    """
    import networkx as nx

    # Stage 1: find the entity node and its neighborhood
    entity_node = None
    for node_id in G.nodes:
        if entity_name.lower() in node_id.lower():
            entity_node = node_id
            break

    graph_context = {"entity": entity_name, "neighborhood": []}
    if entity_node:
        try:
            neighbors = nx.ego_graph(G, entity_node, radius=max_hops)
            graph_context["neighborhood"] = [
                {
                    "id":        n,
                    "name":      G.nodes[n].get("name", n),
                    "type":      G.nodes[n].get("node_type", "unknown"),
                    "hops":      nx.shortest_path_length(G, entity_node, n) if n != entity_node else 0,
                }
                for n in neighbors.nodes
            ]
        except Exception:
            pass

    # Stage 2: vector retrieval anchored to the neighborhood
    # STUB: in production, filter vector chunks by entity neighborhood
    neighborhood_names = {n["name"].lower() for n in graph_context["neighborhood"]}
    relevant_chunks = [
        c for c in vector_chunks
        if any(name in c.content.lower() for name in neighborhood_names)
    ][:top_k_vector]

    return {
        "graph_neighborhood": graph_context,
        "vector_chunks":      [{"source": c.source, "content": c.content[:500]}
                               for c in relevant_chunks],
        "query":              query,
    }


# ============================================================
# Grounding eval for GraphRAG answers
# ============================================================

def evaluate_graph_answer_grounding(
    query: str,
    answer: str,
    retrieved_context: str,
) -> dict:
    """
    Check whether every factual claim in the answer is supported by
    the retrieved context. A strict grounding evaluator.
    """
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=512,
        system=(
            "You are a factual grounding evaluator for data engineering AI systems. "
            "Check whether an answer is fully grounded in the provided context. "
            "Be strict: flag any claim not explicitly supported by the context, "
            "even if it sounds plausible. Data engineering systems change; "
            "only claims supported by the retrieved context are safe."
        ),
        messages=[{"role": "user", "content": (
            f"Query: {query}\n\n"
            f"Retrieved context:\n{retrieved_context}\n\n"
            f"Answer to evaluate:\n{answer}\n\n"
            "For each factual claim:\n"
            "1. Quote the claim\n"
            "2. Find supporting evidence in the context (exact quote)\n"
            "3. Mark as GROUNDED, UNVERIFIED (not in context), or CONTRADICTED\n\n"
            "Return JSON: {grounded: [...], unverified: [...], contradicted: [...], "
            "overall_grounding_score: float 0.0-1.0}"
        )}]
    )
    try:
        return json.loads(response.content[0].text)
    except json.JSONDecodeError:
        return {"error": "parse_failed", "raw": response.content[0].text}


if __name__ == "__main__":
    print("GraphRAG 3.x setup:")
    print("1. Install: pip install 'graphrag>=3.2,<4'   (Python 3.11-3.13)")
    print("2. Init:    graphrag init --root opspu_graphrag --model gpt-6.1-terra --embedding text-embedding-3-small")
    print("3. Edit settings.yaml (template below), add docs to opspu_graphrag/input/")
    print("4. Index:   graphrag index --root opspu_graphrag")
    print("5. Query:   asyncio.run(run_graphrag_local_search('What tables feed fct_device_anomalies?'))")
    print()
    print("settings.yaml values to change:")
    print(GRAPHRAG_CONFIG)
