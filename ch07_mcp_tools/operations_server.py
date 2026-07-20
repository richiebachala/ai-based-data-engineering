# Chapter 7: Tool and Interface Engineering with MCP
# Section: 7.4 Operations server (approval-gated writes)
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
MCP operations server: approval-gated write operations.

The two-call approval pattern:
  Call 1 (no approval_token): returns approval_required + token
  Call 2 (with approval_token): validates token + executes mutation

This makes the approval state explicit in the tool interface — not just
a prompt instruction. The agent CANNOT write without a human-approved token.

Bug fix C7-1: The approval token survives Pydantic/MCP JSON serialization
because it is passed in the tool INPUT (request.approval_token), not stored
in a JSON-serialized intermediate state.
"""

from mcp.server.fastmcp import FastMCP, Context
import snowflake.connector
from pydantic import BaseModel, Field
from typing import Optional
import hashlib
import hmac
import json
import uuid
import re
import os
from datetime import datetime, timezone

mcp = FastMCP(
    name="opspu-operations",
    instructions=(
        "You are connected to the OpsPulse operations layer. "
        "This server can modify data and catalog metadata. "
        "ALL write operations require a human-approved token. "
        "On the first call, you receive an approval_token to present to a human. "
        "The human approves the change and provides the token back to you. "
        "Include the token in the second call to execute."
    ),
)

_APPROVAL_SECRET = os.environ.get("APPROVAL_HMAC_SECRET", "change-me-in-production")
if _APPROVAL_SECRET == "change-me-in-production":
    raise RuntimeError(
        "APPROVAL_HMAC_SECRET environment variable is not set. "
        "Set it before running the operations server."
    )


class UpdateColumnDescriptionRequest(BaseModel):
    table_fqn:       str  = Field(description="Fully-qualified table name (DB.SCHEMA.TABLE)")
    column_name:     str  = Field(description="Column name to update")
    new_description: str  = Field(description="New column description (max 150 chars)")
    reason:          str  = Field(description="Business justification for this change")
    approval_token:  Optional[str] = Field(
        default=None,
        description="Approval token from a previous call. Omit on the first call."
    )


def _safe_identifier(name: str) -> str:
    """Validate a Snowflake identifier to prevent SQL injection."""
    # Allow only alphanumeric, underscore, and dot (for FQN)
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_.]*$', name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def _create_approval_token(request_data: dict) -> str:
    """
    Create an HMAC token binding the approval to the specific request.
    The token is invalidated if any request field changes.
    """
    payload = json.dumps(request_data, sort_keys=True)
    token   = hmac.new(
        _APPROVAL_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return token


def _validate_approval_token(token: str, request_data: dict) -> bool:
    """Validate the token matches the request data."""
    expected = _create_approval_token(request_data)
    return hmac.compare_digest(token, expected)


def _get_privileged_connection():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "OPS_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "OPSPU"),
        role="CATALOG_WRITER",  # can ALTER TABLE MODIFY COLUMN
    )


def _log_mutation_audit(
    tool: str,
    request: dict,
    query_id: str,
    approval_token: str,
) -> str:
    event_id = str(uuid.uuid4())
    event = {
        "event_id":       event_id,
        "event_type":     "mutation_executed",
        "tool":           tool,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "query_id":       query_id,
        "request_hash":   hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16],
        "approval_token": approval_token,
    }
    with open("mcp_audit.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")
    return event_id


@mcp.tool()
def update_column_description(
    request: UpdateColumnDescriptionRequest,
) -> dict:
    """
    Update a column's business description in Snowflake.

    TWO-CALL PROTOCOL:
      Call 1: omit approval_token. Receive approval_required + token.
              Present the proposed change to a human for review.
      Call 2: include the approval_token from Call 1.
              The change is validated and executed.

    The token is bound to the exact request fields — any modification
    to table_fqn, column_name, or new_description invalidates the token.

    Args:
        request: UpdateColumnDescriptionRequest with all change details
    """
    # The approval_token survives JSON serialization because it is passed
    # in the tool input (request.approval_token), not in a serialized state.
    # Bug fix C7-1: this is the correct pattern.
    approval_token = request.approval_token

    if not approval_token:
        # First call: return approval request
        request_data = request.model_dump(exclude={"approval_token"})
        token = _create_approval_token(request_data)
        return {
            "status":           "approval_required",
            "approval_token":   token,
            "proposed_change":  {
                "table":      request.table_fqn,
                "column":     request.column_name,
                "new_value":  request.new_description,
                "reason":     request.reason,
            },
            "instructions": (
                "A human must review and approve this change. "
                "Call update_column_description again with approval_token set "
                "to the value above."
            ),
        }

    # Second call: validate token and execute
    request_data = request.model_dump(exclude={"approval_token"})
    if not _validate_approval_token(approval_token, request_data):
        return {
            "error":      "INVALID_TOKEN",
            "retryable":  False,
            "message":    "Approval token is invalid or expired. Start a new approval flow.",
        }

    conn = _get_privileged_connection()
    try:
        safe_fqn    = _safe_identifier(request.table_fqn)
        safe_col    = _safe_identifier(request.column_name)
        safe_comment = request.new_description.replace("'", "''")
        with conn.cursor() as cur:
            cur.execute(f"""
                ALTER TABLE {safe_fqn}
                MODIFY COLUMN {safe_col}
                COMMENT '{safe_comment}'
            """)
            query_id = cur.sfqid

        audit_id = _log_mutation_audit(
            tool="update_column_description",
            request=request_data,
            query_id=query_id,
            approval_token=approval_token,
        )

        return {
            "status":         "executed",
            "query_id":       query_id,
            "audit_event_id": audit_id,
        }

    except ValueError as e:
        return {"error": "VALIDATION", "retryable": False, "message": str(e)}
    except Exception as e:
        return {"error": "RUNTIME", "retryable": False, "message": str(e)[:500]}


if __name__ == "__main__":
    mcp.run()
