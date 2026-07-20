# Chapter 1: What Is AI-Based Data Engineering?
# Section: 1.3 The New Unit of Value: Data Products / 1.4 Trust Primitives / 1.5 AI-Ready Datasets
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
AI-readiness checklist for data engineering teams.

Scores a table on six dimensions (0-3 each, max 18):
  D1: Schema freshness    - columns documented in INFORMATION_SCHEMA
  D2: Semantic coverage   - MetricFlow / semantic view definitions
  D3: Test coverage       - dbt data_tests or equivalent
  D4: Eval readiness      - golden datasets / snapshot history available
  D5: Governance scope    - column-level masking + row access policies
  D6: Lineage coverage    - upstream + downstream lineage queryable

OpsPulse starting score: 4 / 18 (realistic baseline for most teams).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DimensionScore:
    dimension: str
    score: int          # 0 = none, 1 = partial, 2 = mostly, 3 = complete
    max_score: int = 3
    notes: str = ""

    def pct(self) -> float:
        return self.score / self.max_score


@dataclass
class AIReadinessResult:
    table_fqn: str
    dimensions: list[DimensionScore] = field(default_factory=list)

    @property
    def total_score(self) -> int:
        return sum(d.score for d in self.dimensions)

    @property
    def max_score(self) -> int:
        return sum(d.max_score for d in self.dimensions)

    def print_report(self) -> None:
        print(f"\nAI-Readiness Report: {self.table_fqn}")
        print(f"{'='*55}")
        for d in self.dimensions:
            bar = '█' * d.score + '░' * (d.max_score - d.score)
            print(f"  {d.dimension:<22} [{bar}] {d.score}/{d.max_score}")
            if d.notes:
                print(f"    └ {d.notes}")
        print(f"{'='*55}")
        print(f"  TOTAL: {self.total_score}/{self.max_score} "
              f"({self.total_score/self.max_score*100:.0f}%)")
        print()
        if self.total_score <= 6:
            print("  Status: Foundation work required before AI participation")
        elif self.total_score <= 12:
            print("  Status: Targeted investments will unlock AI use cases")
        else:
            print("  Status: Ready for production AI workflows")


def score_table(
    conn,
    table_fqn: str,
    dbt_manifest: Optional[dict] = None,
) -> AIReadinessResult:
    """
    Score a Snowflake table on the six AI-readiness dimensions.

    Args:
        conn: snowflake.connector connection
        table_fqn: Fully-qualified table name (DB.SCHEMA.TABLE)
        dbt_manifest: Parsed dbt manifest.json (optional; needed for D2/D3)

    Returns:
        AIReadinessResult with scores for all six dimensions.
    """
    db, schema, table = table_fqn.upper().split(".")
    result = AIReadinessResult(table_fqn=table_fqn)

    # --- D1: Schema freshness ---
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*)                              AS total_cols,
            SUM(CASE WHEN comment IS NOT NULL
                      AND LENGTH(TRIM(comment)) > 5
                     THEN 1 ELSE 0 END)           AS documented_cols
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
    """, (schema, table))
    row = cur.fetchone()
    total, documented = (row[0], row[1]) if row else (0, 0)
    if total == 0:
        d1 = 0
    elif documented / total >= 0.90:
        d1 = 3
    elif documented / total >= 0.50:
        d1 = 2
    elif documented / total > 0:
        d1 = 1
    else:
        d1 = 0
    result.dimensions.append(DimensionScore(
        "D1: Schema freshness", d1,
        notes=f"{documented}/{total} columns documented"
    ))

    # --- D2: Semantic coverage ---
    # Check whether a dbt semantic_model or metric references this table
    d2 = 0
    if dbt_manifest:
        model_name = table.lower()
        semantic_models = dbt_manifest.get("semantic_models", {})
        metrics = dbt_manifest.get("metrics", {})
        has_semantic = any(
            model_name in str(sm.get("model", "")).lower()
            for sm in semantic_models.values()
        )
        has_metric = any(
            model_name in str(m).lower() for m in metrics.values()
        )
        if has_semantic and has_metric:
            d2 = 3
        elif has_semantic:
            d2 = 2
        elif has_metric:
            d2 = 1
    result.dimensions.append(DimensionScore(
        "D2: Semantic coverage", d2,
        notes="Requires dbt manifest" if not dbt_manifest else ""
    ))

    # --- D3: Test coverage ---
    d3 = 0
    if dbt_manifest:
        nodes = dbt_manifest.get("nodes", {})
        model_key = f"model.opspu.{table.lower()}"
        model = nodes.get(model_key, {})
        tests = [n for n in nodes.values()
                 if n.get("resource_type") == "test"
                 and table.lower() in str(n.get("attached_node", ""))]
        if len(tests) >= 5:
            d3 = 3
        elif len(tests) >= 2:
            d3 = 2
        elif len(tests) >= 1:
            d3 = 1
    result.dimensions.append(DimensionScore(
        "D3: Test coverage", d3,
        notes="Requires dbt manifest" if not dbt_manifest else ""
    ))

    # --- D4: Eval readiness ---
    # Check whether Iceberg snapshot history is available (time travel)
    d4 = 0
    try:
        cur.execute(f"""
            SELECT COUNT(*) FROM {table_fqn}$SNAPSHOTS
            WHERE committed_at > DATEADD('day', -30, CURRENT_TIMESTAMP())
        """)
        snap_count = cur.fetchone()[0]
        if snap_count >= 30:
            d4 = 3
        elif snap_count >= 7:
            d4 = 2
        elif snap_count >= 1:
            d4 = 1
    except Exception:
        # Table is not Iceberg or snapshot history not available
        d4 = 0
    result.dimensions.append(DimensionScore(
        "D4: Eval readiness", d4,
        notes="Iceberg snapshot history check"
    ))

    # --- D5: Governance scope ---
    d5 = 0
    cur.execute("""
        SELECT COUNT(*)
        FROM information_schema.policy_references
        WHERE ref_entity_name = %s AND ref_entity_domain = 'TABLE'
    """, (table,))
    policy_count = cur.fetchone()[0]
    if policy_count >= 2:
        d5 = 3
    elif policy_count == 1:
        d5 = 2
    # Check column-level masking separately
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.policy_references
        WHERE ref_entity_name = %s
          AND policy_kind IN ('MASKING_POLICY', 'ROW ACCESS POLICY')
    """, (table,))
    mask_count = cur.fetchone()[0]
    if mask_count > 0 and d5 == 0:
        d5 = 1
    result.dimensions.append(DimensionScore(
        "D5: Governance scope", d5,
        notes=f"{policy_count} policies attached"
    ))

    # --- D6: Lineage coverage ---
    d6 = 0
    cur.execute("""
        SELECT COUNT(DISTINCT query_id) AS lineage_events
        FROM snowflake.account_usage.access_history
        WHERE ARRAY_CONTAINS(OBJECT_CONSTRUCT('objectName', %s)::VARIANT,
                             objects_modified)
           OR ARRAY_CONTAINS(OBJECT_CONSTRUCT('objectName', %s)::VARIANT,
                             direct_objects_accessed)
        AND query_start_time > DATEADD('day', -30, CURRENT_TIMESTAMP())
    """, (table_fqn, table_fqn))
    lineage_events = cur.fetchone()[0]
    if lineage_events >= 50:
        d6 = 3
    elif lineage_events >= 10:
        d6 = 2
    elif lineage_events >= 1:
        d6 = 1
    result.dimensions.append(DimensionScore(
        "D6: Lineage coverage", d6,
        notes=f"{lineage_events} lineage events in 30d"
    ))

    return result


# --- Tier A: local DuckDB path (runs with no account, no keys) ---------------
#
# The functions above target Snowflake. For a zero-friction local run, generate
# the OpsPulse dataset first:
#
#     pip install -r setup/requirements-setup.txt
#     python setup/opspulse_generator.py --target duckdb --out setup/opspulse.duckdb
#
# then run this file directly. See setup/README.md.


def _default_duckdb_path() -> Path:
    """Locate the generated OpsPulse DuckDB file (env override wins)."""
    env = os.getenv("OPSPULSE_DUCKDB")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "setup" / "opspulse.duckdb"


def score_table_duckdb(
    con,
    table_name: str,
    dbt_manifest: Optional[dict] = None,
) -> AIReadinessResult:
    """Score a local DuckDB table on the six AI-readiness dimensions.

    D1 (schema freshness) is computed for real from the local catalog. D2/D3 use
    a dbt manifest if supplied. D4-D6 depend on Snowflake platform features
    (Iceberg snapshots, policy catalog, access history) and are reported as
    unavailable in local mode — which is itself the honest OpsPulse starting
    point: a raw, undocumented, ungoverned table.
    """
    result = AIReadinessResult(table_fqn=table_name)
    tname = table_name.split(".")[-1].upper()

    # --- D1: Schema freshness (real) ---
    row = con.execute(
        """
        SELECT COUNT(*) AS total_cols,
               SUM(CASE WHEN comment IS NOT NULL
                         AND LENGTH(TRIM(comment)) > 5
                        THEN 1 ELSE 0 END) AS documented_cols
        FROM duckdb_columns()
        WHERE UPPER(table_name) = ?
        """,
        [tname],
    ).fetchone()
    total, documented = (row[0] or 0, row[1] or 0)
    if total == 0:
        d1 = 0
    elif documented / total >= 0.90:
        d1 = 3
    elif documented / total >= 0.50:
        d1 = 2
    elif documented / total > 0:
        d1 = 1
    else:
        d1 = 0
    result.dimensions.append(DimensionScore(
        "D1: Schema freshness", d1,
        notes=f"{documented}/{total} columns documented (local catalog)"
    ))

    # --- D2 / D3: from dbt manifest if provided (same logic as Snowflake path) ---
    d2 = d3 = 0
    if dbt_manifest:
        model_name = tname.lower()
        semantic_models = dbt_manifest.get("semantic_models", {})
        metrics = dbt_manifest.get("metrics", {})
        has_semantic = any(model_name in str(sm.get("model", "")).lower()
                           for sm in semantic_models.values())
        has_metric = any(model_name in str(m).lower() for m in metrics.values())
        d2 = 3 if (has_semantic and has_metric) else 2 if has_semantic else 1 if has_metric else 0
        nodes = dbt_manifest.get("nodes", {})
        tests = [n for n in nodes.values()
                 if n.get("resource_type") == "test"
                 and model_name in str(n.get("attached_node", ""))]
        d3 = 3 if len(tests) >= 5 else 2 if len(tests) >= 2 else 1 if len(tests) >= 1 else 0
    result.dimensions.append(DimensionScore(
        "D2: Semantic coverage", d2,
        notes="" if dbt_manifest else "Requires dbt manifest"))
    result.dimensions.append(DimensionScore(
        "D3: Test coverage", d3,
        notes="" if dbt_manifest else "Requires dbt manifest"))

    # --- D4 / D5 / D6: Snowflake platform features, unavailable locally ---
    for dim, note in [
        ("D4: Eval readiness", "local mode: requires Iceberg snapshot history"),
        ("D5: Governance scope", "local mode: requires Snowflake policy catalog"),
        ("D6: Lineage coverage", "local mode: requires account_usage.access_history"),
    ]:
        result.dimensions.append(DimensionScore(dim, 0, notes=note))

    return result


def print_active_customer_divergence(con) -> None:
    """The Chapter 1 'aha': four teams, four counts, one dataset."""
    rows = con.execute(
        "SELECT definition, active_customers "
        "FROM v_active_customer_divergence ORDER BY active_customers DESC"
    ).fetchall()
    reconciled = con.execute("SELECT COUNT(*) FROM fct_active_customers").fetchone()[0]

    print("\nOpsPulse: how many 'active customers' do we have?")
    print("=" * 55)
    for definition, count in rows:
        print(f"  {definition:<20} {count:>8,d}")
    print("-" * 55)
    print(f"  {'reconciled fact':<20} {reconciled:>8,d}   (fct_active_customers)")
    print("=" * 55)
    print("  Same data. Four honest definitions. Four different numbers.")
    print("  This is the problem a semantic layer exists to solve.\n")


def run_local_demo(duckdb_path: Optional[Path] = None) -> bool:
    """Tier-A demo: run the Chapter 1 divergence + score a real local table.

    Returns True if the local dataset was found and the demo ran.
    """
    path = duckdb_path or _default_duckdb_path()
    if not path.exists():
        return False
    try:
        import duckdb
    except ImportError:
        print("duckdb not installed — run: pip install -r setup/requirements-setup.txt")
        return False

    con = duckdb.connect(str(path), read_only=True)
    try:
        print(f"Tier A — live local demo against {path.name} (no account, no keys)")
        print_active_customer_divergence(con)
        # Score a real raw table: undocumented + ungoverned = the OpsPulse baseline.
        score_table_duckdb(con, "ERP_ORDERS").print_report()
    finally:
        con.close()
    return True


# --- Illustrative OpsPulse baseline (no live connection needed) ---

OPSPULSE_BASELINE = AIReadinessResult(
    table_fqn="OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS",
    dimensions=[
        DimensionScore("D1: Schema freshness",   1, notes="3/8 columns documented"),
        DimensionScore("D2: Semantic coverage",   0, notes="No semantic model yet"),
        DimensionScore("D3: Test coverage",       1, notes="not_null on customer_id only"),
        DimensionScore("D4: Eval readiness",      1, notes="Iceberg enabled; < 7 snapshots"),
        DimensionScore("D5: Governance scope",    1, notes="Row access policy on region_code"),
        DimensionScore("D6: Lineage coverage",    0, notes="No OpenLineage instrumentation"),
    ]
)


if __name__ == "__main__":
    # Prefer the live Tier-A demo (real data, no account). Falls back to the
    # illustrative baseline if the OpsPulse DuckDB file has not been generated.
    if not run_local_demo():
        print("No local OpsPulse dataset found "
              f"({_default_duckdb_path()}).")
        print("Generate it with:  python setup/opspulse_generator.py --target duckdb "
              "--out setup/opspulse.duckdb")
        print("\nShowing the illustrative OpsPulse baseline instead:")
        OPSPULSE_BASELINE.print_report()
