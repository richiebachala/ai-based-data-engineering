# Chapter 10: Intelligent Orchestration — Routing and Remediation
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `pipeline_triage_dag.py` | Airflow DAG: deterministic routing + LLM triage + action execution (page, ticket, defer) |
| `idempotent_ingestion.sql` | MERGE-ON-LOAD, backfill safety check, row count validation, approval gate SQL |
| `approval_gate.py` | Deferrable ApprovalSensor: polls Airflow Variable; no worker slot held between polls |

## Key concepts

- **Triage decision hierarchy**: deterministic routing first (cheap, fast) → LLM only for ambiguous cases
- **Low-confidence escalation**: triage confidence < 0.70 always routes to `PAUSE_FOR_REVIEW`
- **Idempotency**: MERGE-ON-LOAD makes retries safe; the triage DAG's retry actions rely on this
- **Deferrable sensor**: `mode="reschedule"` releases the worker slot; no slot held between polls
- **LLM-generated runbooks**: specific Snowflake queries for this failure, not generic templates

## Bug fixes applied

- **C10-1**: `ti.set_state(TaskInstanceState.UP_FOR_RETRY)` has no effect in Airflow 2.x+.  
  Correct pattern: log the retry intent and let Airflow's retry mechanism handle it (the original task raises an exception when it fails, which triggers the retry).
- **C10-2**: All 7 helper functions defined: `_get_standard_runbook`, `_log_triage_event`, `_page_on_call`, `_create_review_ticket`, `_schedule_background_retry`, `_get_snowflake_conn`, plus the routing logic.

## Approval gate usage

```bash
# Trigger the example DAG
airflow dags trigger opspu_approval_gate_example

# Approve the action (in CLI or via the Snowflake CALL pattern in idempotent_ingestion.sql)
airflow variables set approval_OPSPU_MARTS_FCT_ACTIVE_CUSTOMERS approved

# The DAG resumes and executes_on_approval runs with decision='approved'
```
