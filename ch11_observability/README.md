# Chapter 11: Evals and AI Observability in Production
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `eval_harness.py` | LLM-as-judge evaluator, offline eval suite runner, PSI drift detection, token budget enforcement, monthly cost governance |
| `observability_tracing.py` | OpenTelemetry tracing with GenAI semantic conventions; traced LLM call wrapper; pipeline step decorator |

## Key concepts

- **Two-layer monitoring**: offline evals (CI, golden datasets) + online monitoring (production, rolling windows)
- **Eval frameworks**: RAGAs (retrieval), DeepEval (structured outputs), PromptFoo (CI regression), Braintrust (version tracking)
- **GenAI semantic conventions**: standardized OTel attributes make traces portable across backends
- **PSI drift detection**: PSI < 0.10 stable; 0.10-0.25 investigate; > 0.25 significant shift
- **Cost governance**: per-component token budgets with HARD (truncate), SOFT (warn), ALERT (page) policies

## Bug fixes applied

- **C11-1**: `_send_budget_alert()` and `_utc_now_iso()` are now defined (not just referenced)

## Eval framework selection guide

| Framework | Use for |
|-----------|--------|
| RAGAs | Context precision, recall, faithfulness, answer relevancy |
| DeepEval | Custom GEval criteria for structured outputs |
| PromptFoo | Regression suites in CI (see ch04_structured_prompting/promptfoo/) |
| Braintrust | Score history across model versions, A/B comparison |
| LLM-as-judge | Semantic correctness, grounding (when no ground truth available) |

## Token budget thresholds (OpsPulse)

| Component | Max input | Max output | Policy |
|-----------|-----------|------------|--------|
| complexity_assessment | 1,000 | 200 | HARD |
| sql_generation_tier2 | 4,000 | 1,500 | SOFT |
| sql_generation_tier3 | 8,000 | 2,000 | ALERT |
| column_description | 3,000 | 200 | HARD |
| failure_triage | 5,000 | 800 | SOFT |
