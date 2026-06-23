# Chapter 3: Workflows vs Agents for Data Engineering
# Section: 3.1 Five composable workflow patterns — Evaluator-Optimizer
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Evaluator-Optimizer: a generator LLM produces a first draft; a separate
evaluator LLM scores it against explicit criteria; if the score falls
below threshold, the generator reruns with the feedback appended.

Key design decisions:
  - Generator: haiku (cheap, fast) for first-pass drafts
  - Evaluator: sonnet (stronger judgment) for quality assessment
  - Loop terminates at threshold OR max_iterations
  - Best result is always tracked; returned even if iterations exhausted

OpsPulse use case: data quality check generation
"""

import anthropic
from pydantic import BaseModel, Field

client = anthropic.Anthropic()


class QualityCheckEvaluation(BaseModel):
    score:             float = Field(ge=0.0, le=1.0)
    passed:            bool
    feedback:          str
    dimension_scores:  dict[str, float] = Field(default_factory=dict)


GENERATOR_SYSTEM = """
You are a senior dbt data engineer generating SQL-based quality checks.
Write Snowflake SQL SELECT statements that return zero rows when the check passes,
or the failing rows when it fails (dbt test pattern).
Always add a comment explaining the check logic.
"""

EVALUATOR_SYSTEM = """
Evaluate a data quality check on four criteria:
1. Correctness — the SQL logic matches the stated rule exactly.
2. Completeness — the check catches the full failure surface, not just the obvious case.
3. Snowflake safety — no cross-database joins, no temp tables, no DML.
4. Explainability — a business analyst can understand what the check verifies.
Score 0.0-1.0 per dimension. Set passed=True only if all four ≥ 0.75 and overall ≥ 0.80.
"""


def generate_quality_check(
    client: anthropic.Anthropic,
    table_schema: dict,
    business_rules: list[str],
    feedback: str = "",
) -> str:
    """Generator step: produce a dbt SQL quality check."""
    feedback_block = ""
    if feedback:
        feedback_block = f"\n\nPrevious attempt was rejected. Reviewer feedback:\n{feedback}"

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        system=GENERATOR_SYSTEM,
        messages=[{"role": "user", "content": (
            f"Table schema: {table_schema}\n"
            f"Business rules to enforce:\n" +
            "\n".join(f"  - {r}" for r in business_rules) +
            feedback_block +
            "\n\nGenerate a dbt quality check SQL."
        )}]
    )
    return response.content[0].text.strip()


def evaluate_quality_check(
    client: anthropic.Anthropic,
    table_schema: dict,
    sql_check: str,
    business_rules: list[str],
    quality_threshold: float = 0.80,
) -> QualityCheckEvaluation:
    """Evaluator step: score the generated check against the four criteria."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        system=EVALUATOR_SYSTEM,
        tools=[{
            "name": "evaluate",
            "description": "Return a structured evaluation.",
            "input_schema": QualityCheckEvaluation.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "evaluate"},
        messages=[{"role": "user", "content": (
            f"Table schema: {table_schema}\n"
            f"Business rules:\n" +
            "\n".join(f"  - {r}" for r in business_rules) +
            f"\n\nSQL to evaluate:\n```sql\n{sql_check}\n```"
        )}]
    )
    tool_call = next(b for b in response.content if b.type == "tool_use")
    return QualityCheckEvaluation(**tool_call.input)


def evaluator_optimizer_loop(
    table_schema: dict,
    business_rules: list[str],
    quality_threshold: float = 0.80,
    max_iterations: int = 3,
) -> dict:
    """
    Evaluator-optimizer loop for data quality check generation.

    Returns:
        dict with keys:
          - output: best SQL check generated
          - iterations: number of iterations used
          - history: per-iteration scores and feedback
          - status: "passed" | "max_iterations_reached"
    """
    history = []
    feedback = ""

    for iteration in range(1, max_iterations + 1):
        output     = generate_quality_check(client, table_schema, business_rules, feedback)
        eval_result = evaluate_quality_check(client, table_schema, output, business_rules, quality_threshold)

        history.append({
            "iteration": iteration,
            "output":    output,
            "score":     eval_result.score,
            "passed":    eval_result.passed,
            "dimensions": eval_result.dimension_scores,
        })

        if eval_result.passed:
            return {"output": output, "iterations": iteration, "history": history, "status": "passed"}

        feedback = eval_result.feedback   # carry feedback into next generation

    # Max iterations reached without passing — return best result
    best = max(history, key=lambda x: x["score"])
    return {
        "output":         best["output"],
        "iterations":     max_iterations,
        "history":        history,
        "status":         "max_iterations_reached",
        "best_score":     best["score"],
    }


if __name__ == "__main__":
    schema = {
        "table": "OPSPU.MARTS.FCT_INVENTORY_EXPOSURE",
        "columns": [
            {"name": "product_id",     "type": "VARCHAR",  "nullable": False},
            {"name": "region_code",    "type": "VARCHAR",  "nullable": False},
            {"name": "exposure_amount","type": "NUMBER",   "nullable": True},
            {"name": "snapshot_date",  "type": "DATE",     "nullable": False},
            {"name": "threshold_pct",  "type": "FLOAT",    "nullable": True},
        ]
    }
    rules = [
        "exposure_amount must not be negative",
        "Every product_id must exist in dim_product_hierarchy",
        "snapshot_date must never be in the future",
    ]

    result = evaluator_optimizer_loop(schema, rules)
    print(f"Status: {result['status']} after {result['iterations']} iteration(s)")
    print(f"\nGenerated SQL check:\n{result['output']}")
