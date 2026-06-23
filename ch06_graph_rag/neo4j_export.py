# Chapter 6: Context Graphs and GraphRAG for Enterprise Data
# Section: 6.2 Neo4j export for production-scale graphs
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Export the OpsPulse lineage graph to Neo4j for production-scale traversal.

Neo4j handles production-scale graphs with millions of edges.
NetworkX is appropriate for development (< 100K nodes) and CI testing.

Node types: Table, Column, Metric, Team, Process, Policy, Dashboard, FailureMode
Relationship types: FEEDS, DEPENDS_ON, HAS_COLUMN, OWNED_BY, GOVERNED_BY, CONSUMES
"""

try:
    from neo4j import GraphDatabase
except ImportError:
    raise ImportError("pip install neo4j>=5.0")

import networkx as nx
import os


def export_graph_to_neo4j(
    G: nx.DiGraph,
    neo4j_uri: str = None,
    neo4j_auth: tuple = None,
    batch_size: int = 500,
) -> dict:
    """
    Export a NetworkX lineage graph to Neo4j.

    Uses MERGE (not CREATE) so the export is idempotent:
    running it multiple times will not create duplicate nodes.

    Args:
        G:           NetworkX DiGraph from knowledge_graph_networkx.py
        neo4j_uri:   Bolt URI (default: NEO4J_URI env var)
        neo4j_auth:  (user, password) tuple (default: NEO4J_AUTH env var)
        batch_size:  Nodes/edges per transaction batch

    Returns:
        dict with nodes_created, relationships_created counts
    """
    uri  = neo4j_uri  or os.environ["NEO4J_URI"]
    auth_str = neo4j_auth or tuple(os.environ["NEO4J_AUTH"].split("/", 1))

    driver = GraphDatabase.driver(uri, auth=auth_str)
    stats = {"nodes_created": 0, "relationships_created": 0}

    # Export nodes in batches
    node_list = list(G.nodes(data=True))
    for i in range(0, len(node_list), batch_size):
        batch = node_list[i:i + batch_size]
        with driver.session() as session:
            session.run(
                """
                UNWIND $nodes AS node
                MERGE (n:DataNode {id: node.id})
                SET n += node.props
                """,
                nodes=[
                    {"id": node_id, "props": {
                        "name":      data.get("name", node_id),
                        "node_type": data.get("node_type", "unknown"),
                        "schema":    data.get("schema", ""),
                        "description": data.get("description", ""),
                    }}
                    for node_id, data in batch
                ]
            )
        stats["nodes_created"] += len(batch)

    # Export edges in batches
    edge_list = list(G.edges(data=True))
    for i in range(0, len(edge_list), batch_size):
        batch = edge_list[i:i + batch_size]
        with driver.session() as session:
            session.run(
                """
                UNWIND $rels AS rel
                MATCH (a:DataNode {id: rel.source})
                MATCH (b:DataNode {id: rel.target})
                MERGE (a)-[r:FEEDS {edge_type: rel.edge_type}]->(b)
                """,
                rels=[
                    {
                        "source":    src,
                        "target":    tgt,
                        "edge_type": data.get("edge_type", "unknown"),
                    }
                    for src, tgt, data in batch
                ]
            )
        stats["relationships_created"] += len(batch)

    driver.close()
    return stats


def query_neo4j_impact(
    table_name: str,
    max_depth: int = 5,
    neo4j_uri: str = None,
    neo4j_auth: tuple = None,
) -> list[dict]:
    """
    Query Neo4j for all tables downstream of a source table.
    More efficient than NetworkX BFS for large graphs (uses index-backed traversal).
    """
    uri      = neo4j_uri  or os.environ["NEO4J_URI"]
    auth_str = neo4j_auth or tuple(os.environ["NEO4J_AUTH"].split("/", 1))

    driver = GraphDatabase.driver(uri, auth=auth_str)
    with driver.session() as session:
        result = session.run(
            """
            MATCH (source:DataNode)
            WHERE toLower(source.name) CONTAINS toLower($table_name)
              AND source.node_type = 'table'
            MATCH path = (source)-[:FEEDS*1..$max_depth]->(downstream)
            WHERE downstream.node_type IN ['table', 'dashboard']
            RETURN
                downstream.name     AS name,
                downstream.node_type AS node_type,
                length(path)        AS hops
            ORDER BY hops, name
            """,
            table_name=table_name,
            max_depth=max_depth,
        )
        rows = [dict(r) for r in result]
    driver.close()
    return rows


def create_neo4j_indexes(
    neo4j_uri: str = None,
    neo4j_auth: tuple = None,
) -> None:
    """Create indexes for efficient OpsPulse graph queries."""
    uri      = neo4j_uri  or os.environ["NEO4J_URI"]
    auth_str = neo4j_auth or tuple(os.environ["NEO4J_AUTH"].split("/", 1))

    driver = GraphDatabase.driver(uri, auth=auth_str)
    with driver.session() as session:
        # Index on node id (primary lookup)
        session.run("CREATE INDEX node_id IF NOT EXISTS FOR (n:DataNode) ON (n.id)")
        # Index on name for natural language queries
        session.run("CREATE INDEX node_name IF NOT EXISTS FOR (n:DataNode) ON (n.name)")
        # Index on node_type for filtering by table/column/dashboard
        session.run("CREATE INDEX node_type IF NOT EXISTS FOR (n:DataNode) ON (n.node_type)")
    driver.close()


if __name__ == "__main__":
    # Demo: build a small graph and export to Neo4j
    # Requires a running Neo4j instance and NEO4J_URI / NEO4J_AUTH env vars
    G = nx.DiGraph()
    G.add_node("dbt://opspu/stg_iot_events",       node_type="table", name="stg_iot_events")
    G.add_node("dbt://opspu/fct_device_anomalies",  node_type="table", name="fct_device_anomalies")
    G.add_node("ops_anomaly_dashboard",             node_type="dashboard", name="ops_anomaly_dashboard")
    G.add_edge("dbt://opspu/stg_iot_events", "dbt://opspu/fct_device_anomalies",
               edge_type="dbt_dependency")
    G.add_edge("dbt://opspu/fct_device_anomalies", "ops_anomaly_dashboard",
               edge_type="consumes")

    print("Exporting to Neo4j...")
    stats = export_graph_to_neo4j(G)
    print(f"Done: {stats}")
