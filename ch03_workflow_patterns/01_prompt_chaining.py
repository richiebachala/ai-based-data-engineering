# Chapter 3: Workflows vs Agents for Data Engineering
# Section: 3.1 Five composable workflow patterns — Prompt Chaining
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Prompt chaining: sequential LLM calls where each step's output is the
next step's input. The code controls execution — there is no dynamic
tool selection. Use when each step has a predictable structure.

OpsPulse use case: column description generation pipeline
  Step 1: Extract column role from schema context (haiku, fast)
  Step 2: Generate one-sentence business description (haiku)
  Step 3: Validate description meets style rules (sonnet)
"""

import asyncio
import anthropic
from pydantic import BaseModel, Field

client = anthropic.Anthropic()


class ColumnDescription(BaseModel):
    column_name: str
    description: str
    role: str        # "identifier" | "measure" | "dimension" | "flag" | "timestamp"
    passed: bool
    feedback: str = ""


def step1_extract_column_role(
    table_name: str,
    column_name: str,
    data_type: str,
    sample_values: list | None = None,
) -> str:
    """Step 1: Determine the column's semantic role in the table."""
    sample_str = f"Sample values: {sample_values}" if sample_values else ""
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=100,
        system="Classify a data column's semantic role. Return one word only.",
        messages=[{
            "role": "user",
            "content": (
                f"Table: {table_name}\n"
                f"Column: {column_name} ({data_type})\n"
                f"{sample_str}\n\n"
                "Role (identifier / measure / dimension / flag / timestamp):"
            )
        }]
    )
    return response.content[0].text.strip().lower()


def step2_generate_description(
    table_name: str,
    column_name: str,
    data_type: str,
    role: str,
    sample_values: list | None = None,
) -> str:
    """Step 2: Generate a one-sentence business description."""
    sample_str = f"Sample values: {sample_values[:5]}" if sample_values else ""
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=150,
        system=(
            "Write one-sentence column descriptions for a data catalog. "
            "Audience: business analysts. No jargon. Under 150 chars."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Table: {table_name}\n"
                f"Column: {column_name} ({data_type}), role={role}\n"
                f"{sample_str}\n\n"
                "Write a one-sentence description in business terms."
            )
        }]
    )
    return response.content[0].text.strip()


def step3_validate_description(
    column_name: str,
    description: str,
) -> tuple[bool, str]:
    """Step 3: Validate the description meets catalog style rules."""
    issues = []
    # Rule 1: under 150 characters
    if len(description) > 150:
        issues.append(f"Too long: {len(description)} chars (max 150)")
    # Rule 2: does not restate the column name as the first word
    first_word = description.split()[0].lower().strip(".,;:") if description else ""
    if first_word == column_name.lower().replace("_", ""):
        issues.append("First word restates the column name")
    # Rule 3: starts with a capital letter
    if description and not description[0].isupper():
        issues.append("Does not start with a capital letter")
    passed = len(issues) == 0
    return passed, "; ".join(issues)


def generate_column_description_chain(
    table_name: str,
    column_name: str,
    data_type: str,
    sample_values: list | None = None,
) -> ColumnDescription:
    """Run the three-step prompt chain for a single column."""
    # Step 1: role extraction
    role = step1_extract_column_role(table_name, column_name, data_type, sample_values)

    # Step 2: description generation (uses step 1 output)
    description = step2_generate_description(
        table_name, column_name, data_type, role, sample_values
    )

    # Step 3: validation (uses step 2 output)
    passed, feedback = step3_validate_description(column_name, description)

    return ColumnDescription(
        column_name=column_name,
        description=description,
        role=role,
        passed=passed,
        feedback=feedback,
    )


async def _generate_async(
    table_name: str,
    col: dict,
) -> ColumnDescription:
    """Async wrapper for use with asyncio.gather in the parallelization pattern."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: generate_column_description_chain(
            table_name,
            col["column_name"],
            col["data_type"],
            col.get("sample_values"),
        )
    )


async def document_all_columns(
    table_name: str,
    columns: list[dict],
) -> list[ColumnDescription]:
    """
    Generate descriptions for all columns concurrently.
    This is the parallelization pattern (Chapter 3, Section 3.1)
    applied to column documentation.
    """
    tasks = [_generate_async(table_name, col) for col in columns]
    return await asyncio.gather(*tasks)


if __name__ == "__main__":
    # Example: document the FCT_ACTIVE_CUSTOMERS table
    columns = [
        {"column_name": "customer_id", "data_type": "VARCHAR",
         "sample_values": ["C001", "C002", "C003"]},
        {"column_name": "active_since", "data_type": "TIMESTAMP_NTZ",
         "sample_values": ["2025-01-15 08:30:00", "2025-02-01 12:00:00"]},
        {"column_name": "region_code", "data_type": "VARCHAR",
         "sample_values": ["US", "EMEA", "APAC"]},
    ]

    results = asyncio.run(document_all_columns("fct_active_customers", columns))
    for r in results:
        status = "✓" if r.passed else "✗"
        print(f"  {status} {r.column_name} ({r.role}): {r.description}")
        if not r.passed:
            print(f"    └ {r.feedback}")
