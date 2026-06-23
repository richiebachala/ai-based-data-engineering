# Chapter 7: Tool and Interface Engineering with MCP
# Section: 7.2 Catalog server (read-only context retrieval)
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
MCP catalog server: read-only resources and tools for schema context.

The ACI principle: every sentence in a tool's name, description, and
parameter descriptions is a behavioral instruction to the model.
Ambiguous documentation produces ambiguous model behavior.

This server is SAFE to give to agents with broad latitude:
  - Resources: read-only, addressed by URI
  - Tools: read-only SQL; no mutations
"""

from mcp.server.fastmcp import FastMCP
import snowflake.connector
import json
import os
from typing import Optional

mcp = FastMCP(
    name="opspu-catalog",
    instructions=(
        "You are connected to the OpsPulse data catalog. "
        "Always call get_table_schema before generating SQL or proposing schema changes. "
        "The catalog is the authoritative source of column definitions. "
        "Use get_column_lineage to check downstream impact before any schema modification."
    ),
)


def _get_connection():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "CATALOG_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "OPSPU"),
        role="CATALOG_READER",  # read-only role
    )


# ============================================================
# Resources: read-only, addressed by URI
# ============================================================

@mcp.resource("schema://{table_fqn}")
def schema_resource(table_fqn: str) -> str:
    """
    Full column schema for a table.

    Returns column names, data types, nullability, and descriptions for every
    column in the specified table. Always retrieve this resource before generating
    SQL — never infer column names or types from training knowledge.

    URI format: schema://DB.SCHEMA.TABLE
    Example:    schema://OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS
    """
    db, schema, table = table_fqn.upper().split(".")
    conn = _get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable, comment
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, table))
        rows = cur.fetchall()

    if not rows:
        return f"No columns found for {table_fqn}. Verify the table name and your role."

    lines = [f"Table: {table_fqn}", f"Columns ({len(rows)}):", ""]
    for col_name, data_type, nullable, comment in rows:
        null_str = "nullable" if nullable == "YES" else "required"
        desc     = f" — {comment}" if comment else " [no description]"
        lines.append(f"  {col_name} ({data_type}, {null_str}){desc}")
    return "\n".join(lines)


@mcp.resource("capabilities://")
def capabilities_resource() -> str:
    """
    Platform capability index — the routing table for the OpsPulse platform.
    Returns: available tables, SQL dialect rules, and active customer definition.
    Retrieve this resource first in every new session.
    """
    try:
        with open("../ch02_modern_data_platform/capability_index.md") as f:
            return f.read()
    except FileNotFoundError:
        return "Capability index not found. See ch02_modern_data_platform/capability_index.md"


# ============================================================
# Tools: callable, read-only
# ============================================================

@mcp.tool()
def get_table_schema(
    table_fqn: str,
) -> dict:
    """
    Return the full column schema for a table as structured JSON.

    Use before generating SQL, proposing tests, or suggesting transformations.
    The returned schema includes column names, types, nullability, and descriptions.

    Args:
        table_fqn: Fully-qualified table name in DB.SCHEMA.TABLE format.
                   Example: 'OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS'
    """
    db, schema, table = table_fqn.upper().split(".")
    conn = _get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable, comment
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, table))
        rows = cur.fetchall()

    if not rows:
        return {
            "error":     "TABLE_NOT_FOUND",
            "retryable": False,
            "message":   f"{table_fqn} not found. Check table name and role.",
        }

    return {
        "table_fqn": table_fqn,
        "columns": [
            {
                "name":        row[0],
                "type":        row[1],
                "nullable":    row[2] == "YES",
                "description": row[3] or "",
            }
            for row in rows
        ],
    }


@mcp.tool()
def get_column_lineage(
    table_fqn: str,
    column_name: str,
    lookback_days: int = 30,
) -> dict:
    """
    Return upstream and downstream lineage for a specific column.

    Queries Snowflake ACCESS_HISTORY for queries that read or write this column
    in the specified window. Use before proposing schema changes to identify
    downstream consumers that would be affected.

    Args:
        table_fqn:      Fully-qualified table name (DB.SCHEMA.TABLE)
        column_name:    Column name (case-insensitive)
        lookback_days:  History window in days (default 30, max 90)
    """
    lookback_days = min(lookback_days, 90)  # safety cap
    conn = _get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT
                q.query_type,
                q.user_name,
                DATE(q.query_start_time) AS query_date
            FROM snowflake.account_usage.access_history ah
            JOIN snowflake.account_usage.query_history q
              ON ah.query_id = q.query_id
            WHERE ARRAY_CONTAINS(
                OBJECT_CONSTRUCT('objectName', %s)::VARIANT,
                ah.direct_objects_accessed
            )
            AND q.query_start_time > DATEADD('day', -%s, CURRENT_TIMESTAMP())
            ORDER BY query_date DESC
            LIMIT 50
        """, (table_fqn, lookback_days))
        rows = cur.fetchall()

    return {
        "table_fqn":    table_fqn,
        "column_name":  column_name,
        "lookback_days": lookback_days,
        "access_events": [
            {"query_type": r[0], "user": r[1], "date": str(r[2])}
            for r in rows
        ],
        "total_accesses": len(rows),
    }


@mcp.tool()
def search_catalog(
    query: str,
    source_type: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """
    Search the catalog for tables or columns matching a query.

    Uses Cortex Search (hybrid BM25 + semantic) for relevance ranking.
    More useful than exact name matching when the user describes what they need.

    Args:
        query:       Natural language description (e.g., 'IoT device anomaly events')
        source_type: Optional filter: 'table' | 'column' | 'metric'
        limit:       Maximum results to return (default 10, max 50)
    """
    limit = min(limit, 50)
    conn  = _get_connection()
    with conn.cursor() as cur:
        if source_type:
            cur.execute("""
                SELECT * FROM TABLE(
                    SNOWFLAKE.CORTEX.SEARCH(
                        'opspu_catalog_index', %s,
                        OBJECT_CONSTRUCT('entity_type', %s),
                        %s
                    )
                )
            """, (query, source_type, limit))
        else:
            cur.execute("""
                SELECT * FROM TABLE(
                    SNOWFLAKE.CORTEX.SEARCH('opspu_catalog_index', %s, NULL, %s)
                )
            """, (query, limit))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in rows]


if __name__ == "__main__":
    mcp.run()
