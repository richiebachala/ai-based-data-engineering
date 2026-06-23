# Chapter 8: AI-Assisted Ingestion, Profiling, and Documentation
# Section: 8.5 Documentation as a byproduct of ingestion
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Documentation-as-byproduct pipeline:

  1. Profile  — SQL profile query → ColumnProfile[] + anomaly report
  2. Classify — LLM entity detection → TableEntityDetection
  3. Document — evaluator-optimizer loop → column descriptions
  4. Apply    — ALTER TABLE MODIFY COLUMN COMMENT
  5. Lineage  — OpenLineage RunEvent → Marquez / Atlas

Elapsed time from staged file to documented table:
  4 minutes pipeline runtime, 10 minutes engineer review.
  Manual equivalent: 2-3 hours.
"""

import anthropic
import snowflake.connector
from openlineage.client import OpenLineageClient
from openlineage.client.run import RunEvent, RunState, Run, Job, Dataset
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional
import uuid

from schema_profiling import (
    ColumnProfile, TableEntityDetection, ColumnRole, PIIClass,
    profile_table, detect_profile_anomalies, detect_entities,
)

client = anthropic.Anthropic()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# Step 3: Evaluator-optimizer loop for column descriptions
# ============================================================

GENERATOR_PROMPT = (
    "Write a one-sentence column description: state the business meaning, "
    "units or format where relevant, and key value constraints. "
    "Under 150 characters. No jargon. Do not restate the column name."
)
EVALUATOR_PROMPT = (
    "Evaluate this column description on three criteria:\n"
    "1. Business meaning — conveys what the data means beyond the column name.\n"
    "2. Jargon-free — a business analyst understands it without engineering context.\n"
    "3. Under 150 characters — fits a Snowflake COMMENT field without truncation.\n"
    "Score 0.0–1.0. Set passed=True only if all three hold. Give specific, actionable feedback."
)


class DescriptionEvaluation(BaseModel):
    score:    float = Field(ge=0.0, le=1.0)
    passed:   bool
    feedback: str


def evaluate_description_loop(
    column_name:   str,
    col_context:   str,
    threshold:     float = 0.85,
    max_iterations: int = 3,
) -> tuple[str, DescriptionEvaluation]:
    """Evaluator-optimizer loop for column descriptions. Returns best result seen."""
    best_desc = ""
    best_eval = DescriptionEvaluation(score=0.0, passed=False, feedback="")
    feedback  = ""

    for _ in range(max_iterations):
        user_msg = f"Column: {column_name}\n{col_context}"
        if feedback:
            user_msg += f"\n\nPrevious draft rejected. Reviewer feedback: {feedback}"

        # Generator: haiku for speed and lower cost per column
        gen = client.messages.create(
            model="claude-haiku-4-5", max_tokens=160, system=GENERATOR_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        desc = gen.content[0].text.strip()

        # Evaluator: sonnet for better judgment on nuanced criteria
        ev = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=256, system=EVALUATOR_PROMPT,
            tools=[{"name": "evaluate", "description": "Return evaluation for a column description.",
                    "input_schema": DescriptionEvaluation.model_json_schema()}],
            tool_choice={"type": "tool", "name": "evaluate"},
            messages=[{"role": "user", "content": f"Column: {column_name}\nDescription: {desc}"}],
        )
        tool   = next(b for b in ev.content if b.type == "tool_use")
        result = DescriptionEvaluation(**tool.input)

        if result.score > best_eval.score:
            best_desc, best_eval = desc, result
        if result.passed or result.score >= threshold:
            return best_desc, best_eval
        feedback = result.feedback

    return best_desc, best_eval


# ============================================================
# Full documentation-as-byproduct pipeline
# ============================================================

def run_documentation_pipeline(
    conn: snowflake.connector.connection.SnowflakeConnection,
    table_fqn: str,
    stage_location: str,
    run_id: Optional[str] = None,
) -> dict:
    """
    Full documentation-as-byproduct pipeline for a newly ingested table.
    Returns a report of all actions taken.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    db, schema, table = table_fqn.upper().split(".")

    # Step 1: Profile
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, table))
        columns = [{"column_name": r[0], "data_type": r[1]} for r in cur.fetchall()]

    profiles  = profile_table(conn, table_fqn, columns)
    anomalies = detect_profile_anomalies(profiles)

    # Step 2: Classify
    sample_rows = _fetch_sample_rows(conn, table_fqn, limit=5)
    entity_det  = detect_entities(table, columns, sample_rows)

    # Step 3: Generate descriptions via evaluator-optimizer loop
    descriptions: dict[str, str] = {}
    for profile in profiles:
        col_context = (
            f"Type: {profile.data_type}\n"
            f"Null rate: {profile.null_pct}%  Distinct: {profile.approx_distinct:,}\n"
            f"Table: {table} ({entity_det.grain})"
        )
        desc, _ = evaluate_description_loop(profile.column_name, col_context)
        descriptions[profile.column_name] = desc

    # Step 4: Apply column comments
    applied_comments: list[str] = []
    for col_name, description in descriptions.items():
        safe_desc = description.replace("'", "''")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"ALTER TABLE {table_fqn} MODIFY COLUMN {col_name} COMMENT '{safe_desc}'"
                )
            applied_comments.append(col_name)
        except Exception as e:
            print(f"  Warning: could not apply comment to {col_name}: {e}")

    # Apply table-level comment
    table_comment = (
        f"{entity_det.entity_type}. {entity_det.grain}. "
        f"Data domain: {entity_det.data_domain}."
    ).replace("'", "''")
    with conn.cursor() as cur:
        cur.execute(f"ALTER TABLE {table_fqn} SET COMMENT = '{table_comment}'")

    # Step 5: Emit OpenLineage event
    ol_client = OpenLineageClient.from_environment()
    ol_client.emit(RunEvent(
        eventType=RunState.COMPLETE,
        eventTime=_utc_now_iso(),
        run=Run(runId=run_id),
        job=Job(namespace="opspu", name=f"ingest.{schema.lower()}.{table.lower()}"),
        inputs=[Dataset(namespace=f"file://{stage_location}", name=table.lower())],
        outputs=[Dataset(namespace=f"snowflake://opspu/{schema.lower()}", name=table.lower())],
    ))

    # Generate dbt YAML block
    dbt_yaml = _generate_dbt_yaml_block(table.lower(), entity_det, descriptions)

    return {
        "table":              table_fqn,
        "profile_anomalies": len(anomalies),
        "columns_documented": len(applied_comments),
        "lineage_emitted":   True,
        "dbt_yaml":          dbt_yaml,
        "anomaly_details":   [{"column": a.column_name, "type": a.anomaly_type,
                               "severity": a.severity} for a in anomalies],
    }


def _fetch_sample_rows(
    conn: snowflake.connector.connection.SnowflakeConnection,
    table_fqn: str,
    limit: int = 5,
) -> list[dict]:
    """Fetch representative sample rows for entity detection context."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table_fqn} LIMIT %s", (limit,))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def _generate_dbt_yaml_block(
    model_name: str,
    entity_det: TableEntityDetection,
    descriptions: dict[str, str],
) -> str:
    """Generate the schema.yml column descriptions block for this table."""
    lines = [
        f"  - name: {model_name}",
        f"    description: >",
        f"      {entity_det.entity_type}. {entity_det.grain}.",
        f"    columns:",
    ]
    for col_class in entity_det.columns:
        desc = descriptions.get(col_class.column_name, "")
        pii_tag = (
            f"\n        meta:\n          pii: true"
            if col_class.pii_class != PIIClass.NONE else ""
        )
        lines += [
            f"      - name: {col_class.column_name}",
            f"        description: >",
            f"          {desc}{pii_tag}",
        ]
    return "\n".join(lines)
