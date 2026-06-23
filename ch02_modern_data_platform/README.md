# Chapter 2: The Modern Stack — Data + AI + Control Plane
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `iceberg_time_travel.sql` | Iceberg table DDL (Horizon-native + Open Catalog cross-engine), schema history, time travel queries |
| `lineage_openlineage.py` | OpenLineage event emission for ingestion and transformation jobs |
| `capability_index.md` | Platform capability index — the “always in context” routing artifact for AI agents |
| `mcp_server_intro.py` | Minimal FastMCP catalog server introducing the MCP pattern (full stack in Ch07) |

## Key concepts

- **Two-engine convergence**: Snowflake (governed consumption) + Databricks (upstream production) connected via Apache Iceberg
- **Horizon Catalog** governs Snowflake-native tables; **Open Catalog** (Apache Polaris) exposes cross-engine Iceberg tables via REST
- **Time travel**: every Iceberg write creates a snapshot; agents reference snapshot IDs for reproducible debugging
- **Catalog as runtime context**: agents query `INFORMATION_SCHEMA` before acting, not after
- **MCP** (Model Context Protocol, Anthropic Nov 2024): standard interface for agent tool calls (deep coverage in Ch07)

## OpsPulse platform decision

```
Databricks → Kafka → Spark Streaming → Iceberg (object storage)
                                             ↓
                               Snowflake (governed SQL + Cortex AI)
                               Snowflake Horizon Catalog (governance)
                               Open Catalog / Polaris (cross-engine)
```

## dbt exposures (YAML in book)

The chapter includes `models/exposures.yml` defining:
- `inventory_ops_dashboard` — downstream of `fct_inventory_exposure`
- `churn_risk_ml_feature_pipeline` — downstream of `fct_active_customers`

See manuscript Chapter 2 for the full YAML.
