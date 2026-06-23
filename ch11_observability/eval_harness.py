# Chapter 11: Evals and AI Observability in Production
# Section: 11.1-11.4 Eval harness, tracing, drift detection, cost governance
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Eval harness and observability for production AI pipelines.

Two layers:
  Offline evals: run in CI against golden datasets; block deployment on score drops
  Online monitoring: track score distributions in production; alert on drift

Eval frameworks:
  - RAGAs:      retrieval quality (faithfulness, precision, recall, relevancy)
  - DeepEval:   structured output quality (custom GEval criteria)
  - PromptFoo:  regression suites in CI (see ch04_structured_prompting/promptfoo/)
  - Braintrust: score history across model versions

Bug fixes applied:
  C11-1: _send_budget_alert() and _utc_now_iso() are defined (not just referenced)
"""

import anthropic
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum
import json

client = anthropic.Anthropic()


# ============================================================
# Bug fix C11-1: define helper stubs
# ============================================================

def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _send_budget_alert(message: str) -> None:
    """
    Send a budget alert to the data engineering team channel.
    Replace with your notification provider (Slack, PagerDuty, etc.).
    """
    print(f"[BUDGET ALERT] {message}")
    # In production: post to Slack webhook


# ============================================================
# Eval data models
# ============================================================

class EvalDimension(str, Enum):
    FAITHFULNESS   = "faithfulness"    # answer grounded in context
    PRECISION      = "precision"       # context is relevant
    RECALL         = "recall"          # relevant context retrieved
    RELEVANCY      = "relevancy"       # answer relevant to question
    CORRECTNESS    = "correctness"     # answer matches ground truth
    COMPLETENESS   = "completeness"    # all required fields present


@dataclass
class EvalCase:
    """One evaluation test case."""
    case_id:        str
    question:       str
    expected_answer: Optional[str]
    context:        str
    metadata:       dict = field(default_factory=dict)


@dataclass
class EvalResult:
    case_id:     str
    overall:     float
    dimensions:  dict[str, float]
    passed:      bool
    notes:       str = ""


# ============================================================
# LLM-as-judge evaluator
# ============================================================

class JudgeScores(BaseModel):
    faithfulness:  float = Field(ge=0.0, le=1.0)
    relevancy:     float = Field(ge=0.0, le=1.0)
    correctness:   float = Field(ge=0.0, le=1.0, default=0.5)
    notes:         str   = ""


def llm_judge_eval(
    question:       str,
    answer:         str,
    context:        str,
    expected_answer: Optional[str] = None,
    pass_threshold:  float = 0.75,
) -> EvalResult:
    """
    LLM-as-judge evaluation. Used for semantic correctness and grounding
    checks that deterministic metrics cannot handle.
    """
    expected_block = ""
    if expected_answer:
        expected_block = f"\nExpected answer: {expected_answer}"

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        system=(
            "You are an AI output evaluator. Score on:\n"
            "faithfulness: is every claim in the answer supported by the context?\n"
            "relevancy: does the answer address the question?\n"
            "correctness: does the answer match the expected answer (if provided)?\n"
            "Scores 0.0-1.0. Be strict on faithfulness."
        ),
        tools=[{
            "name": "score",
            "description": "Return evaluation scores.",
            "input_schema": JudgeScores.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "score"},
        messages=[{"role": "user", "content": (
            f"Question: {question}\n\n"
            f"Context:\n{context[:1000]}\n\n"
            f"Answer to evaluate:\n{answer[:500]}"
            f"{expected_block}"
        )}]
    )
    tool_call = next(b for b in response.content if b.type == "tool_use")
    scores = JudgeScores(**tool_call.input)

    dimensions = {
        "faithfulness":  scores.faithfulness,
        "relevancy":     scores.relevancy,
        "correctness":   scores.correctness,
    }
    overall = sum(dimensions.values()) / len(dimensions)

    return EvalResult(
        case_id="llm_judge",
        overall=overall,
        dimensions=dimensions,
        passed=min(dimensions.values()) >= pass_threshold and overall >= pass_threshold,
        notes=scores.notes,
    )


# ============================================================
# Offline eval suite runner
# ============================================================

def run_eval_suite(
    eval_cases: list[EvalCase],
    pipeline_fn,
    pass_threshold:  float = 0.75,
    min_pass_rate:   float = 0.85,
) -> dict:
    """
    Run a golden dataset eval suite.

    Args:
        eval_cases:    List of test cases with questions + expected answers
        pipeline_fn:   Callable(question, context) -> answer string
        pass_threshold: Minimum score per case to pass (default 0.75)
        min_pass_rate:  Minimum fraction of cases that must pass (default 0.85)

    Returns:
        Summary dict with pass_rate, mean_score, failed_cases
    """
    results = []
    for case in eval_cases:
        answer = pipeline_fn(case.question, case.context)
        result = llm_judge_eval(
            question=case.question,
            answer=answer,
            context=case.context,
            expected_answer=case.expected_answer,
            pass_threshold=pass_threshold,
        )
        result.case_id = case.case_id
        results.append(result)

    passed    = [r for r in results if r.passed]
    pass_rate = len(passed) / len(results) if results else 0.0
    mean_score = sum(r.overall for r in results) / len(results) if results else 0.0

    suite_passed = pass_rate >= min_pass_rate

    return {
        "total_cases":  len(results),
        "passed_cases": len(passed),
        "pass_rate":    pass_rate,
        "mean_score":   mean_score,
        "suite_passed": suite_passed,
        "failed_cases": [
            {"case_id": r.case_id, "score": r.overall, "notes": r.notes}
            for r in results if not r.passed
        ],
    }


# ============================================================
# Online drift detection
# ============================================================

def compute_psi(
    baseline: list[float],
    current:  list[float],
    n_bins:   int = 10,
) -> float:
    """
    Population Stability Index (PSI) for input distribution drift detection.

    PSI < 0.10: no significant change
    PSI 0.10-0.25: moderate change; investigate
    PSI > 0.25: significant shift; model may need retraining
    """
    import numpy as np

    all_vals = baseline + current
    bins = np.linspace(min(all_vals), max(all_vals), n_bins + 1)

    base_counts, _ = np.histogram(baseline, bins=bins)
    curr_counts, _ = np.histogram(current,  bins=bins)

    # Avoid division by zero
    base_pct = (base_counts + 0.0001) / (sum(base_counts) + 0.0001 * n_bins)
    curr_pct = (curr_counts + 0.0001) / (sum(curr_counts) + 0.0001 * n_bins)

    psi = sum((curr_pct - base_pct) * np.log(curr_pct / base_pct))
    return float(psi)


def check_score_drift(
    baseline_scores: list[float],
    current_scores:  list[float],
    alert_threshold: float = 0.10,
    component:       str = "unknown",
) -> dict:
    """
    Check for score distribution drift using PSI.
    Alerts if drift exceeds threshold.
    """
    if not baseline_scores or not current_scores:
        return {"status": "insufficient_data"}

    psi = compute_psi(baseline_scores, current_scores)
    mean_baseline = sum(baseline_scores) / len(baseline_scores)
    mean_current  = sum(current_scores)  / len(current_scores)
    mean_delta    = mean_current - mean_baseline

    status = "stable"
    if psi > 0.25:
        status = "significant_drift"
        _send_budget_alert(
            f"Score distribution SIGNIFICANT DRIFT for {component}: "
            f"PSI={psi:.3f}, mean delta={mean_delta:+.3f}"
        )
    elif psi > 0.10:
        status = "moderate_drift"
        print(f"[DRIFT WARNING] {component}: PSI={psi:.3f}, mean delta={mean_delta:+.3f}")

    return {
        "component":     component,
        "psi":           psi,
        "status":        status,
        "mean_baseline": mean_baseline,
        "mean_current":  mean_current,
        "mean_delta":    mean_delta,
    }


# ============================================================
# Token budget enforcement
# ============================================================

class TokenBudgetPolicy(str, Enum):
    HARD  = "hard"    # truncate input to stay within budget; never exceed
    SOFT  = "soft"    # warn if exceeded; allow the call but log
    ALERT = "alert"   # allow the call but page on-call if exceeded


@dataclass
class TokenBudget:
    component:        str
    max_input_tokens: int
    max_output_tokens: int
    policy:           TokenBudgetPolicy


OPSPU_TOKEN_BUDGETS: dict[str, TokenBudget] = {
    "complexity_assessment": TokenBudget(
        component="complexity_assessment",
        max_input_tokens=1_000,
        max_output_tokens=200,
        policy=TokenBudgetPolicy.HARD,
    ),
    "sql_generation_tier2": TokenBudget(
        component="sql_generation_tier2",
        max_input_tokens=4_000,
        max_output_tokens=1_500,
        policy=TokenBudgetPolicy.SOFT,
    ),
    "sql_generation_tier3": TokenBudget(
        component="sql_generation_tier3",
        max_input_tokens=8_000,
        max_output_tokens=2_000,
        policy=TokenBudgetPolicy.ALERT,
    ),
    "column_description": TokenBudget(
        component="column_description",
        max_input_tokens=3_000,
        max_output_tokens=200,
        policy=TokenBudgetPolicy.HARD,
    ),
    "failure_triage": TokenBudget(
        component="failure_triage",
        max_input_tokens=5_000,
        max_output_tokens=800,
        policy=TokenBudgetPolicy.SOFT,
    ),
}


def enforce_token_budget(
    component: str,
    input_text: str,
) -> str:
    """
    Apply the token budget policy for a component.
    HARD: truncate input. SOFT/ALERT: log a warning without truncating.
    Returns the (possibly truncated) input text.
    """
    budget = OPSPU_TOKEN_BUDGETS.get(component)
    if not budget:
        return input_text

    # Rough estimate: 1 token ≈ 4 characters
    estimated_tokens = len(input_text) // 4

    if estimated_tokens > budget.max_input_tokens:
        message = (
            f"Token budget exceeded for {component}: "
            f"~{estimated_tokens:,} estimated > {budget.max_input_tokens:,} limit."
        )
        if budget.policy == TokenBudgetPolicy.HARD:
            max_chars = budget.max_input_tokens * 4
            input_text = input_text[:max_chars] + "\n[INPUT TRUNCATED — TOKEN BUDGET EXCEEDED]"
        elif budget.policy == TokenBudgetPolicy.ALERT:
            _send_budget_alert(message)
        else:
            print(f"  WARN: {message}")

    return input_text


# Anthropic pricing (approximate 2025; check current pricing at implementation time)
ANTHROPIC_PRICING = {
    "claude-haiku-4-5":  {"input": 0.80 / 1e6, "output": 4.00 / 1e6, "cache_read": 0.08 / 1e6},
    "claude-sonnet-4-5": {"input": 3.00 / 1e6, "output": 15.00 / 1e6, "cache_read": 0.30 / 1e6},
}

MONTHLY_BUDGETS_USD: dict[str, float] = {
    "sql_generation":         15.00,
    "documentation_pipeline":  8.00,
    "failure_triage":           3.00,
    "incident_search":          5.00,
}


def compute_monthly_cost(
    trace_records: list[dict],
    month: str,
) -> list[dict]:
    """
    Aggregate monthly AI costs from trace records and compare against budgets.
    Alert for components approaching or exceeding budget.
    """
    from collections import defaultdict

    by_component: dict[str, list[dict]] = defaultdict(list)
    for record in trace_records:
        component = record.get("component", "unknown")
        by_component[component].append(record)

    summaries = []
    for component, records in by_component.items():
        total_input   = sum(r.get("input_tokens",      0) for r in records)
        total_output  = sum(r.get("output_tokens",     0) for r in records)
        cache_hits    = sum(r.get("cache_read_tokens", 0) for r in records)
        model         = records[0].get("model", "claude-haiku-4-5")
        pricing       = ANTHROPIC_PRICING.get(model, ANTHROPIC_PRICING["claude-haiku-4-5"])

        cost = (
            total_input  * pricing["input"]  +
            total_output * pricing["output"] +
            cache_hits   * pricing["cache_read"]
        )
        budget = MONTHLY_BUDGETS_USD.get(component, 10.00)
        util   = cost / budget if budget > 0 else 0

        if util >= 0.90:
            _send_budget_alert(
                f"{component} has used {util*100:.0f}% of monthly budget "
                f"(${cost:.2f} / ${budget:.2f})."
            )

        summaries.append({
            "component":          component,
            "month":              month,
            "total_calls":        len(records),
            "total_input_tokens": total_input,
            "total_output_tokens":total_output,
            "cache_hit_tokens":   cache_hits,
            "estimated_cost_usd": round(cost, 4),
            "budget_usd":         budget,
            "budget_utilization": round(util, 3),
        })
    return summaries


if __name__ == "__main__":
    # Demo drift check with synthetic scores
    import random
    random.seed(42)
    baseline = [random.gauss(0.82, 0.05) for _ in range(100)]
    current  = [random.gauss(0.74, 0.07) for _ in range(100)]  # slight degradation

    result = check_score_drift(baseline, current, component="sql_generation")
    print(f"Drift check: PSI={result['psi']:.3f} status={result['status']}")
    print(f"Mean delta: {result['mean_delta']:+.3f}")
