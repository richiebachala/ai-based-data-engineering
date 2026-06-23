# Chapter 2: The Modern Stack — Data + AI + Control Plane
# Section: 2.4 The control plane: evals, observability, governance
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
MCP server introduction — minimal FastMCP catalog server.

This file introduces the MCP pattern used throughout the book.
Chapter 7 builds the full three-server stack (catalog, analytics, operations).

The ACI principle: every sentence in a tool's name, description, and parameter
descriptions is a behavioral instruction to the model. Ambiguous documentation
produces ambiguous model behavior.
"""

from mcp.server.fastmcp import FastMCP
import snowflake.connector
import os

# Create the MCP server
mcp = FastMCP(
    name="opspu-catalog",
    instructions=(
        "You are connected to the OpsPulse data catalog. "
        "Use get_table_schema before generating any SQL or proposing any schema change. "
        "The catalog is the authoritative source of column definitions — "
        "do not infer column names or types from memory."
    ),
)


def _get_connection():
    """Return a Snowflake connection using environment credentials."""
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "DEV_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "OPSPU"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA", "MARTS"),
        role=os.environ.get("SNOWFLAKE_ROLE", "DATA_ENGINEER"),
    )


@mcp.resource("schema://{table_fqn}")
def get_table_schema(table_fqn: str) -> str:
    """
    Return the full column schema for a table.

    Returns column names, data types, nullability, and descriptions
    for every column in the specified table. Always call this resource
    before generating SQL queries or proposing schema changes.

    Args:
        table_fqn: Fully-qualified table name in DB.SCHEMA.TABLE format
                   (e.g., 'OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS')
    """
    db, schema, table = table_fqn.upper().split(".")
    conn = _get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                comment AS description
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name   = %s
            ORDER BY ordinal_position
        """, (schema, table))
        rows = cur.fetchall()

    if not rows:
        return f"No columns found for {table_fqn}. Check the table name and your role."

    lines = [f"Schema for {table_fqn}:", ""]
    for col_name, data_type, nullable, description in rows:
        null_str = "nullable" if nullable == "YES" else "not null"
        desc_str = f" — {description}" if description else " [no description]"
        lines.append(f"  {col_name} ({data_type}, {null_str}){desc_str}")
    return "\n".join(lines)


@mcp.tool()
def get_column_lineage(
    table_fqn: str,
    column_name: str,
) -> dict:
    """
    Return upstream and downstream lineage for a specific column.

    Queries Snowflake ACCESS_HISTORY to find which queries read from
    or write to this column in the past 30 days. Use this before
    proposing any schema change to identify downstream consumers.

    Args:
        table_fqn:   Fully-qualified table name (DB.SCHEMA.TABLE)
        column_name: Column name (case-insensitive)
    """
    conn = _get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT
                q.query_text,
                q.query_start_time,
                q.user_name
            FROM snowflake.account_usage.access_history ah
            JOIN snowflake.account_usage.query_history q
              ON ah.query_id = q.query_id
            WHERE ARRAY_CONTAINS(
                OBJECT_CONSTRUCT('objectName', %s, 'columnName', %s)::VARIANT,
                ah.columns_modified
            )
            AND q.query_start_time > DATEADD('day', -30, CURRENT_TIMESTAMP())
            ORDER BY q.query_start_time DESC
            LIMIT 20
        """, (table_fqn, column_name.upper()))
        rows = cur.fetchall()

    return {
        "table_fqn": table_fqn,
        "column_name": column_name,
        "recent_queries": [
            {
                "query": row[0][:200] if row[0] else "",
                "timestamp": str(row[1]),
                "user": row[2],
            }
            for row in rows
        ],
        "lineage_count": len(rows),
    }


if __name__ == "__main__":
    mcp.run()
