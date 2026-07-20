# Chapter 9: Generate and Verify Transformations (SQL/dbt)
# Section: 9.4 dbt test generation from column profiles
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Generate dbt tests from column profiles and entity detection.

Test generation rules:
  - Identifiers with 0% null rate → not_null + unique
  - Low-cardinality dimensions (< 20 distinct) → accepted_values
  - Columns with likely FK relationship → relationships test
  - Flags (BOOLEAN or binary VARCHAR) → accepted_values [True/False]

This eliminates most test-writing effort: the engineer validates and adjusts,
the pipeline writes the first draft.
"""

import anthropic
from pydantic import BaseModel, Field
from typing import Optional
import json
import re

client = anthropic.Anthropic()


# ============================================================
# Data models for dbt test spec
# ============================================================

class DbtTest(BaseModel):
    test_type:  str           # "not_null" | "unique" | "accepted_values" | "relationships"
    column:     str
    options:    dict = Field(default_factory=dict)
    comment:    str = ""


class DbtTestSuite(BaseModel):
    model_name: str
    tests:      list[DbtTest]
    yaml_block: str = ""


# ============================================================
# Rule-based test generation from profiles
# ============================================================

def generate_dbt_tests(
    model_name: str,
    profiles: list,     # list of ColumnProfile from ch08_ingestion/schema_profiling.py
    entity_detection,   # TableEntityDetection from schema_profiling.py
    sample_values: dict[str, list] | None = None,
) -> DbtTestSuite:
    """
    Generate dbt test specs from column profiles and entity detection.
    Rule-based: no LLM call needed for the standard cases.
    """
    tests: list[DbtTest] = []

    for profile in profiles:
        col = profile.column_name
        dtype = profile.data_type.upper()

        # Find entity info for this column
        col_entity = next(
            (c for c in entity_detection.columns if c.column_name == col),
            None,
        )
        role = col_entity.role.value if col_entity else "unknown"
        fk_target = col_entity.likely_joins_to if col_entity else None

        # Rule 1: zero-null identifiers → not_null + unique
        if profile.null_pct == 0.0 and role in ("identifier", "foreign_key"):
            tests.append(DbtTest(
                test_type="not_null",
                column=col,
                comment=f"Identifier column; 0% null in profile",
            ))
            if role == "identifier":
                tests.append(DbtTest(
                    test_type="unique",
                    column=col,
                    comment=f"Identifier column; high-cardinality in profile",
                ))

        # Rule 2: FK columns → relationships test
        if fk_target and role == "foreign_key":
            ref_table, ref_col = fk_target.split(".") if "." in fk_target else (fk_target, col)
            tests.append(DbtTest(
                test_type="relationships",
                column=col,
                options={
                    "to": f"ref('{ref_table.lower()}')",
                    "field": ref_col,
                },
                comment=f"FK detected in entity classification",
            ))

        # Rule 3: low-cardinality dimensions → accepted_values
        if profile.approx_distinct <= 20 and role == "dimension":
            if sample_values and col in sample_values:
                values = sorted(set(str(v) for v in sample_values[col] if v is not None))
                tests.append(DbtTest(
                    test_type="accepted_values",
                    column=col,
                    options={"values": values},
                    comment=f"Low-cardinality dimension ({profile.approx_distinct} distinct values)",
                ))

        # Rule 4: BOOLEAN columns → accepted_values [true, false]
        if "BOOL" in dtype or role == "flag":
            tests.append(DbtTest(
                test_type="accepted_values",
                column=col,
                options={"values": [True, False]},
                comment=f"Boolean/flag column",
            ))

        # Rule 5: non-null timestamps (event time should never be null)
        if "TIMESTAMP" in dtype and "_at" in col.lower():
            tests.append(DbtTest(
                test_type="not_null",
                column=col,
                comment=f"Event timestamp; should never be null",
            ))

    # Build YAML block
    yaml_block = _tests_to_yaml(model_name, tests)
    return DbtTestSuite(model_name=model_name, tests=tests, yaml_block=yaml_block)


def _tests_to_yaml(model_name: str, tests: list[DbtTest]) -> str:
    """Convert test specs to dbt schema.yml YAML format."""
    # Group tests by column
    by_col: dict[str, list[DbtTest]] = {}
    for t in tests:
        by_col.setdefault(t.column, []).append(t)

    lines = [
        "models:",
        f"  - name: {model_name}",
        "    columns:",
    ]
    for col, col_tests in by_col.items():
        lines.append(f"      - name: {col}")
        lines.append(f"        data_tests:  # dbt v1.5+; use 'tests:' for v1.4 and earlier")
        for t in col_tests:
            if t.options:
                lines.append(f"          - {t.test_type}:")
                for k, v in t.options.items():
                    val_str = json.dumps(v) if not isinstance(v, str) else f"\n              - {chr(10).join(v)}"
                    lines.append(f"              {k}: {v}")
            else:
                lines.append(f"          - {t.test_type}")

    return "\n".join(lines)


# ============================================================
# LLM-augmented test generation for complex rules
# ============================================================

def generate_complex_tests(
    model_name: str,
    business_rules: list[str],
    table_schema: dict,
) -> list[str]:
    """
    Generate custom singular test SQL for business rules that
    the rule-based approach cannot handle.

    Returns a list of SQL strings (each should return 0 rows on pass).
    """
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        system=(
            "You are a dbt data quality engineer. Write SQL tests that return "
            "ZERO rows when the test passes (dbt singular test pattern). "
            "Use Snowflake SQL syntax."
        ),
        messages=[{"role": "user", "content": (
            f"Model: {model_name}\n"
            f"Schema: {json.dumps(table_schema, indent=2)}\n"
            f"Business rules to test:\n" +
            "\n".join(f"  {i+1}. {r}" for i, r in enumerate(business_rules)) +
            "\n\nGenerate one SQL test per rule. Return as JSON array of SQL strings."
        )}]
    )
    try:
        return json.loads(response.content[0].text)
    except json.JSONDecodeError:
        # Extract SQL blocks if JSON parsing fails
        blocks = re.findall(r'```sql\n(.*?)\n```', response.content[0].text, re.DOTALL)
        return blocks




if __name__ == "__main__":
    # Demo: generate tests for a fake profile
    from dataclasses import dataclass
    from enum import Enum

    class FakeRole(str, Enum):
        IDENTIFIER = "identifier"
        DIMENSION  = "dimension"
        FLAG       = "flag"

    @dataclass
    class FakeProfile:
        column_name: str
        data_type:   str
        null_pct:    float
        approx_distinct: int
        min_val = None
        max_val = None

    @dataclass
    class FakeColEntity:
        column_name:    str
        role:           FakeRole
        pii_class:      type = None
        likely_joins_to: str = None

    @dataclass
    class FakeDetection:
        entity_type = "test"
        grain = "one row per device"
        data_domain = "IoT"
        columns: list = None

    profiles = [
        FakeProfile("device_id",   "VARCHAR",  0.0, 10000),
        FakeProfile("region_code", "VARCHAR",  0.0, 5),
        FakeProfile("passed",      "BOOLEAN",  0.0, 2),
    ]
    entity = FakeDetection()
    entity.columns = [
        FakeColEntity("device_id",   FakeRole.IDENTIFIER),
        FakeColEntity("region_code", FakeRole.DIMENSION),
        FakeColEntity("passed",      FakeRole.FLAG),
    ]

    suite = generate_dbt_tests("device_calibration", profiles, entity,
                               sample_values={"region_code": ["US", "EMEA", "APAC"]})
    print(f"Generated {len(suite.tests)} tests:")
    print(suite.yaml_block)
