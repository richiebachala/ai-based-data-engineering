# Chapter 12: Governance and Security for Context and Agents
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `content_scanning.py` | Injection detection with source trust tiers, per-source pattern strictness, audit logging |
| `masking_policies.sql` | Snowflake masking + row access policies: PII masking, tag-based masking, region sovereignty, stewardship block |

## Key concepts

- **Indirect prompt injection**: attack surface = retrieved data (tickets, PDFs, table cells), not user input
- **Defense point**: scan tool RESPONSES before they enter the model context
- **Source trust tiers**: SYSTEM (1) < INTERNAL (2) < USER (3) < EXTERNAL (4); higher tier = stricter scan
- **Masking before context**: Snowflake masking policies apply before data reaches the LLM, regardless of how the query is issued
- **Tag-based masking**: PII classification from Chapter 8 connects to masking enforcement (classification = access control)
- **Stewardship queue**: unreviewed tables are blocked by row access policy until a steward clears the flag

## OWASP LLM Top 10 coverage

| Risk | Control |
|------|---------|
| #1 Prompt injection (direct) | Injection patterns in `analytics_server.py` (Ch07) |
| #1 Prompt injection (indirect) | `content_scanning.py` scans all tool responses |
| #2 Sensitive information disclosure | Column masking policies + PII tag enforcement |
| #6 Insecure plugin design | `validate_tool_call()` in `content_scanning.py` |
| #8 Excessive agency | Two-call approval token in `operations_server.py` (Ch07) |

## EU AI Act compliance signals

- **Article 14 (human oversight)**: approval gate (Ch10) + stewardship review (Ch12.6)
- **Article 15 (accuracy monitoring)**: eval CI (Ch11) + drift detection (Ch11)
- **Article 26(5) (log retention)**: 6-month minimum for operational audit; 7 years for financial records
- **GDPR Article 35 (DPIA)**: triggered when classification confidence < 0.75 AND regulatory domain = GDPR/HIPAA

## Running the stewardship workflow

See `pipeline_triage_dag.py` (Ch10) for the `ApprovalSensor` pattern used by the stewardship DAG in Section 12.6.

The stewardship queue DAG (full code in manuscript Chapter 12) reuses the same pattern:
  1. Poll `data_governance.stewardship_queue` for pending proposals
  2. Claim proposal + notify assigned steward
  3. Await steward decision (deferrable sensor)
  4. Apply decision: approve → tag table; reject → clear flag; defer → requeue in 7 days
