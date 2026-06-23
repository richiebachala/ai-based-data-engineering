# Chapter 3: Workflows vs Agents for Data Engineering
# Section: 3.2 Agent frameworks — CrewAI
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
CrewAI role-based team for automated data product documentation.

Use CrewAI when:
  - The task maps to distinct human organizational roles
  - The task sequence is known in advance
  - Role-based structure makes agent behavior predictable and auditable

This crew replicates the OpsPulse documentation workflow:
  1. Data Steward: classify columns for PII and sensitivity
  2. Documentation Writer: write dbt-format descriptions using the classification
"""

try:
    from crewai import Agent, Task, Crew, Process
    from crewai.tools import tool
except ImportError:
    raise ImportError("pip install crewai>=0.1")

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    raise ImportError("pip install langchain-anthropic>=0.1")

import json


# --- Tool stubs (replace with real Snowflake + catalog calls in production) ---

@tool("catalog_query_tool")
def catalog_query_tool(table_name: str) -> str:
    """Query the data catalog for column metadata for a table."""
    # STUB: replace with real INFORMATION_SCHEMA query
    return json.dumps([
        {"column_name": "device_id",    "data_type": "VARCHAR",  "comment": ""},
        {"column_name": "technician_id","data_type": "VARCHAR",  "comment": ""},
        {"column_name": "calibration_date", "data_type": "DATE", "comment": ""},
        {"column_name": "passed",        "data_type": "BOOLEAN", "comment": ""},
        {"column_name": "notes",         "data_type": "VARCHAR", "comment": ""},
    ])


@tool("pii_pattern_tool")
def pii_pattern_tool(column_names: str) -> str:
    """Detect PII patterns in a comma-separated list of column names."""
    # STUB: replace with real PII detection logic
    names = [c.strip() for c in column_names.split(",")]
    result = {}
    pii_keywords = ["name", "email", "phone", "address", "ssn", "technician"]
    for name in names:
        result[name] = any(kw in name.lower() for kw in pii_keywords)
    return json.dumps(result)


@tool("sample_data_tool")
def sample_data_tool(table_name: str) -> str:
    """Retrieve 3 sample rows from a table for documentation context."""
    # STUB: replace with real SELECT TOP 3 query
    return json.dumps([
        {"device_id": "D001", "technician_id": "T42", "calibration_date": "2025-03-01",
         "passed": True,  "notes": "Routine calibration"},
        {"device_id": "D002", "technician_id": "T15", "calibration_date": "2025-03-02",
         "passed": False, "notes": "Offset exceeded tolerance; recalibrated"},
    ])


# --- Agent definitions ---

data_steward = Agent(
    role="Data Steward",
    goal="Classify columns for PII, sensitivity, and business domain",
    backstory=(
        "You are the data governance lead for OpsPulse. You have deep knowledge "
        "of what constitutes PII under GDPR and CCPA, and how to classify "
        "data by sensitivity (public, internal, confidential, restricted)."
    ),
    tools=[catalog_query_tool, pii_pattern_tool],
    llm=ChatAnthropic(model="claude-sonnet-4-5"),
    verbose=False,
)

documentation_writer = Agent(
    role="Documentation Writer",
    goal="Write accurate, business-readable column descriptions for data products",
    backstory=(
        "You are a technical writer with 5 years of experience documenting "
        "data products for business and technical audiences. You make complex "
        "data definitions understandable without sacrificing precision."
    ),
    tools=[catalog_query_tool, sample_data_tool],
    llm=ChatAnthropic(model="claude-sonnet-4-5"),
    verbose=False,
)


# --- Task definitions ---

classify_task = Task(
    description=(
        "Classify every column in fct_inventory_exposure for PII sensitivity "
        "and business domain. Output a JSON array: "
        "[{column, pii: bool, sensitivity: str, domain: str}]"
    ),
    agent=data_steward,
    expected_output="JSON array of column classifications",
)

document_task = Task(
    description=(
        "Using the classifications from the previous task, write dbt-format "
        "column descriptions for all columns in fct_inventory_exposure. "
        "Include PII warnings where the steward flagged PII=true."
    ),
    agent=documentation_writer,
    context=[classify_task],      # receives classify_task's output as context
    expected_output="dbt YAML column descriptions block",
)


# --- Crew assembly ---

documentation_crew = Crew(
    agents=[data_steward, documentation_writer],
    tasks=[classify_task, document_task],
    process=Process.sequential,   # strict ordering: classify before document
)


if __name__ == "__main__":
    print("Running documentation crew for fct_inventory_exposure...")
    result = documentation_crew.kickoff()
    print("\n=== CREW OUTPUT ===")
    print(result)
