-- Chapter 14: Reference Architectures — Apache Ossie Interoperability
-- Section: 14.3 What Becomes Standard vs Hype
-- Book: AI-Based Data Engineering (Packt)
--
-- Apache Ossie (incubating), formerly Open Semantic Interchange (OSI), is a
-- vendor-neutral YAML format for semantic models. Snowflake reads and writes it
-- natively (preview feature, available to all accounts), and dbt Core v1.12+ parses Ossie documents placed in an
-- `osi/` directory into the manifest. This script runs the Snowflake side of
-- the round trip for the canonical fct_active_customers model:
--   1. Create a semantic view from Ossie YAML
--   2. Export it back as Ossie YAML and diff what survived
--
-- One caveat: the round trip is lossy at the edges, by design of the spec.
--   * Only equi-join relationships are exported; ASOF and RANGE joins are dropped.
--   * Field labels and data types are not carried.
--   * Table-level metrics and filters move into Snowflake custom_extensions,
--     which other tools ignore.
--   * dbt drops unsupported metric types with warning I078, and every Ossie
--     dataset source must resolve to a dbt model.
-- Simple metrics such as active-customer counts travel cleanly. Complex metric
-- logic does not yet: keep one system as the authoring source of truth.
--
-- Source: OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS from code/setup (Tier B load).
-- Requires: CREATE SCHEMA OPSPU.SEMANTICS (if absent), CREATE SEMANTIC VIEW on it, and SELECT on the
-- underlying tables. Ossie version emitted by Snowflake today: 0.1.1.


-- ============================================================
-- 1. Import: create a semantic view from an Ossie YAML document
-- ============================================================
-- The procedure takes the target schema and the YAML text. The semantic view
-- name comes from the document's `name` field. An existing view with the same
-- name is replaced with its grants preserved (CREATE OR REPLACE ... COPY GRANTS).

CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_OSSIE_YAML(
  'OPSPU.SEMANTICS',
  $$
  version: "0.1.1"
  name: sv_active_customers_ossie
  description: "Canonical active-customer definition (Chapter 1, Table 1-3 reconciled)"
  datasets:
    - name: fct_active_customers
      source: OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS
      primary_key:
        - customer_id
      fields:
        - name: customer_id
          expression:
            dialects:
              - dialect: SNOWFLAKE
                expression: customer_id
          dimension:
            is_time: false
        - name: region_code
          expression:
            dialects:
              - dialect: SNOWFLAKE
                expression: region_code
          dimension:
            is_time: false
        - name: last_order_date
          expression:
            dialects:
              - dialect: SNOWFLAKE
                expression: last_order_date
          dimension:
            is_time: true
  metrics:
    - name: active_customers
      description: "Distinct customers with qualifying activity in the period"
      expression:
        dialects:
          - dialect: SNOWFLAKE
            expression: "COUNT(DISTINCT customer_id)"
  $$
);


-- ============================================================
-- 2. Export: read the semantic view back as Ossie YAML
-- ============================================================
-- Works on any semantic view, however it was created (DDL, native YAML, Ossie).

SELECT SYSTEM$READ_OSSIE_YAML_FROM_SEMANTIC_VIEW(
    'OPSPU.SEMANTICS.SV_ACTIVE_CUSTOMERS_OSSIE'
) AS ossie_yaml;

-- Save the result as osi/active_customers.yaml in the dbt project to have
-- dbt Core v1.12+ load the same definition into its manifest. Diff it against
-- the document in step 1 before treating the two systems as interchangeable
-- for a given model. The export always uses the wrapped document format
-- (version + semantic_model: [...]), so expect structural noise in the diff.
