# Chapter 9: Generate and Verify Transformations (SQL/dbt)
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `self_healing_pipeline.py` | Full self-healing SQL pipeline: complexity assessment → generation → guardrails → plausibility eval → repair |
| `dbt_test_generation.py` | Generate dbt tests from column profiles (rule-based) + complex business rules (LLM-augmented) |

## Key concepts

- **Complexity tiers**: tier1=haiku (simple), tier2=sonnet (CTEs), tier3=extended thinking (complex)
- **Three-layer validation**: structural guardrails → anti-pattern checks → plausibility evaluation
- **Self-healing loop**: evaluator provides structured feedback; generator reruns with feedback appended
- **Business rules input**: plausibility check validates against plain-English rules, not just schema
- **dbt Copilot**: complements the programmatic pipeline for interactive IDE development

## OpsPulse pipeline outcome

```
Iteration 1: score=0.68 — feedback: "staleness calc doesn't filter to passed=TRUE calibrations"
Iteration 2: score=0.89 — passed
Total: 2 iterations, 45 seconds. Written to models/marts/fct_calibration_aware_anomalies.sql
```

## Guardrail rules

| Layer | Rule | Severity |
|-------|------|----------|
| Structural | No DML (DELETE/INSERT/UPDATE/...) | error |
| Structural | No semicolons (multi-statement) | error |
| Structural | Table allowlist | error |
| Structural | No cartesian/CROSS JOIN | error |
| Anti-pattern | NULL equality (= NULL) | warning |
| Anti-pattern | Integer division | warning |
| Anti-pattern | UNION without ALL | warning |

## dbt test generation rules

| Rule | Test generated |
|------|----------------|
| Identifier column, 0% null | `not_null` + `unique` |
| FK column detected | `relationships` |
| Dimension, < 20 distinct | `accepted_values` |
| BOOLEAN / flag column | `accepted_values: [true, false]` |
| Event timestamp (`_at`) | `not_null` |
