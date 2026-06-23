# Chapter 4: Prompting On-Ramp and Structured Prompting
# Section: 4.3 Structured outputs — OpenAI response_format pattern
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Structured outputs using the OpenAI response_format API.

Two equivalent approaches:
  A. client.beta.chat.completions.parse() — Pydantic model directly
  B. response_format={"type": "json_object"} — JSON mode

Approach A is preferred: it returns a typed Pydantic instance,
not a raw JSON string. No manual json.loads() needed.

OpenAI enforces the schema at the API level (Aug 2024 GA).
The model CANNOT produce output that violates the schema.
"""

from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Optional
import json

client = OpenAI()


# ============================================================
# Pydantic schemas
# ============================================================

class SQLGenerationOutput(BaseModel):
    """Structured output for SQL generation (OpenAI variant)."""
    sql:           str  = Field(description="Valid Snowflake SELECT query")
    explanation:   str  = Field(description="Max 2-sentence description")
    confidence:    str  = Field(description="high | medium | low")
    assumed_joins: list[str] = Field(default_factory=list)


class AnomalyClassification(BaseModel):
    """Structured output for anomaly triage (OpenAI variant)."""
    anomaly_type:       str   = Field(
        description="volume_drop | schema_change | freshness_breach | "
                    "quality_failure | lineage_break | unknown"
    )
    confidence:         float = Field(ge=0.0, le=1.0)
    primary_signal:     str
    recommended_action: str


# ============================================================
# Approach A: beta.chat.completions.parse() with Pydantic model
# ============================================================

def generate_sql_openai_structured(
    business_question: str,
    table_schema: dict,
) -> SQLGenerationOutput:
    """
    Generate SQL using OpenAI structured outputs (Approach A).

    Returns a typed SQLGenerationOutput instance — no json.loads() needed.
    """
    completion = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a senior Snowflake data engineer. "
                    "Write read-only SELECT queries in Snowflake SQL dialect. "
                    "Never reference tables not in the provided schema."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Business question: {business_question}\n"
                    f"Schema: {json.dumps(table_schema)}"
                )
            }
        ],
        response_format=SQLGenerationOutput,   # Pydantic model → OpenAI enforces schema
        max_tokens=1024,
    )
    # .parsed returns a typed SQLGenerationOutput instance
    return completion.choices[0].message.parsed


# ============================================================
# Approach B: JSON mode (response_format={"type": "json_object"})
# ============================================================

def classify_alert_json_mode(
    alert_payload: dict,
) -> AnomalyClassification:
    """
    Classify an alert using OpenAI JSON mode (Approach B).

    JSON mode guarantees valid JSON but does NOT enforce a specific schema.
    Parse manually into the Pydantic model after the call.
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify data pipeline alerts. Never speculate beyond the alert data. "
                    "Return JSON with keys: anomaly_type, confidence, primary_signal, recommended_action."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Alert: {json.dumps(alert_payload)}\n"
                    "Types: volume_drop | schema_change | freshness_breach | "
                    "quality_failure | lineage_break | unknown"
                )
            }
        ],
        response_format={"type": "json_object"},
        max_tokens=300,
    )
    raw = json.loads(response.choices[0].message.content)
    return AnomalyClassification(**raw)


# ============================================================
# Prompt caching: OpenAI (automatic for prompts > 1024 tokens)
# ============================================================

def generate_sql_openai_cached(
    schema_preamble: str,    # stable across calls — will be cached
    business_question: str,  # dynamic — changes per call
) -> dict:
    """
    Generate SQL with OpenAI prompt caching (automatic, no opt-in needed).

    For caching to work:
      1. The stable portion (system prompt + schema preamble) must appear first
      2. The dynamic portion (user question) must appear last
      3. The total prompt must exceed 1,024 tokens

    OpenAI caches at a 50% discount on cached input tokens.
    """
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": schema_preamble   # stable — cached after first use
            },
            {
                "role": "user",
                "content": (
                    f"Business question: {business_question}\n\n"
                    "Return JSON: {sql, explanation, confidence}"
                )
            }
        ],
        max_tokens=1024,
        response_format={"type": "json_object"},
    )
    usage     = response.usage
    cached_in = getattr(usage, "prompt_tokens_details", {})
    return {
        "output":        response.choices[0].message.content,
        "tokens_total":  usage.total_tokens,
        "tokens_cached": getattr(cached_in, "cached_tokens", 0),
    }


if __name__ == "__main__":
    schema = {
        "table": "OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS",
        "columns": [{"name": "customer_id"}, {"name": "region_code"}, {"name": "active_since"}]
    }
    result = generate_sql_openai_structured(
        "Count active customers per region",
        schema,
    )
    print(f"SQL: {result.sql}")
    print(f"Confidence: {result.confidence}")
