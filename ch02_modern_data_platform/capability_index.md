# Chapter 2: The Modern Stack — Data + AI + Control Plane
# Section: 2.3 Catalogs and lineage as context infrastructure
# Book: AI-Based Data Engineering (Packt)
#
# Capability index (CAPABILITIES.md pattern)
# This file is the "always in context" artifact described in Chapter 5.
# Pin it in every agent system prompt; it is the routing table for the platform.

# OpsPulse Platform — Capability Index

This document is the first artifact an AI agent retrieves when it starts a session.
It answers: which tool handles which task, which tables exist, and what SQL dialect to use.

## Platform identity

- **Warehouse**: Snowflake (account: `opspu`)
- **Transformation**: dbt Core 1.8+ (targets Snowflake)
- **Orchestration**: Apache Airflow 2.9+
- **Lineage**: OpenLineage → Marquez
- **SQL dialect**: Snowflake SQL (NOT ANSI / PostgreSQL / MySQL)

## Key tables

| Table FQN | Description | Grain |
|-----------|-------------|-------|
| `OPSPU.RAW.OPSPU_IOT_TELEMETRY` | Raw IoT sensor events | One row per device event |
| `OPSPU.RAW.OPSPU_SUPPORT_TICKETS` | Support ticket text | One row per ticket |
| `OPSPU.STAGING.STG_IOT_EVENTS` | Cleaned IoT events | One row per device event |
| `OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS` | Active customer fact | One row per active customer |
| `OPSPU.MARTS.FCT_INVENTORY_EXPOSURE` | Inventory risk exposure | One row per product × region × date |
| `OPSPU.MARTS.FCT_DEVICE_ANOMALIES` | Anomaly events | One row per anomaly |
| `OPSPU.MARTS.DIM_DEVICES` | Device master | One row per device |

## SQL rules (ALWAYS apply)

1. Use `CURRENT_DATE` — never `NOW()`, `GETDATE()`, or `CURRENT_DATE()`
2. Date arithmetic: `DATEADD('day', -7, CURRENT_DATE)`
3. Case-insensitive string match: `ILIKE`, not `LIKE`
4. Array aggregation: `ARRAY_AGG(DISTINCT col)`
5. SELECT only. No DML, DDL, or CALL statements unless the write server approves.
6. Add `LIMIT 10000` unless the query uses aggregation.

## Active customer definition

Canonical definition (agreed 2025-Q1): at least one qualifying event
(`session_start`, `feature_use`, `api_call`) in the trailing 30 days.
Excludes internal test accounts (`is_internal = TRUE`) and churned accounts.
Use `OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS` — do NOT compute from raw events.

## Divergent definitions (do NOT use in new work)

| Team | Old definition used |
|------|--------------------|
| Sales ops | Contract value > 0 → 14,230 |
| Product analytics | Login in last 30d → 9,847 |
| Customer success | No churn-risk flag → 11,502 |
| Finance | Recognized revenue this quarter → 8,319 |

All four are superseded by the canonical definition above.

## MCP tool inventory

| Tool | Server | Description |
|------|--------|-------------|
| `run_snowflake_select` | analytics | Execute read-only SELECT; returns up to 1000 rows |
| `get_table_schema` | catalog | Return full column schema for a table FQN |
| `get_column_lineage` | catalog | Return upstream/downstream lineage for a column |
| `update_column_description` | operations | Write column comment (requires approval token) |
| `run_dbt_model` | operations | Trigger a dbt run for a specific model |
