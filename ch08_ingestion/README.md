# Chapter 8: AI-Assisted Ingestion, Profiling, and Documentation
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `schema_profiling.py` | Dynamic SQL profiling (single pass), anomaly detection, AI entity detection with PII classification |
| `document_extraction.sql` | PARSE_DOCUMENT, CORTEX.COMPLETE extraction, INFER_SCHEMA, MERGE-ON-LOAD idempotent pattern |
| `documentation_pipeline.py` | Five-step documentation-as-byproduct pipeline: profile → classify → document → apply → lineage |

## Key concepts

- **Profile before ingest**: dynamic SQL profile in one pass catches anomalies before they propagate
- **Entity detection**: LLM identifies business object, grain, data domain, FK relationships, and PII
- **Documentation as byproduct**: 4 min pipeline runtime, 10 min engineer review vs 2-3 hours manual
- **Evaluator-optimizer loop**: generator=haiku (cheap), evaluator=sonnet (quality gate)

## Bug fixes applied

- **C8-1**: `PARSE_DOCUMENT` requires 3 arguments: `(stage, filename, {'mode': 'LAYOUT'})`
- **C8-2**: `ORDER BY ORDER_ID` (not `column_position` which doesn't exist in INFER_SCHEMA output)

## Documentation pipeline output (OpsPulse calibration table)

```
1. Profile:    no blocking anomalies; 2 warnings (8% null on notes, 3% null on technician_id)
2. Classify:   entity_type="device_calibration_event", grain="one row per calibration per device"
3. Document:   8 column descriptions applied as Snowflake COMMENT values
4. Apply:      ALTER TABLE COMMENT applied to all columns
5. Lineage:    OpenLineage RunEvent registered the table's provenance
6. dbt YAML:   schema.yml block ready to paste
```
