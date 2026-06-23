# Chapter 1: What Is AI-Based Data Engineering?
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `ai_readiness_checklist.py` | Score any Snowflake table on six AI-readiness dimensions (D1–D6). Includes the OpsPulse baseline (4/18). |

## Key concepts

- **AI-based data engineering** = context pipelines + structured generation + evaluation controls
- **Three trust primitives**: Quality (D3–D4), Provenance (D5–D6), Semantics (D1–D2)
- **Data product** = owned dataset with a contract, tests, and lineage (vs. a raw pipeline output)
- **OpsPulse baseline**: 4/18 — realistic starting point for most teams

## Usage

```bash
# Print the OpsPulse illustrative baseline (no Snowflake connection needed)
python ai_readiness_checklist.py

# Score a real table (requires a Snowflake connection + optional dbt manifest)
python - <<'EOF'
import snowflake.connector, json
from ai_readiness_checklist import score_table

conn = snowflake.connector.connect(
    account="YOUR_ACCOUNT",
    user="YOUR_USER",
    password="YOUR_PASSWORD",
    warehouse="DEV_WH",
    database="OPSPU",
    schema="MARTS",
)
with open("target/manifest.json") as f:
    manifest = json.load(f)
result = score_table(conn, "OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS", dbt_manifest=manifest)
result.print_report()
EOF
```

## Chapter 1 data product contracts (YAML)

The chapter includes two YAML artefacts that seed the context layer:

**`models/marts/fct_active_customers.yml`** — dbt data product contract  
**`models/semantics/active_customers.yml`** — MetricFlow semantic model

These are included inline in the chapter text; see the manuscript for the full YAML.
