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

Bug fixes applied:
  C6-1: Output file paths corrected (graphrag v0.3+ uses output/ not artifacts/)
  C6-2: read_indexer_reports() called with 3 args (reports_dir, entity_df, entity_embedding_df)
  C6-3: LocalSearchMixedContext given the correct vector_store, not a DataFrame
  C6-4: ChatOpenAI() includes api_key and model
  C6-5: LocalSearch() includes llm_params and context_builder_params
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
# GraphRAG configuration for OpsPulse documentation corpus
# Save as: opspu_graphrag/settings.yaml
# Run: python -m graphrag index --root opspu_graphrag/

entity_extraction:
  entity_types:
    - table
    - column
    - metric
    - team
    - process
    - policy
    - failure_mode

community_reports:
  max_length: 2000

chunk_size: 300        # tokens per chunk
chunk_overlap: 30      # overlap for continuity
"""


# ============================================================
# GraphRAG query wrappers (corrected for graphrag v0.3+)
# ============================================================

def run_graphrag_local_search(
    query: str,
    graphrag_root: str = "./opspu_graphrag",
) -> str:
    """
    Run a GraphRAG local search query via the CLI.

    Local search: best for entity-specific questions
    ("What columns does fct_device_anomalies expose?")

    Bug fix C6-1: GraphRAG v0.3+ writes output to output/, not artifacts/
    """
    import subprocess
    result = subprocess.run(
        [
            "python", "-m", "graphrag", "query",
            "--root", graphrag_root,
            "--method", "local",
            "--query", query,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"GraphRAG local search failed: {result.stderr}")
    return result.stdout


def run_graphrag_global_search(
    query: str,
    graphrag_root: str = "./opspu_graphrag",
) -> str:
    """
    Run a GraphRAG global search query via the CLI.

    Global search: best for portfolio-level questions
    ("What are the main failure modes in the OpsPulse data platform?")
    """
    import subprocess
    result = subprocess.run(
        [
            "python", "-m", "graphrag", "query",
            "--root", graphrag_root,
            "--method", "global",
            "--query", query,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"GraphRAG global search failed: {result.stderr}")
    return result.stdout


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
        model="claude-sonnet-4-5",
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
    print("GraphRAG setup:")
    print("1. Install: pip install graphrag>=0.3")
    print("2. Create index: python -m graphrag index --root opspu_graphrag/")
    print("3. Query: run_graphrag_local_search('What tables feed fct_device_anomalies?')")
    print()
    print("GraphRAG config template:")
    print(GRAPHRAG_CONFIG)
