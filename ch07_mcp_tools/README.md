# Chapter 7: Tool and Interface Engineering with MCP
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `catalog_server.py` | Read-only FastMCP server: schema resources + search tools. The agent's first call before any SQL. |
| `analytics_server.py` | SQL execution server with injection detection, keyword blocklist, row cap, and audit logging. |
| `operations_server.py` | Approval-gated write server: two-call HMAC token pattern for column description updates. |

## Architecture: two-server separation

```
AI Agent
  ├── catalog_server  (read-only: schema, lineage, search)
  ├── analytics_server (read-only: SQL execution, capped at 1000 rows)
  └── operations_server (writes: approval token required for every mutation)
```

Separating read from write servers enforces safety structurally, not via prompting.
No "please don't modify data" instruction is as effective as a server that cannot.

## ACI principle

Every sentence in a tool's `description` and parameter `description` is a
behavioral instruction to the model. Ambiguous documentation = ambiguous behavior.

## Two-call approval pattern (operations_server)

```python
# Call 1: no approval_token → returns proposed change + token
result = update_column_description(request=UpdateColumnDescriptionRequest(
    table_fqn="OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS",
    column_name="active_since",
    new_description="Timestamp of first qualifying event in trailing 30-day window.",
    reason="Clarify business meaning for catalog consumers",
))
# result["status"] == "approval_required"
# result["approval_token"] == "<hmac_token>"

# Human reviews the proposed change and approves
# Call 2: include the approval token
result = update_column_description(request=UpdateColumnDescriptionRequest(
    ...,
    approval_token="<hmac_token from call 1>",
))
# result["status"] == "executed"
```

## Bug fix applied

**C7-1**: Approval token survives Pydantic/MCP JSON serialization because it is
passed in the tool INPUT (`request.approval_token`), not stored in an intermediate
JSON-serialized state object.

## Running the servers

```bash
# Set environment variables
export SNOWFLAKE_ACCOUNT=your_account
export SNOWFLAKE_USER=your_user
export SNOWFLAKE_PASSWORD=your_password
export APPROVAL_HMAC_SECRET=a-strong-random-secret

# Start catalog server on stdio (for Claude Desktop / Cursor)
python catalog_server.py

# Start analytics server
python analytics_server.py

# Start operations server
python operations_server.py
```
