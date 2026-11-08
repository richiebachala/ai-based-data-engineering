# Chapter 13: Scaling Adoption — Use-Case Funnel and Team Topologies
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `use_case_scoring.py` | Impact/effort scoring rubric from Section 13.1. Reproduces the OpsPulse worked-example table and asserts the totals match the chapter. |

Run it with no dependencies beyond the standard library:

```bash
python use_case_scoring.py
```

## Key concepts

- **Use-case funnel**: not every data task is a good AI candidate; score before committing
- **Impact dimensions** (1–5 each, /20): time saved, quality improvement, risk reduction, strategic value
- **Effort dimensions** (1–5 each, /20): data readiness, AI complexity, compliance overhead, integration effort
- **Quadrant**: impact and effort are "high" above 10/20 → Quick win, Strategic, Fill-in, Low priority
- **Team topologies** (Section 13.3): platform team, stream-aligned domain teams, enabling team

## OpsPulse roadmap (Section 13.1 worked example)

1. **Finance period-close assistant** — Quick win (18/20 impact, 9/20 effort) — first pilot
2. **Procurement document extraction** — Quick win (12/20, 6/20) — runs in parallel
3. **HR workforce analytics copilot** — Strategic (17/20, 18/20) — Month 4, after security review
4. **Supply chain anomaly detection** — Strategic (15/20, 14/20) — Month 6
5. **Regulatory compliance Q&A** — Fill-in (10/20, 8/20) — kit library RAG starter

## Team topology (Section 13.3)

```
Platform team
  └─ MCP server infrastructure (Ch07)
  └─ Eval and observability stack (Ch11)
  └─ Context pipeline (Ch05)
  └─ Governance controls (Ch12)

Stream-aligned domain teams (finance, procurement, HR, supply chain)
  └─ Use-case delivery from the kit library (Ch13.2)
  └─ Domain eval sets and golden queries (Ch11)

Enabling team
  └─ Coaching domain teams onto the kits and playbook
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
