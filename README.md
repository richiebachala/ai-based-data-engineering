# AI-Based Data Engineering — Companion Code

Code repository for the Packt book *AI-Based Data Engineering*.

## Structure

| Folder | Chapter | Topics |
|--------|---------|--------|
| `ch01_foundations` | Chapter 1 | AI-readiness checklist, trust primitives, data product contracts |
| `ch02_modern_data_platform` | Chapter 2 | Iceberg, lineage, catalog context, MCP intro |
| `ch03_workflow_patterns` | Chapter 3 | Five composable patterns, LangGraph, AutoGen, CrewAI |
| `ch04_structured_prompting` | Chapter 4 | PTCF prompts, structured outputs, PromptFoo evals |
| `ch05_context_engineering` | Chapter 5 | Retrieval, context shaping, prompt caching, provenance |
| `ch06_graph_rag` | Chapter 6 | Knowledge graphs, Neo4j, GraphRAG search |
| `ch07_mcp_tools` | Chapter 7 | MCP servers: catalog, analytics, operations |
| `ch08_ingestion` | Chapter 8 | Profiling, document extraction, documentation pipeline |
| `ch09_sql_generation` | Chapter 9 | SQL generation, guardrails, self-healing pipeline |
| `ch10_orchestration` | Chapter 10 | Triage DAG, idempotency, approval gates |
| `ch11_observability` | Chapter 11 | Evals, tracing, drift detection, cost governance |
| `ch12_governance` | Chapter 12 | Content scanning, masking, stewardship workflow |
| `ch13_team_topology` | Chapter 13 | Use-case scoring, adoption patterns |
| `ch14_reference_architecture` | Chapter 14 | Reference architectures (prose + diagrams) |

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# edit .env with your keys
```

Required credentials:

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
SNOWFLAKE_PASSWORD=
SNOWFLAKE_WAREHOUSE=
SNOWFLAKE_DATABASE=
NEO4J_URI=
NEO4J_AUTH=
JIRA_URL=
JIRA_EMAIL=
JIRA_TOKEN=
```

## Running examples

Each chapter folder has a `README.md` explaining its files. Most Python scripts are
importable modules; some have a `__main__` block for standalone execution.

```bash
# Chapter 1: score your data estate
python ch01_foundations/ai_readiness_checklist.py

# Chapter 4: run a structured prompt
python ch04_structured_prompting/data_engineering_prompt.py

# Chapter 9: run the self-healing SQL pipeline
python ch09_sql_generation/self_healing_pipeline.py
```

## Notes

- Code snippets marked with `...` are illustrative stubs from the book text.
  Complete implementations are provided where the full code is shown in the book.
- All SQL examples target **Snowflake** syntax.
- All Python examples use **Python 3.10+**.
- The running case study is **OpsPulse** — a fictional global operational analytics platform.

## Book

*AI-Based Data Engineering* — Richie Bachala, Packt Publishing.
