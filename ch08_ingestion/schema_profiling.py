import re
# Chapter 8: AI-Assisted Ingestion, Profiling, and Documentation
# Section: 8.1-8.2 Schema profiling and entity detection
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Dynamic SQL profiling and AI-powered entity detection.

Profile-before-ingest pattern:
  1. Dynamic profile query — one SQL pass captures null rates, cardinality,
     min/max for every column
  2. Baseline comparison — detect row-count drift and new columns on incremental loads
  3. Entity detection — LLM identifies what business object each row represents,
     which columns are FK references, and which columns contain PII
"""

import anthropic
import snowflake.connector
from pydantic import BaseModel, Field
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
import json

client = anthropic.Anthropic()


# --- Data models ---

@dataclass
class ColumnProfile:
    column_name:     str
    data_type:       str
    null_pct:        float
    approx_distinct: int
    min_val:         Optional[str]
    max_val:         Optional[str]


@dataclass
class ProfileAnomaly:
    column_name: str
    anomaly_type: str   # "high_null_rate" | "no_distinct" | "new_column"
    severity:     str   # "warning" | "blocking"
    detail:       str


class ColumnRole(str, Enum):
    IDENTIFIER  = "identifier"
    MEASURE     = "measure"
    DIMENSION   = "dimension"
    FLAG        = "flag"
    TIMESTAMP   = "timestamp"
    FREE_TEXT   = "free_text"
    FOREIGN_KEY = "foreign_key"
    UNKNOWN     = "unknown"


class PIIClass(str, Enum):
    NONE        = "none"
    DIRECT      = "direct"        # name, email, SSN, phone
    QUASI       = "quasi"         # DOB, ZIP, gender
    INDIRECT    = "indirect"      # job title, device ID if linkable
    CONFIRMED   = "confirmed"     # user-verified PII


@dataclass
class ColumnEntityInfo:
    column_name:    str
    role:           ColumnRole
    pii_class:      PIIClass = PIIClass.NONE
    likely_joins_to: Optional[str] = None


@dataclass
class TableEntityDetection:
    entity_type:   str        # e.g. "device_calibration_event"
    grain:         str        # e.g. "one row per calibration event per device"
    data_domain:   str        # e.g. "IoT operations"
    columns:       list[ColumnEntityInfo] = field(default_factory=list)
    classification_confidence: float = 0.0


# ============================================================
# Dynamic profile query
# ============================================================

def profile_table(
    conn: snowflake.connector.connection.SnowflakeConnection,
    table_fqn: str,
    columns: list[dict],
    sample_rows: int = 100000,
) -> list[ColumnProfile]:
    """
    Run a dynamic profiling SQL in a single pass over the table.
    Returns one ColumnProfile per column.
    """
    select_exprs = []
    for col in columns:
        name = col["column_name"]
        dtype = col["data_type"]
        safe_name = '"' + name.replace('"', '""') + '"'
        select_exprs += [
            f"ROUND(100.0 * COUNT_IF({safe_name} IS NULL) / COUNT(*), 2) AS null_pct_{name}",
            f"APPROX_COUNT_DISTINCT({safe_name}) AS distinct_{name}",
        ]
        # min/max for non-text columns
        if any(t in dtype.upper() for t in ["INT", "FLOAT", "NUMBER", "DATE", "TIMESTAMP"]):
            select_exprs.append(f"MIN({safe_name})::VARCHAR AS min_{name}")
            select_exprs.append(f"MAX({safe_name})::VARCHAR AS max_{name}")
        else:
            select_exprs.append(f"NULL AS min_{name}")
            select_exprs.append(f"NULL AS max_{name}")

    # Validate table_fqn before interpolation to prevent SQL injection
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*){0,2}$', table_fqn):
        raise ValueError(f"Invalid table FQN: {table_fqn!r}")
    sql = f"SELECT {', '.join(select_exprs)} FROM {table_fqn} SAMPLE ({sample_rows} ROWS)"

    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        desc = {d[0].lower(): i for i, d in enumerate(cur.description)}

    profiles = []
    for col in columns:
        name = col["column_name"]
        profiles.append(ColumnProfile(
            column_name=name,
            data_type=col["data_type"],
            null_pct=float(row[desc[f"null_pct_{name.lower()}"]]) if row else 0.0,
            approx_distinct=int(row[desc[f"distinct_{name.lower()}"]]) if row else 0,
            min_val=str(row[desc[f"min_{name.lower()}"]]) if row else None,
            max_val=str(row[desc[f"max_{name.lower()}"]]) if row else None,
        ))
    return profiles


def detect_profile_anomalies(
    profiles: list[ColumnProfile],
    null_warning_threshold: float = 0.05,
    null_blocking_threshold: float = 0.30,
) -> list[ProfileAnomaly]:
    """Flag columns with high null rates or zero distinct values."""
    anomalies = []
    for p in profiles:
        if p.null_pct >= null_blocking_threshold:
            anomalies.append(ProfileAnomaly(
                column_name=p.column_name,
                anomaly_type="high_null_rate",
                severity="blocking",
                detail=f"{p.null_pct:.1f}% null (threshold: {null_blocking_threshold*100:.0f}%)",
            ))
        elif p.null_pct >= null_warning_threshold:
            anomalies.append(ProfileAnomaly(
                column_name=p.column_name,
                anomaly_type="high_null_rate",
                severity="warning",
                detail=f"{p.null_pct:.1f}% null",
            ))
        if p.approx_distinct == 0 and p.null_pct < 1.0:
            anomalies.append(ProfileAnomaly(
                column_name=p.column_name,
                anomaly_type="no_distinct",
                severity="warning",
                detail="0 distinct values with non-null rows — possible constant column",
            ))
    return anomalies


# ============================================================
# AI entity detection
# ============================================================

class ColumnClassification(BaseModel):
    column_name:    str
    role:           str  # ColumnRole value
    pii:            bool
    pii_class:      str  # PIIClass value
    likely_joins_to: Optional[str] = None


class TableClassificationOutput(BaseModel):
    entity_type:           str
    grain:                 str
    data_domain:           str
    columns:               list[ColumnClassification]
    classification_confidence: float = Field(ge=0.0, le=1.0)


def detect_entities(
    table_name: str,
    columns: list[dict],
    sample_rows: list[dict] | None = None,
) -> TableEntityDetection:
    """
    Use an LLM to detect what business object each row represents,
    which columns are FK references, and which contain PII.
    """
    sample_str = ""
    if sample_rows:
        sample_str = f"\nSample rows (3 rows):\n{json.dumps(sample_rows[:3], indent=2)}"

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=800,
        system=(
            "You are an enterprise data architect performing entity detection. "
            "Analyze the table schema and sample rows to determine the entity type, "
            "grain, data domain, and classify each column."
        ),
        tools=[{
            "name": "classify_table",
            "description": "Return the table entity classification.",
            "input_schema": TableClassificationOutput.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "classify_table"},
        messages=[{"role": "user", "content": (
            f"Table: {table_name}\n"
            f"Columns: {json.dumps(columns, indent=2)}"
            f"{sample_str}"
        )}]
    )
    tool_call = next(b for b in response.content if b.type == "tool_use")
    output = TableClassificationOutput(**tool_call.input)

    return TableEntityDetection(
        entity_type=output.entity_type,
        grain=output.grain,
        data_domain=output.data_domain,
        columns=[
            ColumnEntityInfo(
                column_name=c.column_name,
                role=ColumnRole(c.role) if c.role in ColumnRole._value2member_map_ else ColumnRole.UNKNOWN,
                pii_class=PIIClass(c.pii_class) if c.pii_class in PIIClass._value2member_map_ else PIIClass.NONE,
                likely_joins_to=c.likely_joins_to,
            )
            for c in output.columns
        ],
        classification_confidence=output.classification_confidence,
    )


if __name__ == "__main__":
    # Demo entity detection without a live connection
    columns = [
        {"column_name": "device_id",        "data_type": "VARCHAR"},
        {"column_name": "calibration_date",  "data_type": "DATE"},
        {"column_name": "technician_id",     "data_type": "VARCHAR"},
        {"column_name": "passed",            "data_type": "BOOLEAN"},
        {"column_name": "offset_mm",         "data_type": "FLOAT"},
    ]
    result = detect_entities("calibration_events", columns)
    print(f"Entity type: {result.entity_type}")
    print(f"Grain: {result.grain}")
    print(f"Confidence: {result.classification_confidence}")
    for col in result.columns:
        pii_str = f" [PII: {col.pii_class.value}]" if col.pii_class != PIIClass.NONE else ""
        join_str = f" → {col.likely_joins_to}" if col.likely_joins_to else ""
        print(f"  {col.column_name}: {col.role.value}{pii_str}{join_str}")
