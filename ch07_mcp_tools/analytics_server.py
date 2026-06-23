# Chapter 7: Tool and Interface Engineering with MCP
# Section: 7.3 Analytics server (safe SQL execution with guardrails)
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
MCP analytics server: SQL execution with safety guardrails and injection detection.

Safety layers:
  1. SQL allowlist: only SELECT; blocks DML, DDL, multi-statement
  2. Row cap: maximum 1,000 rows returned
  3. Injection detection: scans query text for injection patterns
  4. Audit logging: every query logged to the audit trail

This server is READ-ONLY. Separate the read server from the write server.
No amount of 'please don't modify data' in the system prompt is as effective
as a server that physically cannot modify data.
"""

from mcp.server.fastmcp import FastMCP, Context
import snowflake.connector
import hashlib
import json
import uuid
import re
import os
from datetime import datetime, timezone

mcp = FastMCP(
    name="opspu-analytics",
    instructions=(
        "You are connected to the OpsPulse analytics layer. "
        "This server executes read-only SELECT queries. "
        "Always retrieve the table schema from the catalog server before "
        "writing SQL. Do not guess column names. "
        "Queries are limited to 1,000 rows; use aggregation for summary statistics."
    ),
)

# Compiled injection pattern detector
INJECTION_PATTERNS = re.compile(
    r'(ignore\s+(?:previous|prior|all)\s+instructions?'
    r'|disregard\s+(?:your|the)\s+(?:previous|prior)\s+(?:instructions?|context)'
    r'|you\s+are\s+now\s+(?:a|an|acting\s+as)'
    r'|act\s+as\s+(?:a|an)\s+(?:different|new)\s+(?:ai|assistant|model)'
    r'|export\s+(?:all|the)\s+(?:data|contents|rows))'
    r'|--\s*override|/\*.*override.*\*/',
    re.IGNORECASE | re.DOTALL,
)

BLOCKED_KEYWORDS = re.compile(
    r'\b(DELETE|INSERT|UPDATE|MERGE|CREATE|ALTER|DROP|TRUNCATE|CALL|EXECUTE|GRANT|REVOKE)\b',
    re.IGNORECASE,
)


def _get_read_connection():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "ANALYTICS_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "OPSPU"),
        role="ANALYST_READ",  # read-only role; cannot DML
    )


def _hash_sql(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()[:16]


def _scan_for_injection(sql: str) -> tuple[bool, str]:
    """Returns (is_injection, matched_pattern)."""
    match = INJECTION_PATTERNS.search(sql)
    if match:
        return True, match.group(0)
    return False, ""


def _validate_sql(sql: str) -> tuple[bool, str]:
    """
    Validate that the SQL is a safe read-only SELECT.
    Returns (is_valid, error_message).
    """
    sql_stripped = sql.strip()

    # Must start with SELECT (after stripping leading whitespace/comments)
    sql_no_comments = re.sub(r'/\*.*?\*/', '', sql_stripped, flags=re.DOTALL)
    sql_no_comments = re.sub(r'--[^\n]*', '', sql_no_comments).strip()

    if not sql_no_comments.upper().startswith("SELECT"):
        return False, "Query must be a SELECT statement."

    # No DML keywords anywhere
    match = BLOCKED_KEYWORDS.search(sql)
    if match:
        return False, f"Blocked keyword: {match.group(0)}. Only SELECT is allowed."

    # No semicolons (prevents multi-statement injection)
    if ";" in sql:
        return False, "Multi-statement queries (semicolons) are not allowed."

    return True, ""


def _log_query_audit(query_id: str, sql: str, row_count: int) -> str:
    """Log read query to the audit trail. Returns audit event ID."""
    event_id = str(uuid.uuid4())
    event = {
        "event_id":   event_id,
        "event_type": "tool_invocation",
        "tool":       "run_snowflake_select",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "query_id":   query_id,
        "sql_hash":   _hash_sql(sql),
        "row_count":  row_count,
    }
    # In production: write to Snowflake audit table
    with open("mcp_audit.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")
    return event_id


@mcp.tool()
async def run_snowflake_select(
    sql: str,
    max_rows: int = 100,
    ctx: Context = None,
) -> dict:
    """
    Execute a read-only SELECT query against the OpsPulse Snowflake warehouse.

    Returns up to max_rows rows (hard cap: 1,000). Use aggregation (GROUP BY,
    COUNT, SUM) for summary statistics that would exceed the row cap.

    Safety: the query is validated for injection patterns and blocked keywords
    before execution. Only SELECT statements are permitted.

    Args:
        sql:      A valid Snowflake SELECT statement. Must not contain DML,
                  DDL, or semicolons. Use CURRENT_DATE for date references.
        max_rows: Maximum rows to return (default 100, hard cap 1000)
    """
    max_rows = min(max_rows, 1000)  # hard cap

    # Layer 1: injection detection
    is_injection, pattern = _scan_for_injection(sql)
    if is_injection:
        return {
            "error":      "INJECTION_DETECTED",
            "retryable":  False,
            "message":    "Query contains injection pattern and was blocked.",
            "pattern":    pattern[:100],
        }

    # Layer 2: SQL validation
    is_valid, validation_error = _validate_sql(sql)
    if not is_valid:
        return {
            "error":     "VALIDATION",
            "retryable": False,
            "message":   validation_error,
        }

    conn = _get_read_connection()
    try:
        with conn.cursor() as cur:
            # Apply row cap via LIMIT injection
            limited_sql = f"SELECT * FROM ({sql}) __q LIMIT {max_rows}"
            cur.execute(limited_sql)
            columns  = [d[0] for d in cur.description]
            rows     = cur.fetchall()
            query_id = cur.sfqid

        audit_id = _log_query_audit(query_id, sql, len(rows))

        return {
            "columns":    columns,
            "rows":       [list(r) for r in rows],
            "row_count":  len(rows),
            "query_id":   query_id,
            "audit_id":   audit_id,
            "capped":     len(rows) == max_rows,
        }

    except Exception as e:
        error_str = str(e)
        return {
            "error":     "RUNTIME",
            "retryable": "timeout" in error_str.lower() or "network" in error_str.lower(),
            "message":   error_str[:500],
        }


if __name__ == "__main__":
    mcp.run()
