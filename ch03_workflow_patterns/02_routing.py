# Chapter 3: Workflows vs Agents for Data Engineering
# Section: 3.1 Five composable workflow patterns — Routing
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Routing: a classifier step inspects the input and dispatches to the
specialized handler appropriate for that input type.

OpsPulse use case: anomaly triage routing
  - Classifier (haiku): identify the anomaly type from alert payload
  - Specialist handlers: one per anomaly type, each with its own
    prompt and tool access

The routing pattern avoids one-size-fits-all prompts that work
poorly on every category.
"""

import anthropic
from enum import Enum
from pydantic import BaseModel, Field
import json

client = anthropic.Anthropic()


class AnomalyType(str, Enum):
    VOLUME_DROP      = "volume_drop"
    SCHEMA_CHANGE    = "schema_change"
    FRESHNESS_BREACH = "freshness_breach"
    QUALITY_FAILURE  = "quality_failure"
    LINEAGE_BREAK    = "lineage_break"
    UNKNOWN          = "unknown"


class TriageClassification(BaseModel):
    anomaly_type:      AnomalyType
    confidence:        float = Field(ge=0.0, le=1.0)
    primary_signal:    str
    recommended_action: str


CLASSIFIER_SYSTEM = """
You are a data reliability engineer triaging data pipeline alerts.
Classify anomalies into canonical types to route them to the correct
specialist handler. Never speculate beyond what the alert data supports.
When uncertain, use anomaly_type=unknown and set confidence below 0.5.
"""


def classify_alert(alert_payload: dict) -> TriageClassification:
    """
    Classifier step: identify anomaly type from alert payload.
    Uses claude-haiku-4-5 for speed and low cost (narrow taxonomy task).
    """
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        system=CLASSIFIER_SYSTEM,
        tools=[{
            "name": "classify",
            "description": "Classify the anomaly type.",
            "input_schema": TriageClassification.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "classify"},
        messages=[{
            "role": "user",
            "content": (
                f"Alert payload: {json.dumps(alert_payload)}\n\n"
                "Classification rules:\n"
                "- volume_drop: row count or record volume fell below threshold\n"
                "- schema_change: column added, removed, renamed, or type changed\n"
                "- freshness_breach: data not updated within the expected window\n"
                "- quality_failure: null rate, uniqueness, or referential integrity breach\n"
                "- lineage_break: upstream table or model failed to produce output\n"
                "- unknown: insufficient data to classify confidently"
            )
        }]
    )
    tool_call = next(b for b in response.content if b.type == "tool_use")
    return TriageClassification(**tool_call.input)


# --- Specialist handlers (one per anomaly type) ---

def handle_volume_drop(alert: dict, classification: TriageClassification) -> dict:
    """Specialist: investigate row count drops."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        system=(
            "You are a data reliability engineer investigating row count drops. "
            "Identify the most likely root cause and provide specific remediation steps "
            "for a Snowflake/Airflow stack."
        ),
        messages=[{"role": "user", "content": (
            f"Alert: {json.dumps(alert)}\n"
            f"Classification: {classification.model_dump_json()}\n\n"
            "Provide: root cause hypothesis, verification query, remediation steps."
        )}]
    )
    return {"handler": "volume_drop", "analysis": response.content[0].text}


def handle_schema_change(alert: dict, classification: TriageClassification) -> dict:
    """Specialist: investigate schema changes."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        system=(
            "You are a data reliability engineer investigating schema changes. "
            "Identify which column changed, which downstream consumers are affected, "
            "and what remediation is needed."
        ),
        messages=[{"role": "user", "content": (
            f"Alert: {json.dumps(alert)}\n\n"
            "Provide: changed column, impact assessment, migration path."
        )}]
    )
    return {"handler": "schema_change", "analysis": response.content[0].text}


def handle_quality_failure(alert: dict, classification: TriageClassification) -> dict:
    """Specialist: investigate data quality failures."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        system=(
            "You are a data reliability engineer investigating data quality failures. "
            "Analyze null rate, uniqueness, or referential integrity issues and "
            "recommend remediation."
        ),
        messages=[{"role": "user", "content": (
            f"Alert: {json.dumps(alert)}\n\n"
            "Provide: quality dimension failing, root cause, fix."
        )}]
    )
    return {"handler": "quality_failure", "analysis": response.content[0].text}


def handle_unknown(alert: dict, classification: TriageClassification) -> dict:
    """Fallback handler: low-confidence classification → escalate."""
    return {
        "handler": "escalation",
        "analysis": "Confidence below threshold. Escalated to on-call engineer.",
        "alert": alert,
        "classification": classification.model_dump(),
    }


ROUTE_MAP = {
    AnomalyType.VOLUME_DROP:      handle_volume_drop,
    AnomalyType.SCHEMA_CHANGE:    handle_schema_change,
    AnomalyType.QUALITY_FAILURE:  handle_quality_failure,
    AnomalyType.FRESHNESS_BREACH: handle_unknown,   # STUB: add freshness handler
    AnomalyType.LINEAGE_BREAK:    handle_unknown,   # STUB: add lineage handler
    AnomalyType.UNKNOWN:          handle_unknown,
}


def triage_alert(alert_payload: dict) -> dict:
    """
    Full routing pipeline:
    1. Classifier identifies anomaly type
    2. Router dispatches to the specialist handler
    3. Handler returns structured triage result

    Escalates automatically if confidence < 0.70.
    """
    classification = classify_alert(alert_payload)

    if classification.confidence < 0.70:
        return handle_unknown(alert_payload, classification)

    handler = ROUTE_MAP.get(classification.anomaly_type, handle_unknown)
    result = handler(alert_payload, classification)
    result["classification"] = classification.model_dump()
    return result


if __name__ == "__main__":
    # Example: row count drop on fct_sales
    alert = {
        "table": "OPSPU.MARTS.FCT_SALES",
        "check": "row_count",
        "row_count_today": 4200,
        "row_count_yesterday": 9800,
        "threshold_pct": 20,
    }
    print(f"Triaging alert: {alert}")
    result = triage_alert(alert)
    print(f"Handler: {result['handler']}")
    print(f"Analysis:\n{result.get('analysis', 'N/A')}")
