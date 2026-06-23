# Chapter 10: Intelligent Orchestration — Routing and Remediation
# Section: 10.5 Deferrable approval gate (ApprovalSensor)
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Deferrable approval gate using Airflow's sensor + reschedule mode.

The deferrable sensor pattern:
  1. Sensor polls an Airflow Variable for the approval state
  2. Uses mode='reschedule' so no worker slot is held between polls
  3. Returns PokeReturnValue(is_done=True) when a human sets the variable
  4. Downstream tasks see the approval decision as xcom_value

Used in:
  - Chapter 10: pipeline action approval
  - Chapter 12: data stewardship classification review
"""

from __future__ import annotations

from datetime import datetime, timezone
from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.sensors.base import PokeReturnValue
from typing import Optional


# ============================================================
# ApprovalSensor: poll an Airflow Variable for a decision
# ============================================================

@task.sensor(
    poke_interval=60,      # poll every 60 seconds
    timeout=86400,         # 24-hour timeout
    mode="reschedule",     # release worker slot between polls
)
def await_approval(
    approval_key: str,
    description: str = "",
) -> PokeReturnValue:
    """
    Wait for a human to set the Airflow Variable `approval_key` to
    'approved' or 'rejected'.

    Usage:
      # Approve from CLI:
      airflow variables set <approval_key> approved

      # Reject from CLI:
      airflow variables set <approval_key> rejected

    The sensor returns:
      - is_done=True  with xcom_value={'decision': 'approved'|'rejected'}
        when the variable is set to either value
      - is_done=False while waiting
    """
    decision = Variable.get(approval_key, default_var=None)

    if decision in ("approved", "rejected"):
        # Clean up the variable so the next run starts fresh
        Variable.delete(approval_key)
        return PokeReturnValue(
            is_done=True,
            xcom_value={"decision": decision, "key": approval_key},
        )

    return PokeReturnValue(is_done=False, xcom_value=None)


# ============================================================
# Example DAG using the approval gate
# ============================================================

@dag(
    dag_id="opspu_approval_gate_example",
    schedule=None,
    start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    tags=["orchestration", "approval"],
)
def approval_gate_example_dag():

    @task
    def propose_action(table_fqn: str) -> dict:
        """
        Propose a pipeline action and notify the engineer.
        Returns the approval key so the sensor knows what to poll.
        """
        approval_key = f"approval_{table_fqn.lower().replace('.', '_')}"
        message = (
            f"Pipeline action proposed for {table_fqn}. "
            f"Set Airflow Variable '{approval_key}' to 'approved' or 'rejected'."
        )
        print(f"[NOTIFY ENGINEER] {message}")
        # In production: send Slack message with approve/reject buttons
        return {"approval_key": approval_key, "table_fqn": table_fqn}

    @task
    def execute_on_approval(proposal: dict, approval_result: dict) -> dict:
        """Execute the action only if approved."""
        decision = approval_result.get("decision", "rejected")
        table    = proposal["table_fqn"]

        if decision == "approved":
            print(f"[EXECUTE] Running approved pipeline action for {table}")
            # In production: trigger the actual pipeline action
            return {"outcome": "executed", "table": table}
        else:
            print(f"[REJECTED] Pipeline action for {table} was rejected by human reviewer")
            return {"outcome": "rejected", "table": table}

    # DAG wiring
    proposal = propose_action(table_fqn="OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS")
    approval = await_approval(
        approval_key=proposal["approval_key"],
        description="Review proposed pipeline action",
    )
    execute_on_approval(proposal=proposal, approval_result=approval)


approval_gate_example_dag()
