# Chapter 3: Workflows vs Agents for Data Engineering
# Section: 3.1 Five composable workflow patterns — Orchestrator-Workers
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Orchestrator-Workers: the orchestrator LLM decomposes a complex task
into sub-tasks, dispatches them to worker LLMs, and synthesizes results.

The orchestrator uses judgment (moderate reasoning model).
Workers execute narrow, well-specified tasks (cheaper, faster models).

OpsPulse use case: lineage impact analysis
  Orchestrator (sonnet): decompose the column rename into affected tables
  Workers (haiku): assess impact on each table independently
  Synthesizer (sonnet): combine all assessments into one impact report
"""

import asyncio
import anthropic
from pydantic import BaseModel, Field
from typing import Optional
import json

client = anthropic.Anthropic()


# --- Data models ---

class SubTask(BaseModel):
    table_fqn:   str
    description: str  # what the worker should analyze

class DecomposedWork(BaseModel):
    change_description:  str
    affected_tables:     list[str]
    sub_tasks:           list[SubTask]
    requires_human_review: bool = False

class TableImpactAssessment(BaseModel):
    table_fqn:        str
    is_directly_affected: bool
    affected_columns: list[str]
    downstream_risk:  str    # "none" | "low" | "medium" | "high"
    remediation:      str

class ImpactReport(BaseModel):
    change_description:   str
    total_tables_analyzed: int
    tables_at_risk:       list[str]
    overall_risk:         str     # "none" | "low" | "medium" | "high"
    recommended_actions:  list[str]
    requires_human_review: bool


# --- Step 1: Orchestrator decomposes the task ---

def orchestrate_impact_analysis(
    table_fqn: str,
    proposed_change: str,
    all_downstream_tables: list[str],
) -> DecomposedWork:
    """
    Orchestrator: use judgment to identify which tables need assessment
    and define the sub-task for each worker.
    """
    response = client.messages.create(
        model="claude-sonnet-4-5",   # moderate reasoning for decomposition
        max_tokens=800,
        system=(
            "You are a data architect performing impact analysis. "
            "Decompose a schema change into specific assessment tasks for each "
            "potentially affected table. Focus on tables that JOIN or reference "
            "the changed column."
        ),
        tools=[{
            "name": "decompose",
            "description": "Decompose the change into worker sub-tasks.",
            "input_schema": DecomposedWork.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "decompose"},
        messages=[{"role": "user", "content": (
            f"Table being changed: {table_fqn}\n"
            f"Proposed change: {proposed_change}\n"
            f"All downstream tables: {json.dumps(all_downstream_tables)}"
        )}]
    )
    tool_call = next(b for b in response.content if b.type == "tool_use")
    return DecomposedWork(**tool_call.input)


# --- Step 2: Workers assess individual tables ---

def assess_single_table(
    table_fqn: str,
    sub_task_description: str,
    proposed_change: str,
) -> TableImpactAssessment:
    """
    Worker: assess impact on a single table. Uses haiku for speed + cost.
    Each worker has a clean, bounded context window.
    """
    response = client.messages.create(
        model="claude-haiku-4-5",   # cheap + fast for narrow single-table task
        max_tokens=400,
        system=(
            "You are a data impact analyst. Assess whether a specific schema change "
            "affects a single table. Be specific about which columns and why."
        ),
        tools=[{
            "name": "assess",
            "description": "Return the impact assessment for this table.",
            "input_schema": TableImpactAssessment.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "assess"},
        messages=[{"role": "user", "content": (
            f"Table to assess: {table_fqn}\n"
            f"Task: {sub_task_description}\n"
            f"Change: {proposed_change}"
        )}]
    )
    tool_call = next(b for b in response.content if b.type == "tool_use")
    return TableImpactAssessment(**tool_call.input)


async def _worker_async(
    sub_task: SubTask,
    proposed_change: str,
) -> TableImpactAssessment:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: assess_single_table(
            sub_task.table_fqn,
            sub_task.description,
            proposed_change,
        )
    )


# --- Step 3: Synthesizer merges assessments ---

def synthesize_impact_report(
    change_description: str,
    assessments: list[TableImpactAssessment],
    requires_human_review: bool,
) -> ImpactReport:
    """Synthesizer: merge all worker results into a final report."""
    at_risk = [a.table_fqn for a in assessments if a.downstream_risk != "none"]
    risk_levels = [a.downstream_risk for a in assessments]

    # Overall risk = worst single risk
    risk_order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    overall = max(risk_levels, key=lambda r: risk_order.get(r, 0), default="none")

    all_remediations = [a.remediation for a in assessments if a.remediation]
    return ImpactReport(
        change_description=change_description,
        total_tables_analyzed=len(assessments),
        tables_at_risk=at_risk,
        overall_risk=overall,
        recommended_actions=list(dict.fromkeys(all_remediations)),  # dedup order-preserving
        requires_human_review=requires_human_review or overall == "high",
    )


# --- Full orchestrator-workers pipeline ---

async def run_impact_analysis(
    table_fqn: str,
    proposed_change: str,
    downstream_tables: list[str],
) -> ImpactReport:
    """
    Full orchestrator-workers pipeline for impact analysis:
    1. Orchestrator decomposes the problem
    2. Workers assess each table in parallel
    3. Synthesizer produces the final report
    """
    # Step 1
    decomposed = orchestrate_impact_analysis(table_fqn, proposed_change, downstream_tables)

    # Step 2: workers run in parallel
    worker_tasks = [
        _worker_async(sub_task, proposed_change)
        for sub_task in decomposed.sub_tasks
    ]
    assessments = await asyncio.gather(*worker_tasks)

    # Step 3
    return synthesize_impact_report(
        proposed_change,
        list(assessments),
        decomposed.requires_human_review,
    )


if __name__ == "__main__":
    report = asyncio.run(run_impact_analysis(
        table_fqn="OPSPU.RAW.OPSPU_IOT_TELEMETRY",
        proposed_change="Rename column device_id to device_uuid",
        downstream_tables=[
            "OPSPU.STAGING.STG_IOT_EVENTS",
            "OPSPU.MARTS.FCT_DEVICE_ANOMALIES",
            "OPSPU.MARTS.DIM_DEVICES",
        ],
    ))
    print(f"Overall risk: {report.overall_risk}")
    print(f"Tables at risk: {report.tables_at_risk}")
    print(f"Human review required: {report.requires_human_review}")
    for action in report.recommended_actions:
        print(f"  • {action}")
