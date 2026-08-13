from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.nvidia import Nvidia
from agno.team import Team, TeamMode
from agno.tracing import setup_tracing

from app.config import settings
from app.semantica_integration import (
    evaluate_rete_policy_guardrail,
    export_compliance_audit,
    query_knowledge_graph_precedents,
    shared_context,
)
from app.tools import (
    escalate_and_audit,
    load_demo_scenario,
    process_and_record,
    run_recovery_pipeline,
)

# Initialize database storage for Agno sessions, history, and traces
if settings.NEON_DB_URL and (settings.NEON_DB_URL.startswith("postgresql") or settings.NEON_DB_URL.startswith("postgres")):
    try:
        db = PostgresDb(db_url=settings.NEON_DB_URL)
        traces_db = PostgresDb(db_url=settings.NEON_DB_URL)
        setup_tracing(db=traces_db)
    except Exception as e:
        print(f"[Warning] DB initialization fallback: {e}")
        db = None
        traces_db = None
else:
    db = None
    traces_db = None

# Learning set to None to prevent background LLM extraction quota burn for JSON transactional operations
learning = None

# Initialize LLM model provider
if settings.NVIDIA_API_KEY:
    model = Nvidia(
        id=settings.NVIDIA_MODEL,
        api_key=settings.NVIDIA_API_KEY,
        max_tokens=2048,
    )
else:
    model = Nvidia(
        id="nvidia/nemotron-3.5-lightning-30b-a3b",
        max_tokens=2048,
    )

# Bind Semantica Shared Context to the recovery agent session using serializable state
shared_context.bind_agent("b2b-payment-recovery")
context_session_state = {"semantica_context_id": "b2b-payment-recovery"}


# ==========================================
# 1. Diagnostic Agent
# ==========================================
diagnostic_agent = Agent(
    id="diagnostic-agent",
    name="Payment Schema Diagnostic Agent",
    model=model,
    db=db,
    session_state=context_session_state,
    tools=[
        load_demo_scenario,
        query_knowledge_graph_precedents,
        run_recovery_pipeline,
    ],
    markdown=True,
    add_history_to_context=False, # Safety Guard: Prevents context inflation
    retries=0,                    # Safety Guard: Prevents infinite retry loops
    tool_call_limit=3,            # Hard Cap: Prevents infinite tool-calling loops
    instructions=[
        "## Role and Purpose",
        "You are the Payment Schema Diagnostic Agent. Your exclusive mission is to intercept malformed B2B payloads, diagnose schema drift, and secure a sandboxed repair plan.",
        "",
        "## Core Directives & Execution Loop",
        "1. **Load/Intercept:** If a scenario name is provided, use `load_demo_scenario` to fetch the raw payload.",
        "2. **Precedent Search:** Execute `query_knowledge_graph_precedents` using the scenario description to discover historically safe mappings.",
        "3. **Sandbox Healing:** Execute `run_recovery_pipeline` to test your repair plan. This tool validates the schema and generates a deterministic repair.",
        "",
        "## Strict Handoff Contract",
        "- **STOP** immediately after `run_recovery_pipeline` returns success.",
        "- Do NOT attempt to evaluate business policies. Do NOT attempt to process the order.",
        "- Output the exact `repaired_payload` JSON and `incident_id` directly to the Orchestrator so it can be passed to Compliance."
    ],
)


# ==========================================
# 2. Compliance Agent
# ==========================================
compliance_agent = Agent(
    id="compliance-agent",
    name="Financial Policy & Compliance Agent",
    model=model,
    db=db,
    session_state=context_session_state,
    tools=[
        evaluate_rete_policy_guardrail,
        export_compliance_audit,
        escalate_and_audit,
        process_and_record,
    ],
    markdown=True,
    add_history_to_context=False, # Safety Guard: Prevents context inflation
    retries=0,                    # Safety Guard: Prevents infinite retry loops
    tool_call_limit=3,            # Hard Cap: Prevents infinite tool-calling loops
    instructions=[
        "## Role and Purpose",
        "You are the Financial Policy & Compliance Agent. You act as the absolute regulatory gatekeeper. Your mission is to evaluate healed payloads against deterministic ReteEngine rules and generate W3C PROV-O audit trails.",
        "",
        "## Core Directives & Execution Loop",
        "1. **Policy Evaluation:** Upon receiving a repaired payload from the Orchestrator, immediately execute `evaluate_rete_policy_guardrail`.",
        "2. **Conditional Routing:**",
        "   - IF the ReteEngine returns COMPLIANT (safe): Execute `process_and_record` to clear the transaction.",
        "   - IF the ReteEngine returns VIOLATIONS (unsafe): Execute `escalate_and_audit` immediately. Do not attempt to force a bypass.",
        "3. **Audit Generation:** Regardless of success or escalation, you MUST execute `export_compliance_audit` to write the semantic decision trail to disk.",
        "",
        "## Strict Handoff Contract",
        "- Never override a ReteEngine failure.",
        "- Return the final transaction status (Processed or Escalated), the transaction ID, and the audit export path back to the Orchestrator."
    ],
)


# ==========================================
# 3. Swarm Orchestrator (Team)
# ==========================================
recovery_team = Team(
    id="b2b-payment-recovery-team",
    name="B2B Payment Recovery Team",
    mode=TeamMode.coordinate,
    model=model,
    db=db,
    members=[diagnostic_agent, compliance_agent],
    session_state=context_session_state,
    add_history_to_context=False, # Safety Guard: Prevents context inflation
    retries=0,                    # Safety Guard: Prevents infinite retry loops
    tool_call_limit=4,            # Hard Cap: 2 member delegations + summary
    markdown=True,
    debug_mode=False,
    instructions=[
        "## MISSION",
        "You are the Swarm Orchestrator. Route data flawlessly between your specialized agents and synthesize the final outcome.",
        "",
        "## RIGID SWARM PROTOCOL",
        "1. **Diagnosis:** Delegate the user's initial request to the `diagnostic-agent`. WAIT for it to finish.",
        "2. **Compliance Handoff:** Extract the `repaired_payload` and `incident_id` returned by the Diagnostic Agent. Delegate a NEW task to the `compliance-agent`, embedding that payload.",
        "3. **Executive Synthesis:** Once the Compliance Agent completes, YOU MUST STOP DELEGATING. Look at the JSON data and tool responses you have already received, and write the final report yourself.",
        "",
        "## STRICT CONSTRAINTS (ANTI-LOOP)",
        "- NEVER delegate to the `diagnostic-agent` to ask for descriptions, summaries, or explanations. Read the JSON it returned and write the summary yourself.",
        "- You have a strict limit of 2 delegations total per user request (1 to Diagnostic, 1 to Compliance).",
        "",
        "## OUTPUT FORMAT",
        "### 🛡️ Autonomous Recovery Report",
        "**Final Status:** [Processed | Escalated]",
        "**Diagnostic Findings:** [You write a 1 sentence summary of what was fixed based on the JSON differences]",
        "**Compliance & Audit:** [Pass/Fail] | [Audit Export Status]"
    ],
)

# Backwards compatibility alias
agent = recovery_team