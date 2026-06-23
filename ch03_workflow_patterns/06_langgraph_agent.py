# Chapter 3: Workflows vs Agents for Data Engineering
# Section: 3.2 Agent frameworks — LangGraph
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
LangGraph stateful agent for OpsPulse lineage impact analysis.

Use LangGraph when:
  - Partial graph structure can be predetermined
  - Intermediate state needs inspection
  - Human-in-the-loop checkpoints are required

This agent:
  1. Retrieves the table schema from the catalog
  2. Queries the lineage graph for downstream consumers
  3. Assesses impact on each consumer
  4. Pauses for human review if impact is HIGH

Tool call budget is enforced in state — not via a prompt instruction.
"""

from typing import TypedDict, Annotated, Literal
import anthropic
import operator

try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:
    raise ImportError("pip install langgraph>=0.2")

client = anthropic.Anthropic()


# --- State definition ---

class AgentState(TypedDict):
    table_fqn:        str
    proposed_change:  str
    schema_context:   str
    lineage:          list[str]       # downstream tables found
    assessments:      list[dict]
    tool_calls_used:  int
    max_tool_calls:   int             # hard budget (not a prompt instruction)
    risk_level:       str
    human_approved:   bool
    messages:         Annotated[list, operator.add]


# --- Tool stubs (replace with real MCP calls in production) ---

def _get_table_schema(table_fqn: str) -> str:
    # STUB: in production, call the catalog MCP server
    return f"Schema for {table_fqn}: device_id VARCHAR, event_time TIMESTAMP, signal_value FLOAT"


def _get_downstream_tables(table_fqn: str) -> list[str]:
    # STUB: in production, query Snowflake ACCESS_HISTORY or dbt manifest
    return [
        "OPSPU.STAGING.STG_IOT_EVENTS",
        "OPSPU.MARTS.FCT_DEVICE_ANOMALIES",
    ]


def _assess_table_impact(table_fqn: str, change: str) -> dict:
    # STUB: in production, call the orchestrator-workers pattern
    return {"table": table_fqn, "risk": "medium", "remediation": "Update JOIN key"}


# --- Graph nodes ---

def check_tool_budget(state: AgentState) -> Literal["continue", "budget_exceeded"]:
    """Conditional edge: route to budget_exceeded if limit is reached."""
    if state["tool_calls_used"] >= state["max_tool_calls"]:
        return "budget_exceeded"
    return "continue"


def fetch_schema(state: AgentState) -> dict:
    """Node: retrieve table schema from catalog."""
    schema = _get_table_schema(state["table_fqn"])
    return {
        "schema_context":   schema,
        "tool_calls_used":  state["tool_calls_used"] + 1,
        "messages":         [{"role": "system", "content": f"Schema retrieved: {schema[:100]}"}],
    }


def fetch_lineage(state: AgentState) -> dict:
    """Node: query lineage graph for downstream consumers."""
    downstream = _get_downstream_tables(state["table_fqn"])
    return {
        "lineage":          downstream,
        "tool_calls_used":  state["tool_calls_used"] + 1,
        "messages":         [{"role": "system", "content": f"Found {len(downstream)} downstream tables"}],
    }


def assess_impact(state: AgentState) -> dict:
    """Node: assess impact on each downstream table."""
    assessments = [
        _assess_table_impact(t, state["proposed_change"])
        for t in state["lineage"]
    ]
    risk_order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    overall_risk = max(assessments, key=lambda a: risk_order.get(a["risk"], 0))["risk"]
    return {
        "assessments":      assessments,
        "risk_level":       overall_risk,
        "tool_calls_used":  state["tool_calls_used"] + len(state["lineage"]),
        "messages":         [{"role": "system", "content": f"Overall risk: {overall_risk}"}],
    }


def human_review_checkpoint(state: AgentState) -> Literal["approved", "pending"]:
    """Conditional edge: pause for human approval if risk is high."""
    if state["risk_level"] == "high" and not state.get("human_approved", False):
        return "pending"
    return "approved"


def emit_report(state: AgentState) -> dict:
    """Node: emit the final impact report."""
    print(f"\n=== IMPACT REPORT ===")
    print(f"Change: {state['proposed_change']}")
    print(f"Overall risk: {state['risk_level']}")
    for a in state["assessments"]:
        print(f"  {a['table']}: {a['risk']} — {a['remediation']}")
    return {"messages": [{"role": "system", "content": "Report emitted"}]}


def handle_budget_exceeded(state: AgentState) -> dict:
    """Node: tool call budget exhausted — return partial result."""
    print(f"Tool call budget ({state['max_tool_calls']}) exceeded. Escalating to human.")
    return {
        "risk_level":  "unknown",
        "messages":    [{"role": "system", "content": "Budget exceeded; escalated"}],
    }


# --- Build the graph ---

def build_impact_analysis_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("fetch_schema",            fetch_schema)
    graph.add_node("fetch_lineage",           fetch_lineage)
    graph.add_node("assess_impact",           assess_impact)
    graph.add_node("emit_report",             emit_report)
    graph.add_node("handle_budget_exceeded",  handle_budget_exceeded)

    # Entry
    graph.set_entry_point("fetch_schema")

    # Budget check after each tool-using node
    graph.add_conditional_edges(
        "fetch_schema",
        check_tool_budget,
        {"continue": "fetch_lineage", "budget_exceeded": "handle_budget_exceeded"},
    )
    graph.add_conditional_edges(
        "fetch_lineage",
        check_tool_budget,
        {"continue": "assess_impact", "budget_exceeded": "handle_budget_exceeded"},
    )
    # Human-in-the-loop checkpoint after assessment
    graph.add_conditional_edges(
        "assess_impact",
        human_review_checkpoint,
        {"approved": "emit_report", "pending": END},   # pending = graph pauses for human
    )
    graph.add_edge("emit_report",             END)
    graph.add_edge("handle_budget_exceeded",  END)

    return graph


if __name__ == "__main__":
    graph = build_impact_analysis_graph()
    app   = graph.compile(checkpointer=MemorySaver())

    initial_state: AgentState = {
        "table_fqn":       "OPSPU.RAW.OPSPU_IOT_TELEMETRY",
        "proposed_change": "Rename device_id to device_uuid",
        "schema_context":  "",
        "lineage":         [],
        "assessments":     [],
        "tool_calls_used": 0,
        "max_tool_calls":  10,   # hard budget enforced in graph, not prompt
        "risk_level":      "",
        "human_approved":  False,
        "messages":        [],
    }

    config = {"configurable": {"thread_id": "impact-001"}}
    result = app.invoke(initial_state, config)
    print(f"Final risk level: {result['risk_level']}")
