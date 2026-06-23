# Chapter 4: Prompting On-Ramp and Structured Prompting
# Section: 4.1-4.2 Minimum viable prompting / PTCF patterns
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
PTCF (Persona / Task / Context / Format) prompt builder.

Encodes prompt components as a dataclass to make prompts:
  - Version-controllable (stored as code, not as strings in a notebook)
  - Diffable (git diff shows exactly what changed between v1 and v2)
  - Testable (PromptFoo test cases in Section 4.4)
  - Composable (build column/SQL/triage prompts from the same base)

The five constraint-set elements that address the three failure modes:
  1. Role           — who the model is, what dialect/constraints apply
  2. Schema context — tables, columns, types, descriptions in scope
  3. Prohibited     — what the model must NOT do
  4. Output contract— exact format of the expected output
  5. Fallback       — what to return when context is insufficient
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import anthropic

client = anthropic.Anthropic()


@dataclass
class DataEngineeringPrompt:
    """
    PTCF (Persona/Task/Context/Format) prompt builder.

    Encodes prompt components explicitly to make prompts first-class code
    artifacts: version-controllable, diffable, and testable with PromptFoo.
    """
    persona:              str
    task:                 str
    context:              dict           # structured; serialized as JSON in the user message
    output_format:        str
    fallback_instruction: str = (
        'If you cannot produce a valid answer with the provided context, return: '
        '{"error": "insufficient_context", "missing": "<describe what is missing>"}'
    )
    chain_of_thought:     bool = False

    def to_system_message(self) -> str:
        """Build the system message from Persona + fallback instruction."""
        parts = [self.persona, self.fallback_instruction]
        if self.chain_of_thought:
            # Insert CoT instruction between persona and fallback
            parts.insert(1, "Think step by step before producing your final answer.")
        return "\n\n".join(parts)

    def to_user_message(self) -> str:
        """Build the user message from Task + Context + Format."""
        context_block = json.dumps(self.context, indent=2)
        return (
            f"Task: {self.task}\n\n"
            f"Context:\n{context_block}\n\n"
            f"Output format: {self.output_format}"
        )

    def to_messages(self) -> list[dict]:
        """
        Return the user messages array.
        Pass to_system_message() separately via the Anthropic `system=` parameter.
        For OpenAI: prepend {"role": "system", "content": self.to_system_message()}.
        """
        return [{"role": "user", "content": self.to_user_message()}]


# ============================================================
# SQL generation with PTCF
# ============================================================

def generate_safe_sql(
    business_question: str,
    table_schema: dict,
    business_glossary: Optional[dict] = None,
) -> str:
    """Generate Snowflake-safe SQL using the PTCF prompt structure."""
    prompt = DataEngineeringPrompt(
        persona=(
            "You are a senior Snowflake data engineer. "
            "You write read-only SELECT queries in Snowflake SQL dialect. "
            "You never reference tables not listed in the provided schema. "
            "You never use DML, DDL, or CALL statements."
        ),
        task=(
            f"Generate a Snowflake SQL query that answers this question: "
            f"{business_question}"
        ),
        context={
            "schema":        table_schema,
            "glossary":      business_glossary or {},
            "dialect_notes": [
                "Use CURRENT_DATE — not NOW() or GETDATE() or CURRENT_DATE()",
                "Date arithmetic: DATEADD('day', -7, CURRENT_DATE)",
                "Case-insensitive string compare: ILIKE, not LIKE",
                "Null-safe equality: IS NOT DISTINCT FROM, not =",
                "Array aggregation: ARRAY_AGG(DISTINCT col)",
            ]
        },
        output_format=(
            "JSON with keys: "
            "sql (string — a valid Snowflake SELECT with an inline comment explaining logic), "
            "explanation (string — max 2 sentences describing what the query returns), "
            "confidence (string — one of: high, medium, low), "
            "assumed_joins (array of strings — join conditions inferred from schema)"
        ),
        chain_of_thought=True,
    )

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=prompt.to_system_message(),
        messages=prompt.to_messages(),
    )
    return response.content[0].text


# ============================================================
# Column documentation with PTCF
# ============================================================

def build_column_description_prompt(
    table_name: str,
    column_name: str,
    data_type: str,
    table_context: str,
    sample_values: Optional[list] = None,
) -> DataEngineeringPrompt:
    """Build the PTCF prompt for a single column description."""
    context: dict = {
        "table":         table_name,
        "column":        column_name,
        "data_type":     data_type,
        "table_context": table_context,
    }
    if sample_values:
        context["sample_values"] = sample_values

    return DataEngineeringPrompt(
        persona=(
            "You are a data documentation specialist writing column descriptions "
            "for a dbt data catalog. "
            "Your audience is business analysts who can read SQL but are not "
            "familiar with the physical schema. "
            "You never include technical jargon or implementation details "
            "unless they are essential to understanding the column's meaning."
        ),
        task=(
            f"Write a one-sentence description for column '{column_name}' "
            f"in table '{table_name}'."
        ),
        context=context,
        output_format=(
            "A single sentence. "
            "No quotation marks. "
            "No trailing punctuation after the period. "
            "State what the column contains in business terms."
        ),
    )


# ============================================================
# Anomaly triage with PTCF
# ============================================================

from pydantic import BaseModel, Field
from enum import Enum


class AnomalyType(str, Enum):
    VOLUME_DROP      = "volume_drop"
    SCHEMA_CHANGE    = "schema_change"
    FRESHNESS_BREACH = "freshness_breach"
    QUALITY_FAILURE  = "quality_failure"
    LINEAGE_BREAK    = "lineage_break"
    UNKNOWN          = "unknown"


def build_triage_prompt(alert_payload: dict) -> DataEngineeringPrompt:
    """Build the PTCF prompt for anomaly classification."""
    return DataEngineeringPrompt(
        persona=(
            "You are a data reliability engineer triaging data pipeline alerts. "
            "You classify anomalies into canonical types to route them to the "
            "correct specialist handler. You never speculate beyond what the "
            "alert data supports. When uncertain, use anomaly_type=unknown and "
            "set confidence below 0.5."
        ),
        task=(
            "Classify this data pipeline alert into one of the canonical anomaly types "
            "and identify the primary signal supporting your classification."
        ),
        context={
            "alert":        alert_payload,
            "anomaly_types": {t.value: "" for t in AnomalyType},
            "classification_rules": [
                "volume_drop: row count or record volume fell below threshold",
                "schema_change: column added, removed, renamed, or type changed",
                "freshness_breach: data not updated within the expected window",
                "quality_failure: null rate, uniqueness, or referential integrity breach",
                "lineage_break: upstream table or model failed to produce output",
                "unknown: alert data is insufficient to classify confidently",
            ]
        },
        output_format=(
            "JSON with keys: "
            "anomaly_type (string — one of the canonical types), "
            "confidence (float 0.0–1.0), "
            "primary_signal (string — the data point that drove the classification), "
            "recommended_action (string)"
        ),
    )


if __name__ == "__main__":
    # Demo: generate SQL
    schema = {
        "table": "OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS",
        "columns": [
            {"name": "customer_id",  "type": "VARCHAR",       "description": "Surrogate key"},
            {"name": "active_since", "type": "TIMESTAMP_NTZ", "description": "First qualifying event timestamp"},
            {"name": "region_code",  "type": "VARCHAR",       "description": "ISO 3166-1 alpha-2 region"},
        ]
    }
    result = generate_safe_sql(
        "How many active customers are in each region as of today?",
        schema,
    )
    print(result)
