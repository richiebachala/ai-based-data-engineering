"""
Generate Snowflake Workspace notebooks for Ch3, Ch4, Ch5, Ch7.
Book: AI-Based Data Engineering (Packt)

Run:  python generate_ch3457_notebooks.py
"""

import json, os

BASE = os.path.dirname(os.path.abspath(__file__))


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _md(source: str, cell_id: str) -> dict:
    return {"cell_type": "markdown", "id": cell_id, "metadata": {}, "source": source}


def _py(source: str, cell_id: str, name: str) -> dict:
    return {
        "cell_type": "code", "id": cell_id,
        "metadata": {"language": "python", "name": name},
        "source": source, "outputs": [], "execution_count": None,
    }


def _sql(query: str, cell_id: str, var: str, name: str) -> dict:
    return {
        "cell_type": "code", "id": cell_id,
        "metadata": {"language": "sql", "name": name, "resultVariableName": var},
        "source": f"%%sql -r {var}\n{query}",
        "outputs": [], "execution_count": None,
    }


def _nb(cells: list) -> dict:
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.9.0"},
        },
        "cells": cells,
    }


def write_nb(path: str, nb: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
    print(f"  wrote {os.path.relpath(path, BASE)}")


# ──────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 1  Ch3 — Workflow Patterns
# ──────────────────────────────────────────────────────────────────────────────

def build_ch03():
    cells = []

    # ── Cell 1: title / intro ─────────────────────────────────────────────────
    cells.append(_md(
        "# Chapter 3 — Workflow Patterns for Data Engineering\n"
        "## AI-Based Data Engineering (Packt)\n\n"
        "Two of the five composable workflow patterns from Chapter 3:\n\n"
        "1. **Routing** — a classifier dispatches each pipeline alert to the specialist handler "
        "that matches its anomaly type. Uses `claude-haiku-4-5` for the narrow taxonomy task, "
        "`claude-sonnet-4-5` for deeper analysis.\n"
        "2. **Evaluator-Optimizer** — a generator produces an output, an evaluator scores it, "
        "and the generator refines based on feedback until the quality bar is met.\n\n"
        "**Prerequisites:** run `code/setup/opspulse_generator.py --target snowflake` to create "
        "the OpsPulse tables. The anomaly-alert SQL cell falls back to synthetic VALUES rows if "
        "`OPSPU.PUBLIC.PIPELINE_ALERTS` is absent.",
        "a1b2c3d4",
    ))

    # ── Cell 2: setup ─────────────────────────────────────────────────────────
    cells.append(_py(
        "from snowflake.snowpark.context import get_active_session\n"
        "import anthropic\n"
        "import json\n"
        "from enum import Enum\n"
        "from pydantic import BaseModel, Field\n\n"
        "session = get_active_session()\n"
        "client  = anthropic.Anthropic()\n"
        'print("Session and Anthropic client ready.")',
        "e5f6g7h8", "setup",
    ))

    # ── Cell 3: SQL — anomaly alerts (VALUES fallback) ────────────────────────
    cells.append(_sql(
        "-- PIPELINE_ALERTS is created by the OpsPulse generator.\n"
        "-- Using a VALUES fallback so this cell runs even without the generator.\n"
        "WITH synthetic_alerts (alert_id, table_fqn, alert_type, null_rate, minutes_late) AS (\n"
        "    SELECT column1::VARCHAR, column2::VARCHAR, column3::VARCHAR,\n"
        "           column4::FLOAT, column5::INT\n"
        "    FROM VALUES\n"
        "        ('ALT001', 'OPSPU.MARTS.FCT_SALES',            'volume_drop',      0.0,   0),\n"
        "        ('ALT002', 'OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS', 'freshness_breach', 0.0, 187),\n"
        "        ('ALT003', 'OPSPU.RAW.IOT_EVENTS',             'quality_failure',  0.041, 0),\n"
        "        ('ALT004', 'OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS', 'schema_change',    0.0,   0),\n"
        "        ('ALT005', 'OPSPU.MARTS.FCT_REVENUE',          'volume_drop',      0.0,   0)\n"
        ")\n"
        "SELECT * FROM synthetic_alerts;\n"
        "-- To use real data instead:\n"
        "-- SELECT alert_id, table_fqn, alert_type, null_rate, minutes_late\n"
        "-- FROM OPSPU.PUBLIC.PIPELINE_ALERTS LIMIT 20;",
        "i9j0k1l2", "anomaly_alerts", "load_anomaly_data",
    ))

    # ── Cell 4: markdown — Pattern 1 Routing ─────────────────────────────────
    cells.append(_md(
        "## Pattern 1: Routing\n\n"
        "The routing pattern uses a cheap, fast classifier to inspect each alert and dispatch "
        "it to the specialist handler that matches its anomaly type. "
        "The classifier returns a `TriageClassification` with:\n\n"
        "- `anomaly_type` — one of five canonical types\n"
        "- `confidence` — 0.0–1.0; below 0.70 the alert escalates to the fallback handler\n"
        "- `primary_signal` — the data point that drove the classification\n"
        "- `recommended_action` — first step for the on-call engineer\n\n"
        "**Key design choice:** the classifier uses `claude-haiku-4-5` (fast, cheap, narrow "
        "taxonomy task); specialist handlers use `claude-sonnet-4-5` (quality analysis). "
        "You only pay sonnet prices when the input is worth analyzing.",
        "m3n4o5p6",
    ))

    # ── Cell 5: Python — routing implementation ───────────────────────────────
    cells.append(_py(
        "# ── Types, classifier, handlers, dispatcher ────────────────────────────────\n\n"
        "class AnomalyType(str, Enum):\n"
        "    VOLUME_DROP      = 'volume_drop'\n"
        "    SCHEMA_CHANGE    = 'schema_change'\n"
        "    FRESHNESS_BREACH = 'freshness_breach'\n"
        "    QUALITY_FAILURE  = 'quality_failure'\n"
        "    LINEAGE_BREAK    = 'lineage_break'\n"
        "    UNKNOWN          = 'unknown'\n\n\n"
        "class TriageClassification(BaseModel):\n"
        "    anomaly_type:       AnomalyType\n"
        "    confidence:         float = Field(ge=0.0, le=1.0)\n"
        "    primary_signal:     str\n"
        "    recommended_action: str\n\n\n"
        "CLASSIFIER_SYSTEM = (\n"
        "    'You are a data reliability engineer triaging data pipeline alerts. '\n"
        "    'Classify anomalies into canonical types to route them to the correct '\n"
        "    'specialist handler. Never speculate beyond what the alert data supports. '\n"
        "    'When uncertain, use anomaly_type=unknown and set confidence below 0.5.'\n"
        ")\n\n\n"
        "def classify_alert(alert_payload: dict) -> TriageClassification:\n"
        "    \"\"\"Classifier step: uses claude-haiku-4-5 (fast, cheap, narrow task).\"\"\"\n"
        "    response = client.messages.create(\n"
        "        model='claude-haiku-4-5',\n"
        "        max_tokens=300,\n"
        "        system=CLASSIFIER_SYSTEM,\n"
        "        tools=[{\n"
        "            'name': 'classify',\n"
        "            'description': 'Classify the anomaly type.',\n"
        "            'input_schema': TriageClassification.model_json_schema(),\n"
        "        }],\n"
        "        tool_choice={'type': 'tool', 'name': 'classify'},\n"
        "        messages=[{'role': 'user', 'content': (\n"
        "            f'Alert payload: {json.dumps(alert_payload)}\\n\\n'\n"
        "            'Classification rules:\\n'\n"
        "            '- volume_drop: row count or record volume fell below threshold\\n'\n"
        "            '- schema_change: column added, removed, renamed, or type changed\\n'\n"
        "            '- freshness_breach: data not updated within the expected window\\n'\n"
        "            '- quality_failure: null rate, uniqueness, or referential integrity breach\\n'\n"
        "            '- lineage_break: upstream table or model failed to produce output\\n'\n"
        "            '- unknown: insufficient data to classify confidently'\n"
        "        )}],\n"
        "    )\n"
        "    tool_call = next(b for b in response.content if b.type == 'tool_use')\n"
        "    return TriageClassification(**tool_call.input)\n\n\n"
        "def handle_volume_drop(alert: dict, clf: TriageClassification) -> dict:\n"
        "    response = client.messages.create(\n"
        "        model='claude-sonnet-4-5', max_tokens=500,\n"
        "        system=(\n"
        "            'You are a data reliability engineer investigating row count drops. '\n"
        "            'Identify the most likely root cause and provide specific remediation '\n"
        "            'steps for a Snowflake/Airflow stack.'\n"
        "        ),\n"
        "        messages=[{'role': 'user', 'content': (\n"
        "            f'Alert: {json.dumps(alert)}\\n'\n"
        "            f'Classification: {clf.model_dump_json()}\\n\\n'\n"
        "            'Provide: root cause hypothesis, one verification query, remediation steps.'\n"
        "        )}],\n"
        "    )\n"
        "    return {'handler': 'volume_drop', 'analysis': response.content[0].text}\n\n\n"
        "def handle_quality_failure(alert: dict, clf: TriageClassification) -> dict:\n"
        "    response = client.messages.create(\n"
        "        model='claude-sonnet-4-5', max_tokens=500,\n"
        "        system=(\n"
        "            'You are a data reliability engineer investigating data quality failures. '\n"
        "            'Analyze null rate, uniqueness, or referential integrity issues and '\n"
        "            'recommend remediation.'\n"
        "        ),\n"
        "        messages=[{'role': 'user', 'content': (\n"
        "            f'Alert: {json.dumps(alert)}\\n\\n'\n"
        "            'Provide: quality dimension failing, root cause, fix.'\n"
        "        )}],\n"
        "    )\n"
        "    return {'handler': 'quality_failure', 'analysis': response.content[0].text}\n\n\n"
        "def handle_unknown(alert: dict, clf: TriageClassification) -> dict:\n"
        "    return {\n"
        "        'handler': 'escalation',\n"
        "        'analysis': 'Confidence below threshold. Escalated to on-call engineer.',\n"
        "        'classification': clf.model_dump(),\n"
        "    }\n\n\n"
        "ROUTE_MAP = {\n"
        "    AnomalyType.VOLUME_DROP:      handle_volume_drop,\n"
        "    AnomalyType.QUALITY_FAILURE:  handle_quality_failure,\n"
        "    AnomalyType.SCHEMA_CHANGE:    handle_unknown,\n"
        "    AnomalyType.FRESHNESS_BREACH: handle_unknown,\n"
        "    AnomalyType.LINEAGE_BREAK:    handle_unknown,\n"
        "    AnomalyType.UNKNOWN:          handle_unknown,\n"
        "}\n\n\n"
        "def triage_alert(alert_payload: dict) -> dict:\n"
        "    \"\"\"Full routing pipeline: classify → dispatch → analyze.\"\"\"\n"
        "    clf = classify_alert(alert_payload)\n"
        "    if clf.confidence < 0.70:\n"
        "        return handle_unknown(alert_payload, clf)\n"
        "    handler = ROUTE_MAP.get(clf.anomaly_type, handle_unknown)\n"
        "    result  = handler(alert_payload, clf)\n"
        "    result['classification'] = clf.model_dump()\n"
        "    return result\n\n\n"
        'print("Routing functions defined.")',
        "q7r8s9t0", "routing_impl",
    ))

    # ── Cell 6: Python — test the router ─────────────────────────────────────
    cells.append(_py(
        "# ── Test the router with sample alerts ─────────────────────────────────────\n\n"
        "test_alerts = [\n"
        "    {\n"
        "        'table': 'OPSPU.MARTS.FCT_SALES',\n"
        "        'check': 'row_count',\n"
        "        'row_count_today': 4_200,\n"
        "        'row_count_yesterday': 9_800,\n"
        "        'threshold_pct': 20,\n"
        "    },\n"
        "    {\n"
        "        'table': 'OPSPU.RAW.IOT_EVENTS',\n"
        "        'check': 'null_rate',\n"
        "        'column': 'device_timestamp',\n"
        "        'null_rate': 0.041,\n"
        "        'threshold': 0.02,\n"
        "    },\n"
        "]\n\n"
        "for alert in test_alerts:\n"
        "    print(f\"\\n{'='*60}\")\n"
        "    print(f\"Alert: {alert['table']} / {alert['check']}\")\n"
        "    result = triage_alert(alert)\n"
        "    clf    = result['classification']\n"
        "    print(f\"  Type:       {clf['anomaly_type']}\")\n"
        "    print(f\"  Confidence: {clf['confidence']:.0%}\")\n"
        "    print(f\"  Signal:     {clf['primary_signal']}\")\n"
        "    print(f\"  Handler:    {result['handler']}\")\n"
        "    if result['handler'] != 'escalation':\n"
        "        print(f\"  Analysis (preview):\\n{result.get('analysis', '')[:400]}\")",
        "u1v2w3x4", "test_router",
    ))

    # ── Cell 7: markdown — Pattern 2 ─────────────────────────────────────────
    cells.append(_md(
        "## Pattern 2: Evaluator-Optimizer\n\n"
        "The evaluator-optimizer terminates when an output meets the quality bar — "
        "or when the iteration cap is reached. Three steps:\n\n"
        "1. **Generate** — produce an initial output (a column description here)\n"
        "2. **Evaluate** — score the output against explicit criteria; return `passes` + `feedback`\n"
        "3. **Regenerate** — if `passes == False`, pass the feedback to the generator and retry\n\n"
        "**Why it matters for data engineering:** column descriptions that fail the quality bar "
        "produce misleading catalog entries. An LLM-as-judge inside the generation loop catches "
        "these failures before they reach production, without requiring a human reviewer on every column.",
        "y5z6a7b8",
    ))

    # ── Cell 8: Python — evaluator-optimizer ─────────────────────────────────
    cells.append(_py(
        "# ── Evaluator-Optimizer: column documentation loop ─────────────────────────\n\n"
        "class ColumnEval(BaseModel):\n"
        "    score:    int  = Field(ge=1, le=5, description='Quality score 1-5')\n"
        "    passes:   bool = Field(description='True if score >= 4')\n"
        "    feedback: str  = Field(description='One sentence of improvement guidance')\n\n\n"
        "def generate_description(column_name: str, data_type: str, table_name: str) -> str:\n"
        "    response = client.messages.create(\n"
        "        model='claude-haiku-4-5', max_tokens=100,\n"
        "        messages=[{'role': 'user', 'content': (\n"
        "            f\"Write a one-sentence business description for column '{column_name}' \"\n"
        "            f\"({data_type}) in table '{table_name}'. No jargon. No quotation marks.\"\n"
        "        )}],\n"
        "    )\n"
        "    return response.content[0].text.strip()\n\n\n"
        "def evaluate_description(column_name: str, description: str) -> ColumnEval:\n"
        "    response = client.messages.create(\n"
        "        model='claude-haiku-4-5', max_tokens=150,\n"
        "        tools=[{\n"
        "            'name': 'evaluate',\n"
        "            'description': 'Score a column description.',\n"
        "            'input_schema': ColumnEval.model_json_schema(),\n"
        "        }],\n"
        "        tool_choice={'type': 'tool', 'name': 'evaluate'},\n"
        "        messages=[{'role': 'user', 'content': (\n"
        "            f\"Score this description for '{column_name}': \\\"{description}\\\"\\n\"\n"
        "            'Criteria: clear, business-focused, no jargon, states what the column contains.\\n'\n"
        "            'Score: 5=excellent, 4=passes, 3=borderline, 1-2=fails.'\n"
        "        )}],\n"
        "    )\n"
        "    tool_call = next(b for b in response.content if b.type == 'tool_use')\n"
        "    return ColumnEval(**tool_call.input)\n\n\n"
        "def regenerate_with_feedback(\n"
        "    column_name: str, data_type: str, table_name: str,\n"
        "    prior: str, feedback: str,\n"
        ") -> str:\n"
        "    response = client.messages.create(\n"
        "        model='claude-haiku-4-5', max_tokens=100,\n"
        "        messages=[{'role': 'user', 'content': (\n"
        "            'Rewrite this description based on feedback.\\n'\n"
        "            f\"Column: '{column_name}' ({data_type}) in '{table_name}'\\n\"\n"
        "            f'Prior:    {prior}\\n'\n"
        "            f'Feedback: {feedback}\\n'\n"
        "            'Write an improved one-sentence description. No quotation marks.'\n"
        "        )}],\n"
        "    )\n"
        "    return response.content[0].text.strip()\n\n\n"
        "def evaluator_optimizer(\n"
        "    column_name: str, data_type: str, table_name: str,\n"
        "    max_iterations: int = 3,\n"
        ") -> str:\n"
        "    description = generate_description(column_name, data_type, table_name)\n"
        "    for i in range(max_iterations):\n"
        "        ev = evaluate_description(column_name, description)\n"
        "        print(f'  Iter {i+1}: score={ev.score}/5  passes={ev.passes}')\n"
        "        print(f'    {description}')\n"
        "        if ev.passes:\n"
        "            print('    Accepted.')\n"
        "            return description\n"
        "        print(f'    Feedback: {ev.feedback}')\n"
        "        description = regenerate_with_feedback(\n"
        "            column_name, data_type, table_name, description, ev.feedback\n"
        "        )\n"
        "    print('  Max iterations reached.')\n"
        "    return description\n\n\n"
        "# Run on three columns from fct_active_customers\n"
        "columns_to_document = [\n"
        "    ('customer_id',      'VARCHAR',      'FCT_ACTIVE_CUSTOMERS'),\n"
        "    ('region_code',      'VARCHAR',      'FCT_ACTIVE_CUSTOMERS'),\n"
        "    ('total_orders_30d', 'NUMBER(10,0)', 'FCT_ACTIVE_CUSTOMERS'),\n"
        "]\n\n"
        "print('Evaluator-Optimizer column documentation run\\n')\n"
        "final_descriptions = {}\n"
        "for col_name, col_type, tbl in columns_to_document:\n"
        "    print(f'Column: {col_name}')\n"
        "    final_descriptions[col_name] = evaluator_optimizer(col_name, col_type, tbl)\n"
        "    print()\n\n"
        "print('Final descriptions:')\n"
        "for col, desc in final_descriptions.items():\n"
        "    print(f'  {col}: {desc}')",
        "c9d0e1f2", "evaluator_optimizer",
    ))

    # ── Cell 9: SQL — schema context ──────────────────────────────────────────
    cells.append(_sql(
        "-- Schema context for the generated descriptions above\n"
        "SELECT\n"
        "    column_name,\n"
        "    data_type,\n"
        "    COALESCE(comment, '[no description]') AS comment\n"
        "FROM OPSPU.INFORMATION_SCHEMA.COLUMNS\n"
        "WHERE table_schema = 'MARTS'\n"
        "  AND table_name   = 'FCT_ACTIVE_CUSTOMERS'\n"
        "ORDER BY ordinal_position;",
        "g3h4i5j6", "schema_context", "load_schema_context",
    ))

    # ── Cell 10: summary ──────────────────────────────────────────────────────
    cells.append(_md(
        "## Summary\n\n"
        "| Pattern | When to use | Cost profile |\n"
        "|---|---|---|\n"
        "| **Routing** | Heterogeneous inputs requiring specialist handling | haiku triage, sonnet only when warranted |\n"
        "| **Evaluator-Optimizer** | Quality bar on generated outputs; human review too slow | 2–3× single-pass cost, avoids rework |\n\n"
        "The three remaining patterns from Chapter 3 — Parallelization, Orchestrator-Workers, "
        "and Agent loops — build on the same primitives. "
        "See `code/ch03_workflow_patterns/` for the full implementations.",
        "k7l8m9n0",
    ))

    return _nb(cells)


# ──────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 2  Ch4 — Structured Prompting
# ──────────────────────────────────────────────────────────────────────────────

def build_ch04():
    cells = []

    cells.append(_md(
        "# Chapter 4 — Structured Prompting\n"
        "## AI-Based Data Engineering (Packt)\n\n"
        "The **PTCF pattern** (Persona / Task / Context / Format) makes prompts "
        "version-controllable, diffable, testable, and composable.\n\n"
        "| Benefit | How |\n"
        "|---|---|\n"
        "| **Diffable** | `git diff` shows exactly what changed between prompt versions |\n"
        "| **Testable** | PromptFoo test cases (Section 4.4) evaluate against expected outputs |\n"
        "| **Composable** | Same `DataEngineeringPrompt` class builds SQL, docs, and triage prompts |\n"
        "| **API-enforced** | `tool_choice` + Pydantic guarantees valid JSON every time |\n\n"
        "**What you'll build:** a PTCF-structured SQL generator that takes a business question "
        "and OpsPulse schema context and returns a validated `SQLGenerationResult`.",
        "o1p2q3r4",
    ))

    cells.append(_py(
        "import anthropic\n"
        "import json\n"
        "from dataclasses import dataclass, field\n"
        "from typing import Optional\n"
        "from pydantic import BaseModel, Field\n\n"
        "client = anthropic.Anthropic()\n"
        'print("Anthropic client ready.")',
        "s5t6u7v8", "setup",
    ))

    cells.append(_md(
        "## The DataEngineeringPrompt Dataclass\n\n"
        "The five constraint-set elements address three failure modes: "
        "model hallucination, dialect mismatch, and underspecified output.\n\n"
        "| Element | Purpose |\n"
        "|---|---|\n"
        "| **Persona** | Scope, dialect, and authority constraints |\n"
        "| **Task** | The business question, grounded in OpsPulse schema |\n"
        "| **Context** | Structured JSON: schema, glossary, dialect notes |\n"
        "| **Format** | Exact output contract — keys, types, cardinality |\n"
        "| **Fallback** | What to return when context is insufficient |",
        "w9x0y1z2",
    ))

    cells.append(_py(
        "@dataclass\n"
        "class DataEngineeringPrompt:\n"
        "    \"\"\"\n"
        "    PTCF (Persona/Task/Context/Format) prompt builder.\n"
        "    Encodes prompt components as a dataclass so they are version-controlled,\n"
        "    diffable in git, and testable with PromptFoo (Section 4.4).\n"
        "    \"\"\"\n"
        "    persona:              str\n"
        "    task:                 str\n"
        "    context:              dict\n"
        "    output_format:        str\n"
        "    fallback_instruction: str = (\n"
        "        'If you cannot produce a valid answer with the provided context, return: '\n"
        "        '{\"error\": \"insufficient_context\", \"missing\": \"<describe what is missing>\"}'\n"
        "    )\n"
        "    chain_of_thought: bool = False\n\n"
        "    def to_system_message(self) -> str:\n"
        "        parts = [self.persona, self.fallback_instruction]\n"
        "        if self.chain_of_thought:\n"
        "            parts.insert(1, 'Think step by step before producing your final answer.')\n"
        "        return '\\n\\n'.join(parts)\n\n"
        "    def to_user_message(self) -> str:\n"
        "        return (\n"
        "            f'Task: {self.task}\\n\\n'\n"
        "            f'Context:\\n{json.dumps(self.context, indent=2)}\\n\\n'\n"
        "            f'Output format: {self.output_format}'\n"
        "        )\n\n"
        "    def to_messages(self) -> list[dict]:\n"
        "        return [{'role': 'user', 'content': self.to_user_message()}]\n\n\n"
        'print("DataEngineeringPrompt defined.")',
        "a3b4c5d6", "ptcf_dataclass",
    ))

    cells.append(_sql(
        "-- Real schema context from OpsPulse marts layer\n"
        "-- NOTE: requires OpsPulse generator (code/setup/opspulse_generator.py --target snowflake)\n"
        "SELECT\n"
        "    column_name,\n"
        "    data_type,\n"
        "    is_nullable,\n"
        "    COALESCE(comment, '') AS comment\n"
        "FROM OPSPU.INFORMATION_SCHEMA.COLUMNS\n"
        "WHERE table_schema = 'MARTS'\n"
        "  AND table_name   = 'FCT_ACTIVE_CUSTOMERS'\n"
        "ORDER BY ordinal_position;",
        "e7f8g9h0", "column_schema", "get_schema_context",
    ))

    cells.append(_py(
        "# Build a schema dict from the SQL result\n"
        "schema_rows = column_schema.to_pandas()\n"
        "schema = {\n"
        "    'table': 'OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS',\n"
        "    'columns': [\n"
        "        {\n"
        "            'name':        row['COLUMN_NAME'],\n"
        "            'type':        row['DATA_TYPE'],\n"
        "            'nullable':    row['IS_NULLABLE'] == 'YES',\n"
        "            'description': row['COMMENT'],\n"
        "        }\n"
        "        for _, row in schema_rows.iterrows()\n"
        "    ],\n"
        "}\n\n"
        "# Build the PTCF prompt for SQL generation\n"
        "prompt = DataEngineeringPrompt(\n"
        "    persona=(\n"
        "        'You are a senior Snowflake data engineer. '\n"
        "        'You write read-only SELECT queries in Snowflake SQL dialect. '\n"
        "        'You never reference tables not listed in the provided schema. '\n"
        "        'You never use DML, DDL, or CALL statements.'\n"
        "    ),\n"
        "    task='How many active customers are in each region, ordered by count descending?',\n"
        "    context={\n"
        "        'schema':        schema,\n"
        "        'dialect_notes': [\n"
        "            'Use CURRENT_DATE, not NOW() or GETDATE()',\n"
        "            \"Date arithmetic: DATEADD('day', -7, CURRENT_DATE)\",\n"
        "            'Case-insensitive string compare: ILIKE, not LIKE',\n"
        "            'Null-safe equality: IS NOT DISTINCT FROM, not =',\n"
        "        ],\n"
        "    },\n"
        "    output_format=(\n"
        "        'JSON with keys: '\n"
        "        'sql (string — valid Snowflake SELECT), '\n"
        "        'explanation (string — max 2 sentences), '\n"
        "        'confidence (string — high | medium | low)'\n"
        "    ),\n"
        "    chain_of_thought=True,\n"
        ")\n\n"
        "# Call claude-haiku-4-5 for a quick, low-cost first pass\n"
        "response = client.messages.create(\n"
        "    model='claude-haiku-4-5',\n"
        "    max_tokens=600,\n"
        "    system=prompt.to_system_message(),\n"
        "    messages=prompt.to_messages(),\n"
        ")\n"
        "raw_response = response.content[0].text\n"
        "print('System message (first 200 chars):')\n"
        "print(prompt.to_system_message()[:200])\n"
        "print('\\nRaw response from claude-haiku-4-5:')\n"
        "print(raw_response)",
        "i1j2k3l4", "build_and_call_ptcf",
    ))

    cells.append(_md(
        "## API-Enforced Structured Output with `tool_choice`\n\n"
        "The response above is unstructured text — valid JSON if the model cooperates, "
        "but fragile if it adds explanation prose around the JSON block.\n\n"
        "**API enforcement** uses `tool_choice={\"type\": \"tool\", \"name\": \"generate_sql\"}` "
        "to force exactly one valid tool call that deserializes directly into a Pydantic model. "
        "This eliminates string parsing entirely.\n\n"
        "The `SQLGenerationResult` model below is the output contract the API enforces.",
        "m5n6o7p8",
    ))

    cells.append(_py(
        "class SQLGenerationResult(BaseModel):\n"
        "    sql:           str       = Field(description='Valid Snowflake SELECT statement')\n"
        "    explanation:   str       = Field(description='What the query returns, max 2 sentences')\n"
        "    confidence:    str       = Field(description='One of: high, medium, low')\n"
        "    assumed_joins: list[str] = Field(default_factory=list, description='Inferred join conditions')\n\n\n"
        "# Call with tool_choice to get API-enforced structured output\n"
        "response = client.messages.create(\n"
        "    model='claude-haiku-4-5',\n"
        "    max_tokens=600,\n"
        "    system=prompt.to_system_message(),\n"
        "    tools=[{\n"
        "        'name': 'generate_sql',\n"
        "        'description': 'Generate a Snowflake SQL query answering the business question.',\n"
        "        'input_schema': SQLGenerationResult.model_json_schema(),\n"
        "    }],\n"
        "    tool_choice={'type': 'tool', 'name': 'generate_sql'},\n"
        "    messages=prompt.to_messages(),\n"
        ")\n\n"
        "tool_call = next(b for b in response.content if b.type == 'tool_use')\n"
        "result    = SQLGenerationResult(**tool_call.input)\n\n"
        "print(f'SQL:\\n{result.sql}\\n')\n"
        "print(f'Explanation: {result.explanation}')\n"
        "print(f'Confidence:  {result.confidence}')\n"
        "if result.assumed_joins:\n"
        "    print(f'Assumed joins: {result.assumed_joins}')",
        "q9r0s1t2", "structured_output",
    ))

    cells.append(_sql(
        "-- Execute the query the PTCF + tool_choice pipeline generated\n"
        "-- NOTE: requires OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS from the OpsPulse generator\n"
        "SELECT\n"
        "    region_code,\n"
        "    COUNT(*) AS active_count\n"
        "FROM OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS\n"
        "GROUP BY region_code\n"
        "ORDER BY active_count DESC;",
        "u3v4w5x6", "query_result", "exec_generated_sql",
    ))

    cells.append(_md(
        "## Summary\n\n"
        "| Technique | Benefit | Trade-off |\n"
        "|---|---|---|\n"
        "| **PTCF dataclass** | Version-controlled, testable prompts | More setup than an inline string |\n"
        "| **Chain-of-thought** | Better SQL for multi-join queries | +100–200 tokens per call |\n"
        "| **`tool_choice` enforcement** | Guaranteed valid JSON; no string parsing | Requires tool-use support |\n\n"
        "The PTCF pattern is composable: the same `DataEngineeringPrompt` class builds "
        "the column documentation prompt in Chapter 8 and the triage prompt in Chapter 3. "
        "See `code/ch04_structured_prompting/data_engineering_prompt.py` for the full "
        "implementation including PromptFoo test cases.",
        "y7z8a9b0",
    ))

    return _nb(cells)


# ──────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 3  Ch5 — Context Engineering
# ──────────────────────────────────────────────────────────────────────────────

def build_ch05():
    cells = []

    cells.append(_md(
        "# Chapter 5 — Context Engineering\n"
        "## AI-Based Data Engineering (Packt)\n\n"
        "Context engineering is the discipline of deciding *what* information to include "
        "in a prompt, in *what order*, and *how much* of it. The three levers are:\n\n"
        "1. **Source selection** — which of the six source categories is relevant to this query?\n"
        "2. **Chunking** — at what granularity do you split each source?\n"
        "3. **Budget management** — how do you fit the most relevant context within the token limit?\n\n"
        "**What you'll build:** a context assembler that pulls schema metadata, sample data, "
        "and table freshness signals from Snowflake, then passes the assembled context to "
        "`claude-haiku-4-5` for a grounded SQL generation call.\n\n"
        "**Prerequisites:** run `code/setup/opspulse_generator.py --target snowflake` for "
        "the OPSPU.MARTS tables.",
        "c1d2e3f4",
    ))

    cells.append(_py(
        "import anthropic\n"
        "import json\n"
        "from dataclasses import dataclass, field\n"
        "from typing import Optional\n"
        "from snowflake.snowpark.context import get_active_session\n\n"
        "session = get_active_session()\n"
        "client  = anthropic.Anthropic()\n"
        'print("Session and Anthropic client ready.")',
        "g5h6i7j8", "setup",
    ))

    cells.append(_sql(
        "-- Source 1: Schema / catalog metadata from INFORMATION_SCHEMA\n"
        "-- Authority: high  Freshness: on DDL change  Granularity: table-level\n"
        "SELECT\n"
        "    table_name,\n"
        "    column_name,\n"
        "    data_type,\n"
        "    COALESCE(comment, '') AS comment\n"
        "FROM OPSPU.INFORMATION_SCHEMA.COLUMNS\n"
        "WHERE table_schema = 'MARTS'\n"
        "ORDER BY table_name, ordinal_position;",
        "k9l0m1n2", "schema_metadata", "source1_schema",
    ))

    cells.append(_sql(
        "-- Source 2: Representative rows from the canonical active-customer table\n"
        "-- Authority: medium  Freshness: on data change  Granularity: row-level (3-5 rows)\n"
        "-- NOTE: returns empty result if FCT_ACTIVE_CUSTOMERS does not exist yet;\n"
        "--       run code/setup/opspulse_generator.py --target snowflake first.\n"
        "SELECT * FROM OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS LIMIT 5;",
        "o3p4q5r6", "sample_data", "source2_sample",
    ))

    cells.append(_sql(
        "-- Source 3: Table freshness signals (DDL-level approximation)\n"
        "-- last_altered reflects the most recent DDL or data operation.\n"
        "-- Relabeled as approx_ddl_lag to avoid overstating freshness precision.\n"
        "SELECT\n"
        "    table_name,\n"
        "    row_count,\n"
        "    last_altered\n"
        "FROM OPSPU.INFORMATION_SCHEMA.TABLES\n"
        "WHERE table_schema = 'MARTS'\n"
        "ORDER BY last_altered DESC;",
        "s7t8u9v0", "incident_context", "source3_freshness",
    ))

    cells.append(_py(
        "# ── ContextChunk dataclass + budget-aware assembler ─────────────────────────\n\n"
        "@dataclass\n"
        "class ContextChunk:\n"
        "    source:         str\n"
        "    source_type:    str   # schema | sample_data | freshness | incident | policy\n"
        "    content:        str\n"
        "    token_estimate: int  = 0\n"
        "    metadata:       dict = field(default_factory=dict)\n\n"
        "    def __post_init__(self):\n"
        "        # Rough estimate: 1 token ≈ 4 characters\n"
        "        self.token_estimate = max(1, len(self.content) // 4)\n\n\n"
        "def schema_rows_to_chunk(df) -> ContextChunk:\n"
        "    \"\"\"Convert INFORMATION_SCHEMA columns DataFrame to a ContextChunk.\"\"\"\n"
        "    lines = []\n"
        "    for tbl, grp in df.groupby('TABLE_NAME'):\n"
        "        lines.append(f'Table: OPSPU.MARTS.{tbl}')\n"
        "        for _, row in grp.iterrows():\n"
        "            desc = f\" — {row['COMMENT']}\" if row['COMMENT'] else ''\n"
        "            lines.append(f\"  {row['COLUMN_NAME']} ({row['DATA_TYPE']}){desc}\")\n"
        "        lines.append('')\n"
        "    return ContextChunk(\n"
        "        source='OPSPU.INFORMATION_SCHEMA.COLUMNS',\n"
        "        source_type='schema',\n"
        "        content='\\n'.join(lines),\n"
        "        metadata={'table_count': df['TABLE_NAME'].nunique()},\n"
        "    )\n\n\n"
        "def sample_rows_to_chunk(df, table_fqn: str) -> ContextChunk:\n"
        "    \"\"\"Convert sample rows DataFrame to a ContextChunk.\"\"\"\n"
        "    if df.empty:\n"
        "        return ContextChunk(source=table_fqn, source_type='sample_data',\n"
        "                            content=f'No sample rows available for {table_fqn}.')\n"
        "    cols  = list(df.columns[:6])  # cap at 6 columns to control token cost\n"
        "    lines = [', '.join(cols)]\n"
        "    for _, row in df.head(3).iterrows():\n"
        "        lines.append(', '.join(str(row[c]) for c in cols))\n"
        "    return ContextChunk(\n"
        "        source=table_fqn, source_type='sample_data',\n"
        "        content='\\n'.join(lines),\n"
        "        metadata={'rows_shown': min(3, len(df))},\n"
        "    )\n\n\n"
        "def freshness_rows_to_chunk(df) -> ContextChunk:\n"
        "    \"\"\"Convert table freshness DataFrame to a ContextChunk.\"\"\"\n"
        "    lines = ['Table freshness (last_altered — DDL approximation):']\n"
        "    for _, row in df.iterrows():\n"
        "        lines.append(\n"
        "            f\"  {row['TABLE_NAME']}: \"\n"
        "            f\"rows={row['ROW_COUNT']}, last_altered={row['LAST_ALTERED']}\"\n"
        "        )\n"
        "    return ContextChunk(\n"
        "        source='OPSPU.INFORMATION_SCHEMA.TABLES',\n"
        "        source_type='freshness',\n"
        "        content='\\n'.join(lines),\n"
        "    )\n\n\n"
        "def assemble_context(chunks: list, token_budget: int = 4_000) -> str:\n"
        "    \"\"\"Budget-aware context assembly. Fills highest-priority sources first.\"\"\"\n"
        "    assembled   = []\n"
        "    tokens_used = 0\n"
        "    for chunk in chunks:\n"
        "        if tokens_used + chunk.token_estimate > token_budget:\n"
        "            remaining = token_budget - tokens_used\n"
        "            print(f'  [budget] Skipping {chunk.source} '\n"
        "                  f'({chunk.token_estimate} tokens, {remaining} remaining)')\n"
        "            continue\n"
        "        assembled.append(\n"
        "            f'[{chunk.source_type.upper()}] {chunk.source}\\n{chunk.content}'\n"
        "        )\n"
        "        tokens_used += chunk.token_estimate\n"
        "    print(f'  [budget] Assembled {len(assembled)}/{len(chunks)} chunks, '\n"
        "          f'~{tokens_used} tokens')\n"
        "    return '\\n\\n---\\n\\n'.join(assembled)\n\n\n"
        'print("ContextChunk and assemble_context defined.")',
        "w1x2y3z4", "context_chunk_assembler",
    ))

    cells.append(_py(
        "# ── Assemble context from all three sources ─────────────────────────────────\n\n"
        "schema_df    = schema_metadata.to_pandas()\n"
        "sample_df    = sample_data.to_pandas()\n"
        "freshness_df = incident_context.to_pandas()\n\n"
        "schema_chunk    = schema_rows_to_chunk(schema_df)\n"
        "sample_chunk    = sample_rows_to_chunk(sample_df, 'OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS')\n"
        "freshness_chunk = freshness_rows_to_chunk(freshness_df)\n\n"
        "# Priority order: schema first (most authoritative), sample second, freshness third\n"
        "chunks = [schema_chunk, sample_chunk, freshness_chunk]\n"
        "print('Context chunks built:')\n"
        "for c in chunks:\n"
        "    print(f'  {c.source_type:12s} | {c.token_estimate:4d} tokens | {c.source}')\n\n"
        "print('\\nAssembling context (4,000-token budget):')\n"
        "assembled = assemble_context(chunks, token_budget=4_000)\n"
        "print(f'\\nAssembled context preview (first 600 chars):\\n{assembled[:600]}')",
        "a5b6c7d8", "assemble_context_sources",
    ))

    cells.append(_py(
        "# ── Grounded SQL generation with assembled context ──────────────────────────\n\n"
        "response = client.messages.create(\n"
        "    model='claude-haiku-4-5',\n"
        "    max_tokens=400,\n"
        "    system=(\n"
        "        'You are a senior Snowflake data engineer. '\n"
        "        'Generate read-only SELECT queries using ONLY the tables and columns '\n"
        "        'described in the provided context. Never reference tables outside the context.'\n"
        "    ),\n"
        "    messages=[{\n"
        "        'role': 'user',\n"
        "        'content': (\n"
        "            f'Context:\\n{assembled}\\n\\n'\n"
        "            'Question: How many active customers are in each region, '\n"
        "            'and what is the average 30-day order count per customer per region?\\n\\n'\n"
        "            'Return: one Snowflake SELECT query answering this question.'\n"
        "        ),\n"
        "    }],\n"
        ")\n\n"
        "print('Grounded response from claude-haiku-4-5:')\n"
        "print(response.content[0].text)",
        "e9f0g1h2", "grounded_sql_call",
    ))

    cells.append(_sql(
        "-- Rough token budget estimate per column metadata row\n"
        "-- 1 token ≈ 4 characters — guides how many columns fit in a given budget\n"
        "SELECT\n"
        "    column_name,\n"
        "    data_type,\n"
        "    COALESCE(comment, '')                                                   AS comment,\n"
        "    LENGTH(column_name || ' ' || data_type || ' ' || COALESCE(comment, '')) AS approx_chars,\n"
        "    ROUND(\n"
        "        LENGTH(column_name || ' ' || data_type || ' ' || COALESCE(comment, '')) / 4.0\n"
        "    )                                                                       AS approx_tokens\n"
        "FROM OPSPU.INFORMATION_SCHEMA.COLUMNS\n"
        "WHERE table_schema = 'MARTS'\n"
        "ORDER BY approx_tokens DESC\n"
        "LIMIT 10;",
        "i3j4k5l6", "token_estimates", "token_budget_estimate",
    ))

    cells.append(_md(
        "## Summary\n\n"
        "| Source category | Authority | Freshness | Chunking granularity |\n"
        "|---|---|---|---|\n"
        "| Schema metadata | High | On DDL change | Table-level |\n"
        "| Sample data | Medium | On data change | Row-level (3–5 rows) |\n"
        "| Table freshness | Medium | On DDL/data | Table-level |\n"
        "| dbt model artifacts | High | On dbt run | Model-level |\n"
        "| Incident history | High | Real-time | Ticket-level |\n"
        "| Policy documents | High | On policy change | Section-level |\n\n"
        "`assemble_context()` respects the token budget by processing chunks in priority order — "
        "the deterministic baseline. Chapter 5 also covers retrieval-augmented approaches "
        "(Cortex Search) for large knowledge bases where priority ordering is not sufficient. "
        "See `code/ch05_context_engineering/context_sources.py` for the full implementation "
        "including dbt and Cortex Search sources.",
        "m7n8o9p0",
    ))

    return _nb(cells)


# ──────────────────────────────────────────────────────────────────────────────
# NOTEBOOK 4  Ch7 — MCP Tools
# ──────────────────────────────────────────────────────────────────────────────

def build_ch07():
    cells = []

    cells.append(_md(
        "# Chapter 7 — Tool and Interface Engineering with MCP\n"
        "## AI-Based Data Engineering (Packt)\n\n"
        "This notebook shows the SQL patterns that power the three MCP servers in Chapter 7:\n\n"
        "- **`catalog_server`** — read-only schema context "
        "(tools: `get_table_schema`, `search_catalog`, `get_column_lineage`)\n"
        "- **`analytics_server`** — read-only aggregate queries against OpsPulse marts\n"
        "- **`operations_server`** — lineage and access-history queries\n\n"
        "**Note:** MCP servers are long-running processes that expose tools over the MCP wire "
        "protocol. They cannot run inside a notebook cell. This notebook shows the underlying "
        "Snowflake queries each tool executes, so you can verify, profile, and tune them "
        "independently of the server. The final cells demonstrate the ACI principle and "
        "provide local setup instructions.",
        "q1r2s3t4",
    ))

    cells.append(_md(
        "## The ACI Principle\n\n"
        "**ACI** (Agent-Computer Interface by design): every sentence in a tool's name, "
        "description, and parameter descriptions is a behavioral instruction to the model.\n\n"
        "- **Ambiguous documentation** → ambiguous model behavior\n"
        "- **Prescriptive documentation** → deterministic tool selection\n\n"
        "The `catalog_server` server-level instruction illustrates this:\n\n"
        "```\n"
        "\"Always call get_table_schema before generating SQL or proposing schema changes.\n"
        " The catalog is the authoritative source of column definitions.\"\n"
        "```\n\n"
        "This single instruction prevents the model from generating SQL from training "
        "knowledge — it always fetches current schema first. "
        "The SQL cells below are exactly what each tool executes on Snowflake.",
        "u5v6w7x8",
    ))

    cells.append(_sql(
        "-- catalog_server: get_table_schema('OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS')\n"
        "-- The MCP tool parses this result into a structured JSON response.\n"
        "-- ACI note: the tool description says 'ALWAYS call this before generating SQL'\n"
        "-- so the model never infers column names from training knowledge.\n"
        "SELECT\n"
        "    column_name,\n"
        "    data_type,\n"
        "    is_nullable,\n"
        "    COALESCE(comment, '[no description]') AS description\n"
        "FROM OPSPU.INFORMATION_SCHEMA.COLUMNS\n"
        "WHERE table_schema = 'MARTS'\n"
        "  AND table_name   = 'FCT_ACTIVE_CUSTOMERS'\n"
        "ORDER BY ordinal_position;",
        "y9z0a1b2", "table_schema_result", "catalog_get_schema",
    ))

    cells.append(_sql(
        "-- catalog_server: search_catalog('active customers') — LIKE fallback\n"
        "-- In production the tool calls a Cortex Search index for hybrid BM25+semantic ranking.\n"
        "-- This LIKE query is the fallback for environments without a Cortex Search service.\n"
        "SELECT\n"
        "    table_name,\n"
        "    table_type,\n"
        "    row_count,\n"
        "    COALESCE(comment, '') AS comment\n"
        "FROM OPSPU.INFORMATION_SCHEMA.TABLES\n"
        "WHERE table_schema = 'MARTS'\n"
        "  AND (table_name ILIKE '%customer%' OR table_name ILIKE '%active%')\n"
        "ORDER BY row_count DESC NULLS LAST;",
        "c3d4e5f6", "catalog_search_result", "catalog_search",
    ))

    cells.append(_sql(
        "-- analytics_server: safe read-only aggregate query\n"
        "-- The analytics_server enforces SELECT-only by validating the query before execution.\n"
        "-- NOTE: requires OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS from the OpsPulse generator.\n"
        "SELECT\n"
        "    region_code,\n"
        "    COUNT(*)              AS active_customers,\n"
        "    AVG(total_orders_30d) AS avg_orders_30d\n"
        "FROM OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS\n"
        "GROUP BY region_code\n"
        "ORDER BY active_customers DESC;",
        "g7h8i9j0", "analytics_result", "analytics_query",
    ))

    cells.append(_sql(
        "-- catalog_server: get_column_lineage for FCT_ACTIVE_CUSTOMERS\n"
        "-- Queries SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY (30-day window).\n"
        "-- Requires ACCOUNTADMIN or explicit SNOWFLAKE.ACCOUNT_USAGE read grant.\n"
        "-- Returns an empty result set if access is denied — no error.\n"
        "SELECT DISTINCT\n"
        "    user_name,\n"
        "    query_type,\n"
        "    DATE(query_start_time) AS query_date\n"
        "FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY\n"
        "WHERE query_text ILIKE '%FCT_ACTIVE_CUSTOMERS%'\n"
        "  AND query_start_time > DATEADD('day', -30, CURRENT_TIMESTAMP())\n"
        "ORDER BY query_date DESC\n"
        "LIMIT 20;",
        "k1l2m3n4", "lineage_result", "catalog_lineage",
    ))

    cells.append(_py(
        "from snowflake.snowpark.context import get_active_session\n"
        "import anthropic\n\n"
        "session = get_active_session()\n"
        "client  = anthropic.Anthropic()\n\n"
        "# The ACI principle: every description IS a behavioral instruction.\n"
        "# 'ALWAYS call this before generating SQL' forces schema fetch before SQL generation.\n"
        "tools = [\n"
        "    {\n"
        "        'name': 'get_table_schema',\n"
        "        'description': (\n"
        "            'Return column schema for a table. '\n"
        "            'ALWAYS call this before generating SQL or proposing schema changes. '\n"
        "            'Never infer column names or types from training knowledge — '\n"
        "            'the catalog is the authoritative source.'\n"
        "        ),\n"
        "        'input_schema': {\n"
        "            'type': 'object',\n"
        "            'properties': {\n"
        "                'table_fqn': {\n"
        "                    'type': 'string',\n"
        "                    'description': (\n"
        "                        'Fully-qualified table name: DB.SCHEMA.TABLE. '\n"
        "                        'Example: OPSPU.MARTS.FCT_ACTIVE_CUSTOMERS'\n"
        "                    ),\n"
        "                },\n"
        "            },\n"
        "            'required': ['table_fqn'],\n"
        "        },\n"
        "    },\n"
        "]\n\n"
        "response = client.messages.create(\n"
        "    model='claude-haiku-4-5',\n"
        "    max_tokens=300,\n"
        "    tools=tools,\n"
        "    messages=[{\n"
        "        'role': 'user',\n"
        "        'content': 'How many active customers are in the EMEA region?',\n"
        "    }],\n"
        ")\n\n"
        "if response.stop_reason == 'tool_use':\n"
        "    tool_use = next(b for b in response.content if b.type == 'tool_use')\n"
        "    print(f'Model called tool: {tool_use.name}')\n"
        "    print(f'Tool input:        {tool_use.input}')\n"
        "    print('\\nThe ACI principle is working: '\n"
        "          'the model fetched schema before generating SQL.')\n"
        "else:\n"
        "    print(f'Stop reason: {response.stop_reason}')\n"
        "    print(response.content[0].text[:300])",
        "o5p6q7r8", "aci_demo",
    ))

    cells.append(_md(
        "## Running the MCP Servers Locally\n\n"
        "Each server is a standalone Python script that exposes tools over the MCP wire protocol.\n\n"
        "**Prerequisites:**\n"
        "```bash\n"
        "pip install mcp anthropic snowflake-connector-python\n"
        "export SNOWFLAKE_ACCOUNT=<your-account>\n"
        "export SNOWFLAKE_USER=<your-user>\n"
        "export SNOWFLAKE_PASSWORD=<your-password>\n"
        "```\n\n"
        "**Start the catalog server:**\n"
        "```bash\n"
        "cd code/ch07_mcp_tools\n"
        "python catalog_server.py\n"
        "```\n\n"
        "**Claude Desktop configuration** "
        "(`~/Library/Application Support/Claude/claude_desktop_config.json`):\n"
        "```json\n"
        "{\n"
        "  \"mcpServers\": {\n"
        "    \"opspu-catalog\": {\n"
        "      \"command\": \"python\",\n"
        "      \"args\": [\"/path/to/code/ch07_mcp_tools/catalog_server.py\"]\n"
        "    }\n"
        "  }\n"
        "}\n"
        "```\n\n"
        "Once connected, Claude will automatically call `get_table_schema` before any SQL "
        "generation — the same behavior shown in the ACI demo cell above.",
        "s9t0u1v2",
    ))

    cells.append(_md(
        "## Summary\n\n"
        "The three MCP servers enforce four behavioral layers:\n\n"
        "| Layer | Server | What it prevents |\n"
        "|---|---|---|\n"
        "| **Schema grounding** | `catalog_server` | SQL hallucinated from training knowledge |\n"
        "| **Read-only analytics** | `analytics_server` | Accidental DML from a broad-permission agent |\n"
        "| **Lineage check** | `catalog_server` | Schema changes without impact assessment |\n"
        "| **Platform capabilities** | `catalog_server` | Agents calling endpoints that don't exist |\n\n"
        "The server-level `instructions=` string in `FastMCP` is the highest-priority behavioral "
        "constraint — it applies before any tool call and sets the model's operating context for "
        "the entire session. See `code/ch07_mcp_tools/` for the full three-server implementation.",
        "w3x4y5z6",
    ))

    return _nb(cells)


# ──────────────────────────────────────────────────────────────────────────────
# Write all four notebooks
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    targets = [
        (
            os.path.join(BASE, "ch03_workflow_patterns", "ch03_workflow_patterns.ipynb"),
            build_ch03(),
        ),
        (
            os.path.join(BASE, "ch04_structured_prompting", "ch04_structured_prompting.ipynb"),
            build_ch04(),
        ),
        (
            os.path.join(BASE, "ch05_context_engineering", "ch05_context_engineering.ipynb"),
            build_ch05(),
        ),
        (
            os.path.join(BASE, "ch07_mcp_tools", "ch07_mcp_tools.ipynb"),
            build_ch07(),
        ),
    ]
    print("Generating notebooks...")
    for path, nb in targets:
        write_nb(path, nb)
    print("Done.")
