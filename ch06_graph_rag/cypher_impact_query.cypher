-- Chapter 6: Context Graphs and GraphRAG for Enterprise Data
-- Section: 6.2 Cypher queries for impact analysis
-- Book: AI-Based Data Engineering (Packt)
--
-- NOTE: Code snippets marked with ... are illustrative stubs from the book text.
-- Complete implementations are provided where the full code is shown.

-- ============================================================
-- 1. Find all downstream tables when device_id is renamed
--    in opspu_iot_telemetry (up to 4 hops)
-- ============================================================
MATCH (source:DataNode {name: 'opspu_iot_telemetry'})
MATCH path = (source)-[:FEEDS*1..4]->(downstream:DataNode)
WHERE downstream.node_type = 'table'
RETURN
    downstream.name     AS affected_table,
    length(path)        AS hops,
    [n IN nodes(path) | n.name] AS path_nodes
ORDER BY hops, affected_table;


-- ============================================================
-- 2. Find dashboards affected by a change to fct_device_anomalies
-- ============================================================
MATCH (source:DataNode)
WHERE toLower(source.name) CONTAINS 'fct_device_anomalies'
  AND source.node_type = 'table'
MATCH path = (source)-[:FEEDS*1..3]->(dashboard:DataNode {node_type: 'dashboard'})
RETURN
    dashboard.name   AS dashboard_name,
    length(path)     AS hops,
    source.name      AS changed_table
ORDER BY hops;


-- ============================================================
-- 3. Find all tables owned by the ML Platform team
--    (cross-entity: table → team ownership)
-- ============================================================
MATCH (team:DataNode {name: 'ML Platform Team', node_type: 'team'})
MATCH (team)<-[:OWNED_BY]-(table:DataNode {node_type: 'table'})
RETURN table.name AS table_name
ORDER BY table_name;


-- ============================================================
-- 4. Blast radius: everything downstream of stg_iot_events
--    with at most 5 hops, grouped by type
-- ============================================================
MATCH (source:DataNode)
WHERE toLower(source.name) CONTAINS 'stg_iot_events'
MATCH path = (source)-[:FEEDS*1..5]->(downstream:DataNode)
RETURN
    downstream.node_type   AS entity_type,
    COUNT(DISTINCT downstream) AS affected_count
ORDER BY affected_count DESC;


-- ============================================================
-- 5. Column-level lineage: which tables read device_id column?
-- ============================================================
MATCH (col:DataNode {name: 'device_id', node_type: 'column'})
MATCH (col)<-[:HAS_COLUMN]-(table:DataNode {node_type: 'table'})
MATCH path = (table)-[:FEEDS*0..3]->(downstream:DataNode)
RETURN DISTINCT
    downstream.name     AS downstream_entity,
    downstream.node_type AS entity_type,
    length(path)        AS hops
ORDER BY hops, downstream_entity;


-- ============================================================
-- 6. Create graph structure for OpsPulse (setup script)
-- ============================================================

-- Create core nodes
MERGE (iot:DataNode {id: 'OPSPU.RAW.OPSPU_IOT_TELEMETRY'})
SET iot.name = 'opspu_iot_telemetry',
    iot.node_type = 'table',
    iot.schema = 'RAW';

MERGE (stg:DataNode {id: 'dbt://opspu/stg_iot_events'})
SET stg.name = 'stg_iot_events',
    stg.node_type = 'table',
    stg.schema = 'STAGING';

MERGE (fct:DataNode {id: 'dbt://opspu/fct_device_anomalies'})
SET fct.name = 'fct_device_anomalies',
    fct.node_type = 'table',
    fct.schema = 'MARTS';

MERGE (dash:DataNode {id: 'ops_anomaly_dashboard'})
SET dash.name = 'ops_anomaly_dashboard',
    dash.node_type = 'dashboard';

-- Create edges
MATCH (a:DataNode {id: 'OPSPU.RAW.OPSPU_IOT_TELEMETRY'})
MATCH (b:DataNode {id: 'dbt://opspu/stg_iot_events'})
MERGE (a)-[:FEEDS {edge_type: 'dbt_source'}]->(b);

MATCH (a:DataNode {id: 'dbt://opspu/stg_iot_events'})
MATCH (b:DataNode {id: 'dbt://opspu/fct_device_anomalies'})
MERGE (a)-[:FEEDS {edge_type: 'dbt_dependency'}]->(b);

MATCH (a:DataNode {id: 'dbt://opspu/fct_device_anomalies'})
MATCH (b:DataNode {id: 'ops_anomaly_dashboard'})
MERGE (a)-[:FEEDS {edge_type: 'consumes'}]->(b);
