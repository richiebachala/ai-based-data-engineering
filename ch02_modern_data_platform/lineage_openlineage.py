# Chapter 2: The Modern Stack — Data + AI + Control Plane
# Section: 2.3 Catalogs and lineage as context infrastructure
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
OpenLineage event emission for OpsPulse pipelines.

Uses the OpenLineage Python client to register:
- Dataset inputs and outputs
- Run start / complete / fail events
- Job-level metadata

This is the lineage instrumentation pattern used throughout the book.
Chapter 8 builds on this for the documentation-as-byproduct pipeline.
"""

import os
import uuid
from datetime import datetime, timezone

from openlineage.client import OpenLineageClient
from openlineage.client.run import (
    RunEvent,
    RunState,
    Run,
    Job,
    Dataset,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_ingestion_lineage(
    run_id: str,
    source_path: str,
    target_table: str,
    namespace: str = "opspu",
) -> None:
    """
    Emit an OpenLineage COMPLETE event for a Snowflake ingestion job.

    Args:
        run_id:       UUID identifying this pipeline run
        source_path:  Stage or S3 path of the source file
        target_table: Target Snowflake table name (lowercase)
        namespace:    OpenLineage namespace (default: "opspu")
    """
    client = OpenLineageClient.from_environment()

    client.emit(RunEvent(
        eventType=RunState.COMPLETE,
        eventTime=_utc_now_iso(),
        run=Run(runId=run_id),
        job=Job(namespace=namespace, name=f"ingest.{target_table}"),
        inputs=[Dataset(
            namespace=f"file://{source_path.split('/')[2]}",   # bucket name as namespace
            name=source_path.rsplit("/", 1)[-1],
        )],
        outputs=[Dataset(
            namespace=f"snowflake://opspu/marts",
            name=target_table,
        )],
    ))


def emit_transformation_lineage(
    run_id: str,
    input_tables: list[str],
    output_table: str,
    job_name: str,
    namespace: str = "opspu",
) -> None:
    """
    Emit an OpenLineage COMPLETE event for a dbt transformation job.

    Args:
        run_id:        UUID for this run
        input_tables:  Source tables (lowercase names)
        output_table:  Output table (lowercase name)
        job_name:      dbt model name (e.g. "fct_active_customers")
        namespace:     OpenLineage namespace
    """
    client = OpenLineageClient.from_environment()

    client.emit(RunEvent(
        eventType=RunState.COMPLETE,
        eventTime=_utc_now_iso(),
        run=Run(runId=run_id),
        job=Job(namespace=namespace, name=job_name),
        inputs=[
            Dataset(namespace=f"snowflake://opspu/raw", name=t)
            for t in input_tables
        ],
        outputs=[
            Dataset(namespace=f"snowflake://opspu/marts", name=output_table)
        ],
    ))


def emit_failure(
    run_id: str,
    job_name: str,
    error_message: str,
    namespace: str = "opspu",
) -> None:
    """Emit an OpenLineage FAIL event with error metadata."""
    client = OpenLineageClient.from_environment()

    client.emit(RunEvent(
        eventType=RunState.FAIL,
        eventTime=_utc_now_iso(),
        run=Run(runId=run_id),
        job=Job(namespace=namespace, name=job_name),
        inputs=[],
        outputs=[],
    ))


if __name__ == "__main__":
    run_id = str(uuid.uuid4())
    print(f"Emitting test lineage event (run_id={run_id})")
    print("Set OPENLINEAGE_URL in .env to send to a real Marquez / Atlas instance.")
    print(f"OPENLINEAGE_URL={os.getenv('OPENLINEAGE_URL', 'not set')}")
