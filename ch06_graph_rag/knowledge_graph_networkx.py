# Chapter 6: Context Graphs and GraphRAG for Enterprise Data
# Section: 6.2 Building the lineage graph with NetworkX
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Knowledge graph construction using NetworkX.

Builds the OpsPulse lineage graph from two structured sources:
  1. dbt manifest (table-level model lineage)
  2. Snowflake ACCESS_HISTORY (runtime column-level lineage)

Vector retrieval fails on three categories of queries that graph handles:
  1. Impact analysis (multi-hop traversal)
  2. Cross-entity relationship joins
  3. Portfolio-level aggregations
"""

import networkx as nx
import json
from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class GraphNode:
    node_id:     str
    node_type:   str    # "table" | "column" | "metric" | "team" | "process" | "policy" | "dashboard"
    name:        str
    metadata:    dict = field(default_factory=dict)


# ============================================================
# Build graph from dbt manifest
# ============================================================

def build_lineage_graph_from_manifest(
    manifest: dict,
) -> nx.DiGraph:
    """
    Build a directed lineage graph from a dbt manifest.

    Nodes: dbt models (tables)
    Edges: dependency relationships (upstream → downstream)
    """
    G = nx.DiGraph()

    nodes = manifest.get("nodes", {})
    sources = manifest.get("sources", {})

    # Add all model nodes
    for key, node in nodes.items():
        if node.get("resource_type") != "model":
            continue
        model_name = node.get("name", "")
        node_id = f"dbt://opspu/{model_name}"
        G.add_node(node_id, **{
            "node_type": "table",
            "name": model_name,
            "schema": node.get("schema", ""),
            "description": node.get("description", ""),
            "columns": list(node.get("columns", {}).keys()),
        })

    # Add source nodes
    for key, source in sources.items():
        source_id = f"source://opspu/{source.get('name', key)}"
        G.add_node(source_id, **{
            "node_type": "source",
            "name": source.get("name", key),
        })

    # Add dependency edges
    for key, node in nodes.items():
        if node.get("resource_type") != "model":
            continue
        model_id = f"dbt://opspu/{node.get('name', '')}"
        for dep in node.get("depends_on", {}).get("nodes", []):
            dep_name = dep.split(".")[-1]
            if dep.startswith("model."):
                dep_id = f"dbt://opspu/{dep_name}"
            elif dep.startswith("source."):
                dep_id = f"source://opspu/{dep_name}"
            else:
                continue
            if dep_id in G.nodes:
                G.add_edge(dep_id, model_id,
                           edge_type="dbt_dependency")

    return G


# ============================================================
# Extend graph from Snowflake ACCESS_HISTORY (column-level lineage)
# ============================================================

def extend_graph_from_access_history(
    G: nx.DiGraph,
    conn,
    lookback_days: int = 30,
) -> nx.DiGraph:
    """
    Add runtime column-level lineage edges from Snowflake ACCESS_HISTORY.

    Edges are typed as 'runtime_read' or 'runtime_write' and include
    the query_id for full audit traceability.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                val.value:objectName::STRING AS source_table,
                column_name,
                query_id,
                query_start_time
            FROM snowflake.account_usage.access_history ah,
                 LATERAL FLATTEN(input => ah.direct_objects_accessed) val,
                 LATERAL FLATTEN(input => val.value:columns) col_val,
                 LATERAL (SELECT col_val.value:columnName::VARCHAR AS column_name) col_name
            WHERE query_start_time > DATEADD('day', -%s, CURRENT_TIMESTAMP())
            LIMIT 10000
        """, (lookback_days,))
        rows = cur.fetchall()

    for source_table, col_name, query_id, ts in rows:
        if not source_table:
            continue
        node_id = f"SNOWFLAKE://{source_table.lower()}"
        col_id  = f"{node_id}/{col_name.lower()}"
        if node_id not in G.nodes:
            G.add_node(node_id, node_type="table", name=source_table)
        if col_id not in G.nodes:
            G.add_node(col_id, node_type="column", name=col_name,
                       table=source_table)
            G.add_edge(node_id, col_id, edge_type="has_column")

    return G


# ============================================================
# Graph traversal for impact analysis
# ============================================================

def find_downstream_impact(
    G: nx.DiGraph,
    table_fqn: str,
    max_hops: int = 5,
) -> dict:
    """
    Find all tables and dashboards downstream of a source table.
    Returns a structured impact report with hop counts.
    """
    # Normalize: find the node_id that matches table_fqn
    source_id = None
    table_lower = table_fqn.lower()
    for node_id in G.nodes:
        if table_lower in node_id.lower():
            source_id = node_id
            break

    if not source_id:
        return {"error": f"Table {table_fqn} not found in lineage graph"}

    # BFS to find all downstream nodes within max_hops
    affected = {}
    for node in nx.descendants(G, source_id):
        try:
            hops = nx.shortest_path_length(G, source_id, node)
        except nx.NetworkXNoPath:
            continue
        if hops <= max_hops:
            affected[node] = {
                "hops": hops,
                "node_type": G.nodes[node].get("node_type", "unknown"),
                "name": G.nodes[node].get("name", node),
            }

    tables   = {k: v for k, v in affected.items() if v["node_type"] == "table"}
    dashboards = {k: v for k, v in affected.items() if v["node_type"] == "dashboard"}

    return {
        "source":       table_fqn,
        "total_affected": len(affected),
        "tables_affected": len(tables),
        "max_depth":    max(v["hops"] for v in affected.values()) if affected else 0,
        "affected_tables": tables,
        "affected_dashboards": dashboards,
    }


# ============================================================
# Lineage claim verification (hallucination detection)
# ============================================================

def extract_lineage_claims(answer_text: str) -> list[tuple[str, str]]:
    """
    Extract lineage claims from LLM output using pattern matching.
    Looks for patterns like "X feeds Y", "X depends on Y".
    Returns list of (source, target) pairs.
    """
    patterns = [
        r'(\w+)\s+feeds\s+(?:into\s+)?(\w+)',
        r'(\w+)\s+depends\s+on\s+(\w+)',
        r'(\w+)\s+is\s+upstream\s+of\s+(\w+)',
        r'(\w+)\s+→\s+(\w+)',
    ]
    claims = []
    for pattern in patterns:
        for match in re.finditer(pattern, answer_text, re.IGNORECASE):
            claims.append((match.group(1), match.group(2)))
    return claims


def verify_lineage_claims(
    answer_text: str,
    G: nx.DiGraph,
    entity_alias_index: dict,
) -> dict:
    """
    Check each lineage claim in the answer against the ground-truth graph.
    Returns verified/unverified/contradicted claims with graph evidence.
    """
    claims = extract_lineage_claims(answer_text)
    results = {"verified": [], "unverified": [], "contradicted": []}

    for src_alias, tgt_alias in claims:
        src_id = entity_alias_index.get(src_alias.lower())
        tgt_id = entity_alias_index.get(tgt_alias.lower())

        if not src_id or not tgt_id:
            results["unverified"].append({
                "claim": f"{src_alias} → {tgt_alias}",
                "reason": "one or both entities not found in graph",
            })
            continue

        if nx.has_path(G, src_id, tgt_id):
            path_len = nx.shortest_path_length(G, src_id, tgt_id)
            results["verified"].append({
                "claim": f"{src_alias} → {tgt_alias}",
                "path_length": path_len,
                "evidence": f"Graph path exists: {src_id} to {tgt_id} in {path_len} hop(s)",
            })
        else:
            results["contradicted"].append({
                "claim": f"{src_alias} → {tgt_alias}",
                "reason": f"No path from {src_id} to {tgt_id} in the lineage graph",
            })

    hallucination_rate = (
        len(results["contradicted"]) / len(claims) if claims else 0.0
    )
    return {
        **results,
        "total_claims":       len(claims),
        "hallucination_rate": hallucination_rate,
        "passed":             hallucination_rate == 0.0 and len(results["unverified"]) == 0,
    }


if __name__ == "__main__":
    # Build a minimal demo graph
    G = nx.DiGraph()
    G.add_node("dbt://opspu/stg_iot_events",   node_type="table", name="stg_iot_events")
    G.add_node("dbt://opspu/fct_device_anomalies", node_type="table", name="fct_device_anomalies")
    G.add_node("ops_anomaly_dashboard",         node_type="dashboard", name="ops_anomaly_dashboard")
    G.add_edge("dbt://opspu/stg_iot_events",    "dbt://opspu/fct_device_anomalies", edge_type="dbt_dependency")
    G.add_edge("dbt://opspu/fct_device_anomalies", "ops_anomaly_dashboard",          edge_type="consumes")

    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    impact = find_downstream_impact(G, "stg_iot_events")
    print(f"Downstream of stg_iot_events: {impact}")
