# Chapter 14: Reference Architectures, Case Studies, and the Future
# Book: AI-Based Data Engineering (Packt)

## Overview

Chapter 14 synthesizes the full book into:
- Three reference architectures (solo engineer, team, enterprise)
- Four domain case studies (customer 360, finance close, inventory, catalog security)
- Forward-looking standard vs. hype assessment
- Human accountability framework

No new executable code is introduced in this chapter. The chapter draws on
patterns from all previous chapters and demonstrates how they combine at scale.

## Reference architecture tiers

### Tier 1: Solo engineer / early adoption

```
Catalog MCP server (Ch07) + PTCF prompts (Ch04)
  └ No eval harness yet; engineer reviews every output manually
  └ Trigger: "does this work well enough to share with the team?"
```

### Tier 2: Team-scale platform

```
Full context pipeline (Ch05) + Eval CI (Ch11) + Approval gates (Ch10)
  └ Eval CI blocks deployment on score regression
  └ Trigger: second engineer joins; second domain onboards
```

### Tier 3: Enterprise platform

```
All tiers + Governance (Ch12) + Multi-domain MCP (Ch07) + Observability (Ch11)
  └ Formal eval criteria per use case, per domain
  └ EU AI Act compliance logging (Article 14 + 15)
  └ Trigger: production use case proves value; second business domain onboards
```

## Domain case studies (what the controls prevent)

| Domain | Without controls | With controls |
|--------|-----------------|---------------|
| Customer 360 | Confidently incorrect account health assessments | RAGAs faithfulness monitoring catches hallucinated account history |
| Finance close | Wrong revenue figures reaching the CFO | PlausibilityEval blocks SQL that violates closing-period business rules |
| Inventory optimization | $2.1M in unnecessary purchase orders | Approval gates require human sign-off before any inventory commit action |
| Catalog security | Catalog poisoning via compromised calibration report | Content scanning detects injection in EXTERNAL-tier source |

## Standard vs. hype (Section 14.3)

| Pattern | Assessment |
|---------|------------|
| MCP (Ch07) | Standard — adopted by OpenAI + Google DeepMind in 2025 |
| Eval-as-CI (Ch11) | Standard — same rigor as unit tests for deterministic code |
| Structured outputs (Ch04) | Standard — API-level enforcement since Aug 2024 |
| Context engineering (Ch05) | Standard — the durable skill this book is built around |
| Fully autonomous agents without approval gates | Hype — engineering reality does not match the marketing |
| Fine-tuning as default domain adaptation | Hype — context engineering is cheaper and more flexible |
| Long-context as RAG replacement | Hype for large corpora; viable for stable small-corpus cases |

## Accountability principle (Section 14.4)

> "Accountability follows intent, not authorship. The engineering choices that make
> a system overseen — prompt templates in version control, eval CI with documented
> criteria, audit logs, approval gates with full context, runbooks — are the
> implementation of what the EU AI Act's Article 14 requires and what professional
> engineering standards will increasingly demand."

## The platform built across 14 chapters

| Chapter | Component | What it enables |
|---------|-----------|----------------|
| 1 | AI-readiness checklist | Know your current score before building |
| 2 | Iceberg + catalog | Reproducibility, cross-engine governance |
| 3 | Workflow patterns | Reliable, debuggable AI workflows |
| 4 | Structured prompts + evals | Consistent, testable outputs |
| 5 | Context pipeline | Grounded, auditable inference |
| 6 | Knowledge graph | Multi-hop relationship queries |
| 7 | MCP tool layer | Standardized agent-tool interface |
| 8 | Ingestion + documentation | Documentation as a byproduct |
| 9 | Self-healing SQL | Verified transformations |
| 10 | Intelligent orchestration | Self-repairing pipelines |
| 11 | Evals + observability | Measurable, monitored AI quality |
| 12 | Governance + security | Safe, auditable AI operations |
| 13 | Team topology | Organizational scaling patterns |
| 14 | Reference architectures | End-to-end integration guide |
