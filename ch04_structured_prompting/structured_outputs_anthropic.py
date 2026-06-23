# Chapter 4: Prompting On-Ramp and Structured Prompting
# Section: 4.3 Structured outputs — Anthropic tool_choice pattern
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Structured outputs using the Anthropic tool_choice API.

The tool_choice={"type": "tool", "name": "..."}  forces the model to
call exactly one tool with the specified schema. The model CANNOT
produce free text — every response is parsed JSON conforming to the
Pydantic schema. This replaces fragile text parsing with a protocol-
level guarantee.

This is the canonical structured output pattern used throughout Parts
2 and 3 of the book.
"""

import anthropic
from pydantic import BaseModel, Field
from typing import Optional
import json

client = anthropic.Anthropic()


# ============================================================
# Output schemas (Pydantic models become the tool input_schema)
# ============================================================

class SQLGenerationOutput(BaseModel):
    """Structured output for SQL generation."""
    sql:              str   = Field(description="Valid Snowflake SELECT query")
    explanation:      str   = Field(description="Max 2-sentence description of what the query returns")
    confidence:       str   = Field(description="One of: high, medium, low")
    assumed_joins:    list[str] = Field(
        default_factory=list,
        description="Join conditions inferred from schema, not explicitly requested"
    )


class AnomalyClassification(BaseModel):
    """Structured output for anomaly triage routing."""
    anomaly_type:       str   = Field(description="One of: volume_drop, schema_change, freshness_breach, quality_failure, lineage_break, unknown")
    confidence:         float = Field(ge=0.0, le=1.0)
    primary_signal:     str   = Field(description="The data point that drove the classification")
    recommended_action: str


class ColumnDescriptionOutput(BaseModel):
    """Structured output for column documentation."""
    column_name:   str
    description:   str  = Field(description="One sentence, under 150 chars, no jargon")
    passed:        bool = Field(description="True if description meets all style rules")
    feedback:      str  = Field(default="", description="Style issues, if any")


# ============================================================
# Generating structured SQL output
# ============================================================

def generate_structured_sql(
    business_question: str,
    table_schema: dict,
) -> SQLGenerationOutput:
    """
    Generate SQL with API-enforced structured output.

    The model CANNOT produce free text — it MUST call the 'generate_sql' tool.
    The response is always a valid SQLGenerationOutput, never a string.
    """
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=(
            "You are a senior Snowflake data engineer. Write read-only SELECT queries. "
            "Never reference tables not in the provided schema."
        ),
        tools=[{
            "name": "generate_sql",
            "description": "Generate a Snowflake SQL query for the business question.",
            "input_schema": SQLGenerationOutput.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "generate_sql"},
        messages=[{"role": "user", "content": (
            f"Business question: {business_question}\n"
            f"Schema: {json.dumps(table_schema)}"
        )}]
    )
    tool_block = next(b for b in response.content if b.type == "tool_use")
    return SQLGenerationOutput(**tool_block.input)


# ============================================================
# Generating structured anomaly classification
# ============================================================

def classify_alert_structured(
    alert_payload: dict,
) -> AnomalyClassification:
    """Classify an alert with API-enforced structured output."""
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        system=(
            "Classify data pipeline alerts. Never speculate beyond the alert data. "
            "Use anomaly_type=unknown and confidence<0.5 when uncertain."
        ),
        tools=[{
            "name": "classify_alert",
            "description": "Classify the anomaly type from the alert payload.",
            "input_schema": AnomalyClassification.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "classify_alert"},
        messages=[{"role": "user", "content": (
            f"Alert: {json.dumps(alert_payload)}\n"
            "Types: volume_drop | schema_change | freshness_breach | "
            "quality_failure | lineage_break | unknown"
        )}]
    )
    tool_block = next(b for b in response.content if b.type == "tool_use")
    return AnomalyClassification(**tool_block.input)


# ============================================================
# Structured column description with evaluation
# ============================================================

def generate_column_description_structured(
    table_name: str,
    column_name: str,
    data_type: str,
    table_context: str = "",
) -> ColumnDescriptionOutput:
    """Generate and self-evaluate a column description in one call."""
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,
        system=(
            "Write one-sentence column descriptions for a dbt catalog. "
            "Audience: business analysts. Under 150 chars. No jargon."
        ),
        tools=[{
            "name": "write_description",
            "description": "Write and self-evaluate a column description.",
            "input_schema": ColumnDescriptionOutput.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "write_description"},
        messages=[{"role": "user", "content": (
            f"Table: {table_name}  Column: {column_name} ({data_type})\n"
            f"Context: {table_context}"
        )}]
    )
    tool_block = next(b for b in response.content if b.type == "tool_use")
    return ColumnDescriptionOutput(**tool_block.input)


if __name__ == "__main__":
    schema = {
        "table": "OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS",
        "columns": [
            {"name": "customer_id",  "type": "VARCHAR"},
            {"name": "active_since", "type": "TIMESTAMP_NTZ"},
            {"name": "region_code",  "type": "VARCHAR"},
        ]
    }
    result = generate_structured_sql(
        "Count active customers per region for the last 30 days",
        schema,
    )
    print(f"SQL: {result.sql}")
    print(f"Explanation: {result.explanation}")
    print(f"Confidence: {result.confidence}")
    if result.assumed_joins:
        print(f"Assumed joins: {result.assumed_joins}")
