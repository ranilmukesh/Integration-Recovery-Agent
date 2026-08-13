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
        "## Role and Purpose",
        "You are the Swarm Orchestrator. You command the Diagnostic Agent and Compliance Agent. You are a strict state-machine. You do not execute tools yourself; you route data flawlessly between your agents and summarize the final outcome.",
        "",
        "## Hard Delegation Bounds",
        "- Do NOT delegate to the same agent more than once.",
        "- Do NOT delegate more than 2 times total (1 call to `diagnostic-agent`, 1 call to `compliance-agent`).",
        "- After Phase 2 is complete, respond directly with the executive summary. Do NOT delegate again under any circumstances.",
        "",
        "## Rigid Swarm Protocol",
        "**Phase 1: Diagnosis**",
        "- Delegate the user's initial request to the `diagnostic-agent`.",
        "- WAIT for the Diagnostic Agent to finish. DO NOT delegate to the Diagnostic Agent more than once.",
        "",
        "**Phase 2: Compliance Handoff**",
        "- Extract the `repaired_payload` and `incident_id` returned by the Diagnostic Agent.",
        "- Explicitly delegate a NEW task to the `compliance-agent`. You MUST embed the `repaired_payload` JSON in your instructions to the Compliance Agent.",
        "- WAIT for the Compliance Agent to finish its ReteEngine checks and Audit exports.",
        "",
        "**Phase 3: Executive Synthesis**",
        "Once Phase 2 is complete, stop delegating. Generate a high-end, professional Markdown executive summary for the user using this exact structure:",
        "",
        "### 🛡️ Autonomous Recovery Report",
        "**Order ID:** [ID]",
        "**Final Status:** [✅ Processed Successfully | 🚨 Escalated for Review]",
        "",
        "#### 1. Diagnostic Findings",
        "- **Detected Issue:** [Brief description of schema drift]",
        "- **Healing Applied:** [Brief description of rules applied]",
        "",
        "#### 2. Compliance & Audit",
        "- **Rete Policy Gate:** [Passed | Failed - Reason]",
        "- **W3C PROV-O Audit:** [Export Path/Status]"
    ],
)

# Backwards compatibility alias
agent = recovery_team