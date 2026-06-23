# Chapter 5: Context Engineering — Retrieval, Shaping, Provenance
# Section: 5.4 Provenance — source citations and audit logging
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Provenance tracking: source citations in structured outputs + audit log.

Every context chunk carries provenance metadata from creation.
Source citations in structured outputs make AI inference results auditable
without requiring log analysis.

The audit log is the foundation for Chapter 11's observability stack.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================
# Source citation schema
# ============================================================

class SourceCitation(BaseModel):
    source_id:    str  = Field(description="Unique identifier: table FQN, document path, or ticket ID")
    source_type:  str  = Field(description="One of: schema, dbt_model, runbook, incident, policy")
    retrieved_at: str  = Field(description="ISO 8601 UTC timestamp of retrieval")
    relevance:    str  = Field(
        description="How this source contributed: 'schema definition', "
                    "'historical precedent', 'escalation procedure', etc."
    )


class GeneratedSQLWithProvenance(BaseModel):
    """SQL generation output with full source provenance."""
    sql:             str
    explanation:     str
    confidence:      str     # "high" | "medium" | "low"
    missing_context: Optional[str] = None
    assumed_joins:   list[str] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(
        description=(
            "List every context source that contributed to this answer. "
            "Include the schema source (always), plus any runbook sections, "
            "incident reports, or policy documents that influenced the SQL or explanation."
        )
    )


# ============================================================
# Sourced context chunk (extends base ContextChunk with provenance)
# ============================================================

class SourcedContextChunk(BaseModel):
    source:       str
    source_type:  str
    content:      str
    token_estimate: int = 0
    retrieved_at: str   = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    relevance_score: float = 0.0


# ============================================================
# Inference event audit log
# ============================================================

def log_inference_event(
    question:      str,
    context_chunks: list,          # list of SourcedContextChunk or plain ContextChunk
    output:        BaseModel,
    model:         str,
    workflow_step: str,
    audit_file:    str = "inference_audit.jsonl",
) -> str:
    """
    Log a complete inference event to the audit trail.
    Returns the event_id.

    Writes JSONL format (one JSON object per line) for easy streaming.
    In production: write to Snowflake audit table via Snowpipe or INSERT.
    """
    event_id = str(uuid.uuid4())
    event = {
        "event_id":        event_id,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "workflow_step":   workflow_step,
        "model":           model,
        "question":        question,
        "context_sources": [
            {
                "source":    getattr(chunk, 'source', 'unknown'),
                "type":      getattr(chunk, 'source_type', 'unknown'),
                "tokens":    getattr(chunk, 'token_estimate', 0),
                "included":  True,
            }
            for chunk in context_chunks
        ],
        "tokens_used":    sum(getattr(c, 'token_estimate', 0) for c in context_chunks),
        "output_summary": output.model_dump() if hasattr(output, "model_dump") else str(output),
    }

    with open(audit_file, "a") as f:
        f.write(json.dumps(event) + "\n")

    return event_id


def replay_audit_event(event_id: str, audit_file: str = "inference_audit.jsonl") -> Optional[dict]:
    """Retrieve a specific audit event by ID. Used for debugging wrong answers."""
    try:
        with open(audit_file) as f:
            for line in f:
                event = json.loads(line.strip())
                if event.get("event_id") == event_id:
                    return event
    except FileNotFoundError:
        return None
    return None


# ============================================================
# Snowflake audit table DDL (reference)
# ============================================================

AUDIT_TABLE_DDL = """
CREATE OR REPLACE TABLE OPSPU.PLATFORM.AI_INFERENCE_AUDIT (
    event_id       VARCHAR        NOT NULL,
    timestamp      TIMESTAMP_TZ   NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    workflow_step  VARCHAR,
    model          VARCHAR,
    question_hash  VARCHAR,       -- SHA-256 of question; never log raw PII questions
    context_sources VARIANT,      -- JSON array of {source, type, tokens, included}
    tokens_used    INT,
    output_summary VARIANT,
    PRIMARY KEY (event_id)
);
"""


if __name__ == "__main__":
    # Demo: log a synthetic inference event

    class DemoOutput(BaseModel):
        sql: str
        confidence: str

    class DemoChunk:
        source = "OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS"
        source_type = "schema"
        token_estimate = 250

    event_id = log_inference_event(
        question="How many active customers in EMEA?",
        context_chunks=[DemoChunk()],
        output=DemoOutput(sql="SELECT COUNT(*) FROM fct_active_customers WHERE region_code = 'EMEA'",
                          confidence="high"),
        model="claude-sonnet-4-5",
        workflow_step="sql_generation",
    )
    print(f"Logged event_id: {event_id}")
    event = replay_audit_event(event_id)
    print(f"Retrieved: {event['workflow_step']} | model={event['model']}")
