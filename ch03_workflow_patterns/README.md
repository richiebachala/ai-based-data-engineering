# Chapter 3: Workflows vs Agents for Data Engineering
# Book: AI-Based Data Engineering (Packt)

## Files

| File | Description |
|------|-------------|
| `01_prompt_chaining.py` | Three-step column description chain (extract role → generate → validate). Async variant for parallel columns. |
| `02_routing.py` | Anomaly triage router: haiku classifier dispatches to specialist handlers per anomaly type |
| `03_parallelization.py` | Parallel column documentation (asyncio.gather) + voting ensemble for impact assessment |
| `04_orchestrator_workers.py` | Lineage impact analysis: sonnet orchestrator decomposes; haiku workers assess each table in parallel |
| `05_evaluator_optimizer.py` | Evaluator-optimizer loop for data quality check generation (generator=haiku, evaluator=sonnet) |
| `06_langgraph_agent.py` | LangGraph stateful agent with hard tool-call budget, human-in-the-loop checkpoint, conditional edges |
| `07_autogen_critic.py` | AutoGen two-agent SQL review (generator + critic). Bug fixed: `is_termination_msg` on `UserProxyAgent` |
| `08_crewai_roles.py` | CrewAI documentation crew: Data Steward classifies, Documentation Writer writes dbt YAML |

## Decision tree (Figure 3-1)

```
Single LLM call? → just call the API
  ↓ no
Output type varies by input? → Routing
  ↓ no
Task can be split into independent parts? → Parallelization
  ↓ no
Task requires a first draft + quality gate? → Evaluator-Optimizer
  ↓ no
Task requires decomposition into unknown sub-tasks? → Orchestrator-Workers
  ↓ no
Task requires dynamic tool choice? → Agent (LangGraph / AutoGen / CrewAI)
```

## Framework selection (Table 3-2)

| Framework | Best for | OpsPulse use |
|-----------|----------|--------------|
| LangGraph | Stateful graphs, conditional branching, HITL checkpoints | Lineage impact analysis |
| AutoGen/AG2 | Two-agent critique loops, conversational refinement | SQL review |
| CrewAI | Role-defined team simulations, sequential pipelines | Documentation automation |

## Bug fix: C3-1

`is_termination_msg` must be on `UserProxyAgent`, not `AssistantAgent`.
See `07_autogen_critic.py` for the corrected pattern.

## Bug fix: C3-2

The sequential loop in Section 3.1 is correctly labeled as sequential;
Parallel execution uses `asyncio.gather` as shown in `03_parallelization.py`.
