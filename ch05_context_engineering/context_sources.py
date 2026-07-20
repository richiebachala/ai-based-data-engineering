# Chapter 5: Context Engineering — Retrieval, Shaping, Provenance
# Section: 5.1-5.2 Context sources and hybrid retrieval
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Context sources and chunking strategy for OpsPulse.

Six source categories with different freshness, authority, and chunking:
  1. Schema/catalog metadata  — table-level, from INFORMATION_SCHEMA
  2. dbt model artifacts      — table-level (descriptions, tests)
  3. Sample data              — row-level, from SELECT TOP N
  4. Runbooks                 — heading-level with 1-paragraph overlap
  5. Incident history         — ticket-level
  6. Policy documents         — section-level
"""

import snowflake.connector
import json
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
import os


@dataclass
class ContextChunk:
    source:       str        # e.g. "OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS"
    source_type:  str        # "schema" | "dbt_model" | "runbook" | "incident" | "policy"
    content:      str
    token_estimate: int = 0
    metadata:     dict = field(default_factory=dict)

    def __post_init__(self):
        # Rough estimate: 1 token ≈ 4 characters
        self.token_estimate = max(1, len(self.content) // 4)


@dataclass
class TableContext:
    table_fqn:  str
    columns:    list[dict]   # [{column_name, data_type, is_nullable, comment}]
    row_count:  Optional[int] = None
    last_modified: Optional[str] = None


# ============================================================
# Source 1: Schema / catalog metadata
# ============================================================

def fetch_table_context(
    conn: snowflake.connector.connection.SnowflakeConnection,
    table_fqn: str,
) -> TableContext:
    """
    Fetch full column schema for a table.

    Bug fix (C5-3): guards fetchone() against None — table may not exist
    or the role may not have access. Raises ValueError with a clear message.
    """
    db, schema, table = table_fqn.upper().split(".")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable, comment
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, table))
        rows = cur.fetchall()

    if not rows:
        raise ValueError(
            f"No columns found for {table_fqn}. "
            "Check the table name and that your role has USAGE on the schema."
        )

    return TableContext(
        table_fqn=table_fqn,
        columns=[
            {
                "column_name": row[0],
                "data_type":   row[1],
                "is_nullable": row[2],
                "comment":     row[3] or "",
            }
            for row in rows
        ],
    )


def table_context_to_chunk(table_ctx: TableContext) -> ContextChunk:
    """Convert a TableContext to a ContextChunk for the retrieval pipeline."""
    col_lines = [
        f"  {c['column_name']} ({c['data_type']}, "
        f"{'nullable' if c['is_nullable'] == 'YES' else 'not null'})"
        + (f" — {c['comment']}" if c['comment'] else "")
        for c in table_ctx.columns
    ]
    content = f"Table: {table_ctx.table_fqn}\nColumns:\n" + "\n".join(col_lines)
    return ContextChunk(
        source=table_ctx.table_fqn,
        source_type="schema",
        content=content,
        metadata={"column_count": len(table_ctx.columns)},
    )


# ============================================================
# Source 2: dbt model artifacts
# ============================================================

def fetch_dbt_model_context(
    manifest: dict,
    model_name: str,
) -> Optional[ContextChunk]:
    """
    Fetch dbt model description and column tests from the manifest.

    Bug fix (C5-2): column test access now handles the manifest structure
    correctly. In dbt v1.5+ manifest, column tests are in 'nodes' with
    resource_type='test', not in a 'tests' key on the column dict.
    """
    model_key = f"model.opspu.{model_name}"
    model = manifest.get("nodes", {}).get(model_key)
    if not model:
        return None

    description = model.get("description", "")

    # Correct approach: find tests in manifest.nodes where attached_node matches
    column_tests: dict[str, list[str]] = {}
    for node_key, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") != "test":
            continue
        attached = node.get("attached_node", "")
        if model_key not in attached:
            continue
        col_name = node.get("column_name", "_table")
        test_name = node.get("name", "").split(".")[-1]
        column_tests.setdefault(col_name, []).append(test_name)

    content_parts = [f"dbt model: {model_name}", f"Description: {description}"]
    if column_tests:
        content_parts.append("Column tests:")
        for col, tests in column_tests.items():
            content_parts.append(f"  {col}: {', '.join(tests)}")

    return ContextChunk(
        source=f"dbt://{model_name}",
        source_type="dbt_model",
        content="\n".join(content_parts),
        metadata={"model_name": model_name},
    )


# ============================================================
# Source 3: Sample data
# ============================================================

def fetch_sample_rows(
    conn: snowflake.connector.connection.SnowflakeConnection,
    table_fqn: str,
    limit: int = 3,
    exclude_pii_columns: list[str] | None = None,
) -> ContextChunk:
    """Fetch representative sample rows as context."""
    exclude = set(c.upper() for c in (exclude_pii_columns or []))
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT *
            FROM {table_fqn}
            TABLESAMPLE BERNOULLI(1)
            LIMIT %s
        """, (limit,))
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()

    # Filter PII columns
    if exclude:
        col_idx = [(i, c) for i, c in enumerate(columns) if c not in exclude]
    else:
        col_idx = list(enumerate(columns))

    lines = [", ".join(c for _, c in col_idx)]
    for row in rows:
        lines.append(", ".join(str(row[i]) for i, _ in col_idx))

    return ContextChunk(
        source=table_fqn,
        source_type="sample_data",
        content="\n".join(lines),
        metadata={"row_count": len(rows)},
    )


# ============================================================
# Cortex Search source (Section 5.2)
# ============================================================

def search_incident_history(
    query: str,
    service_name: str = "OPSPU.MARTS.INCIDENT_SEARCH_SERVICE",
    limit: int = 5,
) -> list[ContextChunk]:
    """
    Search incident history using Snowflake Cortex Search.

    Uses the CortexSearchService SDK (snowflake-ml-python >= 1.5).
    The legacy SEARCH_PREVIEW SQL function is deprecated — use the SDK.

    Args:
        query:        Natural-language search query
        service_name: Fully-qualified Cortex Search Service name
        limit:        Maximum number of results to return
    """
    try:
        from snowflake.cortex import CortexSearchService  # snowflake-ml-python >= 1.5
    except ImportError:
        raise ImportError(
            "snowflake-ml-python >= 1.5 is required for CortexSearchService. "
            "Install with: pip install 'snowflake-ml-python>=1.5'"
        )

    import snowflake.snowpark as snowpark
    session = snowpark.Session.builder.configs({
        "account":   os.environ["SNOWFLAKE_ACCOUNT"],
        "user":      os.environ["SNOWFLAKE_USER"],
        "password":  os.environ["SNOWFLAKE_PASSWORD"],
        "role":      os.environ.get("SNOWFLAKE_ROLE", "DATA_ENGINEER"),
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "DEV_WH"),
    }).create()

    svc = CortexSearchService(session, service_name)
    results = svc.search(
        query=query,
        columns=["ticket_id", "summary", "root_cause", "resolution", "created_at"],
        limit=limit,
    )

    chunks = []
    for r in results.results:
        content = (
            f"[{r.get('ticket_id', 'unknown')}] {r.get('summary', '')}\n"
            f"Root cause: {r.get('root_cause', 'not documented')}\n"
            f"Resolution: {r.get('resolution', 'not documented')}"
        )
        chunks.append(ContextChunk(
            source=service_name,
            source_type="incident_history",
            content=content,
            metadata={
                "ticket_id": r.get("ticket_id"),
                "created_at": str(r.get("created_at", "")),
                "score":      r.get("@SCORE", 0.0),
            },
        ))
    return chunks
