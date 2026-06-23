# Chapter 10: Intelligent Orchestration — Routing and Remediation
# Section: 10.1-10.3 Pipeline triage, idempotency, approval gate
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Airflow DAG for intelligent pipeline triage and repair.

Bug fix C10-1: ti.set_state(TaskInstanceState.UP_FOR_RETRY) in failure callback
has no effect in Airflow 2.x+. The correct pattern is to raise an exception
(which Airflow handles as a retry) or use on_failure_callback with alerting only.

Bug fix C10-2: All 7 helper functions are defined (not just referenced).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import anthropic
import snowflake.connector
from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.sensors.base import PokeReturnValue
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

client = anthropic.Anthropic()


# ============================================================
# Triage data models
# ============================================================

class TriageAction(str, Enum):
    RETRY_IMMEDIATELY  = "retry_immediately"    # transient; safe to retry now
    RETRY_WITH_BACKOFF = "retry_with_backoff"   # transient; wait before retry
    PAUSE_FOR_REVIEW   = "pause_for_review"     # ambiguous quality failure
    ESCALATE_CRITICAL  = "escalate_critical"    # SLA breach; page on-call
    DEFER_TO_BACKGROUND = "defer_to_background" # low priority; run off-peak


class TriageResult(BaseModel):
    action:          TriageAction
    confidence:      float = Field(ge=0.0, le=1.0)
    root_cause:      str
    runbook:         str
    affected_consumers: list[str] = Field(default_factory=list)


# ============================================================
# Routing logic (deterministic, no LLM needed)
# ============================================================

def route_failure(
    error_type: str,
    null_rate: Optional[float],
    minutes_late: Optional[float],
    retry_count: int,
) -> Optional[TriageAction]:
    """
    Route obvious cases deterministically before calling the LLM.
    Returns None for ambiguous cases that require LLM triage.
    """
    # Connection / transient network errors → retry immediately
    if any(term in error_type.lower() for term in
           ["connection", "timeout", "network", "ssl", "temporary"]):
        if retry_count < 3:
            return TriageAction.RETRY_IMMEDIATELY

    # Critical SLA breach (> 60 min late) → page immediately
    if minutes_late and minutes_late > 60:
        return TriageAction.ESCALATE_CRITICAL

    # Consecutive retries exhausted → pause for human review
    if retry_count >= 3:
        return TriageAction.PAUSE_FOR_REVIEW

    # Ambiguous → LLM triage
    return None


# ============================================================
# LLM triage for ambiguous failures
# ============================================================

def llm_triage_failure(
    table_fqn: str,
    error_message: str,
    null_rate: Optional[float],
    affected_consumers: list[str],
    schema_context: str = "",
) -> TriageResult:
    """
    LLM-powered triage for ambiguous quality failures.
    Used only when deterministic routing cannot classify the failure.
    """
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=800,
        system=(
            "You are a data reliability engineer triaging Airflow pipeline failures. "
            "Classify the failure and produce a specific, actionable runbook. "
            "The runbook must include specific Snowflake queries to diagnose the issue, "
            "not generic advice."
        ),
        tools=[{
            "name": "triage",
            "description": "Return a structured triage result.",
            "input_schema": TriageResult.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "triage"},
        messages=[{"role": "user", "content": (
            f"Table: {table_fqn}\n"
            f"Error: {error_message[:500]}\n"
            f"Null rate: {null_rate}\n"
            f"Affected consumers: {affected_consumers}\n"
            f"Schema context: {schema_context[:200]}"
        )}]
    )
    tool_call = next(b for b in response.content if b.type == "tool_use")
    return TriageResult(**tool_call.input)


# ============================================================
# Airflow DAG
# ============================================================

@dag(
    dag_id="opspu_pipeline_triage",
    schedule=None,   # triggered by failure callbacks
    start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    tags=["orchestration", "triage"],
)
def opspu_pipeline_triage_dag():

    @task
    def assess_failure(failure_context: dict) -> dict:
        """
        Step 1: Route the failure deterministically.
        Falls through to LLM triage for ambiguous cases.
        """
        error_type  = failure_context.get("error_type", "")
        null_rate   = failure_context.get("null_rate")
        minutes_late = failure_context.get("minutes_late")
        retry_count  = failure_context.get("retry_count", 0)
        table_fqn    = failure_context.get("table_fqn", "")

        # Deterministic routing
        deterministic_action = route_failure(
            error_type, null_rate, minutes_late, retry_count
        )

        if deterministic_action:
            return {
                "action":      deterministic_action.value,
                "confidence":  1.0,
                "root_cause":  f"Deterministic routing: {error_type}",
                "runbook":     _get_standard_runbook(deterministic_action),
                "source":      "deterministic",
            }

        # LLM triage for ambiguous cases
        triage = llm_triage_failure(
            table_fqn=table_fqn,
            error_message=failure_context.get("error_message", ""),
            null_rate=null_rate,
            affected_consumers=failure_context.get("affected_consumers", []),
        )

        # Low-confidence recommendations → always escalate
        if triage.confidence < 0.70:
            triage = TriageResult(
                action=TriageAction.PAUSE_FOR_REVIEW,
                confidence=triage.confidence,
                root_cause="Low-confidence triage — escalated for human review",
                runbook=triage.runbook,
                affected_consumers=triage.affected_consumers,
            )

        return {**triage.model_dump(), "source": "llm"}

    @task
    def execute_triage_action(triage_result: dict, failure_context: dict) -> dict:
        """
        Step 2: Execute the recommended action.
        Bug fix C10-1: do NOT use ti.set_state(TaskInstanceState.UP_FOR_RETRY).
        Retries are triggered by raising an exception in the task.
        """
        action = TriageAction(triage_result["action"])

        if action == TriageAction.RETRY_IMMEDIATELY:
            # Log and return; Airflow retries when the original task raises again
            _log_triage_event(triage_result, failure_context, "retry_scheduled")
            return {"outcome": "retry_logged", "action": action.value}

        elif action == TriageAction.ESCALATE_CRITICAL:
            _page_on_call(
                table=failure_context.get("table_fqn", ""),
                runbook=triage_result["runbook"],
                affected=triage_result.get("affected_consumers", []),
            )
            return {"outcome": "paged", "action": action.value}

        elif action == TriageAction.PAUSE_FOR_REVIEW:
            _create_review_ticket(
                table=failure_context.get("table_fqn", ""),
                triage=triage_result,
            )
            return {"outcome": "ticket_created", "action": action.value}

        elif action == TriageAction.DEFER_TO_BACKGROUND:
            _schedule_background_retry(failure_context)
            return {"outcome": "deferred", "action": action.value}

        return {"outcome": "no_action", "action": action.value}

    # DAG wiring
    failure_ctx = {}  # populated at runtime via dag_run.conf
    result = assess_failure(failure_context=failure_ctx)
    execute_triage_action(triage_result=result, failure_context=failure_ctx)


opspu_pipeline_triage_dag()


# ============================================================
# Helper functions (Bug fix C10-2: all defined, not just referenced)
# ============================================================

def _get_standard_runbook(action: TriageAction) -> str:
    """Return the standard runbook text for deterministic actions."""
    runbooks = {
        TriageAction.RETRY_IMMEDIATELY:   "Transient error detected. Airflow will retry automatically.",
        TriageAction.ESCALATE_CRITICAL:   "SLA breach detected. Page on-call immediately.",
        TriageAction.PAUSE_FOR_REVIEW:    "Retry limit reached. Create ticket for investigation.",
        TriageAction.DEFER_TO_BACKGROUND: "Low priority. Schedule retry during off-peak window.",
        TriageAction.RETRY_WITH_BACKOFF:  "Transient error. Retry with exponential backoff.",
    }
    return runbooks.get(action, "No standard runbook available.")


def _log_triage_event(triage: dict, context: dict, outcome: str) -> None:
    """Log the triage event to the audit trail."""
    import json, uuid
    event = {
        "event_id":   str(uuid.uuid4()),
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "outcome":    outcome,
        "triage":     triage,
        "context":    {k: v for k, v in context.items() if k != "error_message"},
    }
    with open("triage_audit.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")


def _page_on_call(table: str, runbook: str, affected: list[str]) -> None:
    """Send critical alert to on-call engineer (Slack / PagerDuty stub)."""
    message = (
        f"[CRITICAL] Pipeline failure on {table}\n"
        f"Affected consumers: {', '.join(affected)}\n"
        f"Runbook:\n{runbook}"
    )
    print(f"[PAGE ON-CALL] {message}")
    # In production: post to Slack webhook or PagerDuty API


def _create_review_ticket(table: str, triage: dict) -> str:
    """Create a Jira ticket for human review. Returns the ticket ID."""
    # STUB: replace with real Jira API call using JIRA_* env vars
    ticket_id = f"OPS-{hash(table) % 10000:04d}"
    print(f"[TICKET CREATED] {ticket_id} for {table}: {triage.get('root_cause', '')}")
    return ticket_id


def _schedule_background_retry(context: dict) -> None:
    """Schedule a low-priority retry during the next off-peak window."""
    # STUB: trigger the DAG with a 4-hour delay
    print(f"[DEFER] Scheduling background retry for {context.get('table_fqn', 'unknown')}")


def _get_snowflake_conn():
    return snowflake.connector.connect(
        account=Variable.get("SNOWFLAKE_ACCOUNT"),
        user=Variable.get("SNOWFLAKE_SERVICE_USER"),
        password=Variable.get("SNOWFLAKE_SERVICE_PASSWORD"),
        warehouse="OPS_WH",
        database="OPSPU",
    )
