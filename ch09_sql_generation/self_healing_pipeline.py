# Chapter 9: Generate and Verify Transformations (SQL/dbt)
# Section: 9.1-9.3 SQL complexity assessment, guardrails, self-healing pipeline
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Self-healing SQL generation pipeline.

Three-layer pipeline:
  1. Complexity assessment — haiku classifies SQL tier to pick the right model
  2. Generation — tier-appropriate model generates SQL
  3. Validation stack — structural guardrails + anti-pattern checks + plausibility eval
  4. Repair loop — failed validation → feedback → regenerate

The evaluator-optimizer from Chapter 3 now applied at the SQL layer.
Key addition: business rules input for plausibility checking.
"""

import anthropic
import re
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field

client = anthropic.Anthropic()


# ============================================================
# Complexity tiers
# ============================================================

class SQLComplexityTier(str, Enum):
    TIER1 = "tier1"   # simple filters + aggregation → haiku
    TIER2 = "tier2"   # CTEs + window functions → sonnet
    TIER3 = "tier3"   # multi-hop joins + interacting conditions → extended thinking


class ComplexityAssessment(BaseModel):
    tier:          SQLComplexityTier
    reasoning:     str
    key_challenges: list[str] = Field(default_factory=list)


def assess_sql_complexity(
    business_requirement: str,
    available_tables: list[dict],
) -> ComplexityAssessment:
    """
    Classify the SQL complexity tier using a cheap haiku call.
    This one call saves 10-100x cost on the generation call by picking
    the right model tier upfront.
    """
    response = client.messages.create(
        model="claude-haiku-4-5",   # cheap: this is just a classification
        max_tokens=300,
        system=(
            "Classify the SQL complexity of a business requirement into one of three tiers.\n"
            "tier1: simple SELECT with filters and aggregation, no CTEs\n"
            "tier2: 1-3 CTEs, window functions, multi-table joins\n"
            "tier3: 4+ CTEs, self-joins, interacting conditions requiring multi-step deliberation"
        ),
        tools=[{
            "name": "assess",
            "description": "Return the complexity assessment.",
            "input_schema": ComplexityAssessment.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "assess"},
        messages=[{"role": "user", "content": (
            f"Requirement: {business_requirement}\n"
            f"Available tables: {[t.get('name', t) for t in available_tables]}"
        )}]
    )
    tool_call = next(b for b in response.content if b.type == "tool_use")
    return ComplexityAssessment(**tool_call.input)


# ============================================================
# Guardrail stack
# ============================================================

@dataclass
class GuardrailViolation:
    rule:     str
    severity: str   # "error" | "warning"
    detail:   str


@dataclass
class GuardrailResult:
    passed:    bool
    violations: list[GuardrailViolation] = field(default_factory=list)


BLOCKED_KEYWORDS = re.compile(
    r'\b(DELETE|INSERT|UPDATE|MERGE|CREATE|ALTER|DROP|TRUNCATE|CALL|EXECUTE)\b',
    re.IGNORECASE
)

CARTESIAN_PATTERN = re.compile(
    r'\bCROSS\s+JOIN\b|\bFROM\s+\w+,\s*\w+\b',
    re.IGNORECASE
)


def check_structural_guardrails(
    sql: str,
    allowed_tables: set[str],
) -> GuardrailResult:
    """
    Layer 1: Structural checks that block before generation.
    All failures here are hard errors that prevent execution.
    """
    violations = []

    # No DML
    match = BLOCKED_KEYWORDS.search(sql)
    if match:
        violations.append(GuardrailViolation(
            rule="no_dml",
            severity="error",
            detail=f"Blocked keyword: {match.group(0)}",
        ))

    # No semicolons (multi-statement prevention)
    if sql.count(";") > 0:
        violations.append(GuardrailViolation(
            rule="no_semicolons",
            severity="error",
            detail="Multi-statement queries are not allowed",
        ))

    # All tables must be in the allowed set
    table_refs = re.findall(r'\bFROM\s+(\w+)|\bJOIN\s+(\w+)', sql, re.IGNORECASE)
    for refs in table_refs:
        for ref in refs:
            if ref and ref.upper() not in {t.upper() for t in allowed_tables}:
                violations.append(GuardrailViolation(
                    rule="table_allowlist",
                    severity="error",
                    detail=f"Table '{ref}' is not in the allowed set: {sorted(allowed_tables)}",
                ))

    # No cartesian joins
    if CARTESIAN_PATTERN.search(sql):
        violations.append(GuardrailViolation(
            rule="no_cartesian",
            severity="error",
            detail="Cartesian or implicit CROSS JOIN detected",
        ))

    return GuardrailResult(
        passed=len([v for v in violations if v.severity == "error"]) == 0,
        violations=violations,
    )


def check_anti_patterns(sql: str) -> GuardrailResult:
    """
    Layer 2: Anti-pattern checks that warn about correctness risks.
    These do not block execution but are fed back to the generator.
    """
    violations = []

    # NULL equality comparison (NULL = NULL is always false)
    if re.search(r'\=\s*NULL\b', sql, re.IGNORECASE):
        violations.append(GuardrailViolation(
            rule="null_equality",
            severity="warning",
            detail="Use IS NULL instead of = NULL",
        ))

    # Integer division (may truncate unexpectedly)
    if re.search(r'\b\d+\s*/\s*\d+\b', sql):
        violations.append(GuardrailViolation(
            rule="integer_division",
            severity="warning",
            detail="Integer division truncates; cast to FLOAT: x::FLOAT / y",
        ))

    # UNION without ALL (deduplication is usually unintentional and expensive)
    if re.search(r'\bUNION\s+(?!ALL)', sql, re.IGNORECASE):
        violations.append(GuardrailViolation(
            rule="union_without_all",
            severity="warning",
            detail="UNION deduplicates; use UNION ALL unless deduplication is intentional",
        ))

    return GuardrailResult(
        passed=len([v for v in violations if v.severity == "error"]) == 0,
        violations=violations,
    )


# ============================================================
# Plausibility evaluator
# ============================================================

class SQLEvaluation(BaseModel):
    overall_score:  float = Field(ge=0.0, le=1.0)
    passed:         bool
    feedback:       str
    dimension_scores: dict[str, float] = Field(default_factory=dict)


def evaluate_sql_plausibility(
    sql: str,
    business_requirement: str,
    business_rules: list[str],
    table_schemas: dict[str, list[dict]],
) -> SQLEvaluation:
    """LLM-as-judge plausibility check against business rules."""
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        system=(
            "You are a data engineer evaluating generated SQL for correctness. "
            "Score on: (1) semantic correctness vs requirement, (2) business rule compliance, "
            "(3) join correctness, (4) filter completeness. "
            "Set passed=True only if all dimensions >= 0.75 and overall >= 0.80."
        ),
        tools=[{
            "name": "evaluate",
            "description": "Return the SQL evaluation.",
            "input_schema": SQLEvaluation.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "evaluate"},
        messages=[{"role": "user", "content": (
            f"Business requirement: {business_requirement}\n"
            f"Business rules:\n" + "\n".join(f"  - {r}" for r in business_rules) +
            f"\n\nTable schemas: {table_schemas}\n\nSQL to evaluate:\n```sql\n{sql}\n```"
        )}]
    )
    tool_call = next(b for b in response.content if b.type == "tool_use")
    return SQLEvaluation(**tool_call.input)


# ============================================================
# Self-healing pipeline
# ============================================================

@dataclass
class SelfHealingResult:
    status:            str   # "passed" | "max_iterations_reached" | "blocked"
    final_sql:         str
    final_score:       float
    iterations:        int
    iteration_history: list[dict] = field(default_factory=list)


def _generate_sql(
    business_requirement: str,
    table_schemas: dict,
    business_rules: list[str],
    complexity_tier: str,
    feedback: str = "",
) -> str:
    """Generate SQL using the tier-appropriate model."""
    model_map = {
        "tier1": "claude-haiku-4-5",
        "tier2": "claude-sonnet-4-5",
        "tier3": "claude-sonnet-4-5",   # use extended thinking in production
    }
    model = model_map.get(complexity_tier, "claude-sonnet-4-5")

    feedback_block = f"\n\nPrevious attempt feedback:\n{feedback}" if feedback else ""

    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=(
            "You are a senior Snowflake data engineer. Write read-only SELECT queries. "
            "Use CTEs for clarity. Use CURRENT_DATE for date references. No DML."
        ),
        messages=[{"role": "user", "content": (
            f"Business requirement: {business_requirement}\n"
            f"Business rules to enforce:\n" +
            "\n".join(f"  - {r}" for r in business_rules) +
            f"\n\nAvailable table schemas: {table_schemas}"
            f"{feedback_block}"
            "\n\nGenerate the SQL query."
        )}]
    )
    return response.content[0].text.strip()


def self_healing_sql_pipeline(
    business_requirement: str,
    business_rules: list[str],
    table_schemas: dict[str, list[dict]],
    allowed_tables: set[str] | None = None,
    complexity_tier: str | None = None,
    max_iterations: int = 3,
) -> SelfHealingResult:
    """
    Full self-healing SQL generation pipeline.

    1. Assess complexity (if not provided)
    2. Generate SQL
    3. Structural guardrails → hard block on errors
    4. Anti-pattern check → warnings as feedback
    5. Plausibility eval → score + feedback
    6. If not passing: regenerate with combined feedback
    """
    if allowed_tables is None:
        allowed_tables = set(table_schemas.keys())

    if complexity_tier is None:
        assessment = assess_sql_complexity(
            business_requirement,
            [{"name": t} for t in table_schemas.keys()],
        )
        complexity_tier = assessment.tier.value

    history = []
    best    = {"sql": "", "score": 0.0}
    feedback = ""

    for iteration in range(1, max_iterations + 1):
        sql = _generate_sql(
            business_requirement, table_schemas, business_rules, complexity_tier, feedback
        )

        # Layer 1: structural guardrails
        guardrail_result = check_structural_guardrails(sql, allowed_tables)
        if not guardrail_result.passed:
            errors = [v.detail for v in guardrail_result.violations if v.severity == "error"]
            feedback = f"Structural errors (fix before retrying): {'; '.join(errors)}"
            history.append({"iteration": iteration, "status": "guardrail_error",
                           "score": 0.0, "feedback": feedback})
            continue

        # Layer 2: anti-pattern check
        anti_pattern_result = check_anti_patterns(sql)
        anti_pattern_feedback = (
            "Anti-patterns detected (fix): " +
            "; ".join(v.detail for v in anti_pattern_result.violations)
        ) if anti_pattern_result.violations else ""

        # Layer 3: plausibility eval
        eval_result = evaluate_sql_plausibility(
            sql, business_requirement, business_rules, table_schemas
        )

        combined_feedback_parts = []
        if anti_pattern_feedback:
            combined_feedback_parts.append(anti_pattern_feedback)
        if not eval_result.passed:
            combined_feedback_parts.append(eval_result.feedback)

        history.append({
            "iteration": iteration,
            "status":    "passed" if eval_result.passed and not anti_pattern_result.violations else "failed",
            "score":     eval_result.overall_score,
            "feedback":  "\n".join(combined_feedback_parts),
        })

        if eval_result.overall_score > best["score"]:
            best = {"sql": sql, "score": eval_result.overall_score}

        if eval_result.passed and not any(v.severity == "error" for v in anti_pattern_result.violations):
            return SelfHealingResult(
                status="passed",
                final_sql=sql,
                final_score=eval_result.overall_score,
                iterations=iteration,
                iteration_history=history,
            )

        feedback = "\n".join(combined_feedback_parts)

    return SelfHealingResult(
        status="max_iterations_reached",
        final_sql=best["sql"],
        final_score=best["score"],
        iterations=max_iterations,
        iteration_history=history,
    )


if __name__ == "__main__":
    schemas = {
        "OPSPU.MARTS.FCT_DEVICE_ANOMALIES": [
            {"name": "device_id",    "type": "VARCHAR"},
            {"name": "event_date",   "type": "DATE"},
            {"name": "anomaly_type", "type": "VARCHAR"},
            {"name": "region_code",  "type": "VARCHAR"},
            {"name": "severity",     "type": "VARCHAR"},
        ]
    }
    rules = [
        "Only include anomalies where severity IN ('critical', 'high')",
        "Use CURRENT_DATE for date references, not hardcoded dates",
        "Return counts grouped by region_code and anomaly_type",
    ]
    result = self_healing_sql_pipeline(
        business_requirement="Count high-severity device anomalies by region and type for this month",
        business_rules=rules,
        table_schemas=schemas,
        allowed_tables=set(schemas.keys()),
    )
    print(f"Status: {result.status}  Score: {result.final_score:.2f}  Iterations: {result.iterations}")
    print(f"\nFinal SQL:\n{result.final_sql}")
