-- Chapter 14: Reference Architectures — Apache Ossie Interoperability
-- Book: AI-Based Data Engineering (Packt)
--
-- Apache Ossie (Open Semantic Interchange, incubator since Jul 2026):
-- A vendor-neutral YAML format for semantic layer definitions.
-- 50+ vendors converge on a single interchange format — meaning your
-- semantic models become portable across Snowflake, dbt, Looker, Tableau,
-- and any tool that reads/writes Ossie YAML.
--
-- This script demonstrates the Snowflake ↔ Ossie round-trip:
--   1. Export a Snowflake Semantic View as Ossie YAML
--   2. (External) Edit/validate with any Ossie-compatible tool
--   3. Re-import the Ossie YAML back into Snowflake


-- ============================================================
-- 1. Export: read Ossie YAML from an existing Semantic View
-- ============================================================

SELECT SYSTEM$READ_OSSIE_YAML_FROM_SEMANTIC_VIEW(
    'OPSPU.SEMANTICS.SV_ACTIVE_CUSTOMERS'
) AS ossie_yaml;

-- The output is a portable YAML document conforming to the Ossie spec.
-- It contains: entities, measures, dimensions, relationships, and
-- verified queries — everything needed to reconstruct the semantic
-- model in another tool.


-- ============================================================
-- 2. Validate the exported YAML (CLI, outside Snowflake)
-- ============================================================

-- $ pip install apache-ossie
-- $ ossie validate exported_model.yaml
-- ✓ Valid Ossie v1.0 document (3 entities, 7 measures, 12 dimensions)


-- ============================================================
-- 3. Import: create a Semantic View from Ossie YAML
-- ============================================================

-- Load your Ossie YAML onto a stage, then:
CREATE OR REPLACE SEMANTIC VIEW OPSPU.SEMANTICS.SV_FROM_OSSIE
  FROM OSSIE YAML '@opspu_semantic_stage/customer_model.ossie.yaml';

-- The imported semantic view is immediately usable with Cortex Analyst
-- and inherits all measures, dimensions, and verified queries from the
-- Ossie source — regardless of which tool originally authored them.
