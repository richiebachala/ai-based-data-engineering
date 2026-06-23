# Chapter 13: Scaling Adoption — Use-Case Funnel and Team Topologies
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `use_case_scoring.py` | Impact/effort scoring model for prioritizing AI use cases. Includes OpsPulse portfolio rankings. |

## Key concepts

- **Use-case funnel**: not every data task is a good AI candidate; score before committing
- **Impact dimensions**: time savings, quality improvement, adoption signal, cost reduction
- **Effort dimensions**: context readiness, integration effort, eval complexity, risk level
- **ROI = impact / effort**: the ordering principle for your adoption roadmap
- **Team topologies**: AI Platform team (infrastructure), Domain DE teams (application), Governance team (oversight)

## Recommended starting order (OpsPulse)

1. **Column description auto-generation** (Ch8) — highest ROI, lowest risk
2. **Pipeline failure triage** (Ch10) — high team satisfaction, replaces repetitive work
3. **Lineage impact analysis** (Ch6) — prevents the most expensive incidents
4. **SQL generation assistant** (Ch9) — requires semantic layer investment first

## Team topology (Section 13.3)

```
AI Platform Team
  └─ MCP server infrastructure (Ch07)
  └─ Eval and observability stack (Ch11)
  └─ Context pipeline (Ch05)
  └─ Governance controls (Ch12)

Domain Data Engineering Teams
  └─ Workflow patterns (Ch03)
  └─ Ingestion + documentation pipeline (Ch08)
  └─ SQL generation (Ch09)
  └─ Orchestration + triage (Ch10)

Governance Team
  └─ Classification + stewardship (Ch12.6)
  └─ Access policies (Ch12.2)
  └─ Eval criteria and pass thresholds (Ch11)
```

## What changes for data engineers

> "The engineers who merge AI-generated SQL, dbt models, documentation, and runbooks
> are responsible for those artifacts. The eval harness, security scanner, and approval
> gates reduce the probability of errors — but professional accountability remains with humans."

AI data engineering expands scope from pipeline builder to platform architect:
- Build and maintain the context layer that agents depend on
- Define eval criteria and pass thresholds
- Review AI-generated artifacts before promotion to production
- Own the governance controls that make agent behavior safe and auditable
