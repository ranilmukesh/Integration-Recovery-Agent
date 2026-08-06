from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserMemoryConfig, UserProfileConfig
from agno.models.nvidia import Nvidia
from agno.tracing import setup_tracing

from app.config import settings
from app.tools import (
    apply_repair_in_sandbox,
    escalate_incident,
    get_incident_audit,
    load_demo_scenario,
    lookup_repair_rules,
    process_order,
    propose_repair,
    record_incident,
    record_repair_attempt,
    save_approved_repair_rule,
    validate_business_rules_tool,
    validate_order_payload,
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

# Configure Learning Machine
if db:
    learning = LearningMachine(
        db=db,
        user_profile=UserProfileConfig(mode=LearningMode.ALWAYS),
        user_memory=UserMemoryConfig(mode=LearningMode.ALWAYS),
    )
else:
    learning = None

# Initialize LLM model provider
if settings.NVIDIA_API_KEY:
    model = Nvidia(
        id=settings.NVIDIA_MODEL,
        api_key=settings.NVIDIA_API_KEY
    )
else:
    model = Nvidia(id="nvidia/nemotron-3-ultra-550b-a55b")

# Build Integration Recovery Agent
agent = Agent(
    id="integration-recovery-agent",
    name="Integration Recovery Agent",
    model=model,
    db=db,
    tools=[
        load_demo_scenario,
        validate_order_payload,
        lookup_repair_rules,
        propose_repair,
        apply_repair_in_sandbox,
        validate_business_rules_tool,
        process_order,
        save_approved_repair_rule,
        record_incident,
        record_repair_attempt,
        escalate_incident,
        get_incident_audit,
    ],
    add_history_to_context=True,
    num_history_runs=3,
    stream_events=True,
    update_memory_on_run=False,
    enable_session_summaries=False,
    learning=learning,
    markdown=True,
    retries=1,
    delay_between_retries=10,
    exponential_backoff=True,
    debug_mode=True,
    instructions=[
        "You are the Integration Recovery Agent.",
        "",
        "Single-Pass Execution Rules:",
        "1. Execute the recovery workflow ONCE per user request. Do NOT reload a scenario or call load_demo_scenario more than once.",
        "2. Do NOT retry or re-invoke tools that have already returned success.",
        "3. Once process_order or escalate_incident succeeds and record_repair_attempt is called, provide the final concise summary and STOP immediately.",
        "",
        "Tool Calling & Data Formatting Rules:",
        "1. Pass all payloads, rules, and data to tools as NATIVE dictionaries/JSON objects. Do NOT use stringified JSON.",
        "2. If a tool call returns a syntax or formatting error, STOP and fix the structure. Do not blindly retry the same bad call.",
        "3. If you receive a rate limit or resource exhausted error, STOP immediately and inform the user. Do not retry.",
        "",
        "Demo mode:",
        "If the user asks to demonstrate, simulate, show, or run a scenario without providing a payload, call load_demo_scenario first.",
        "Never invent a demonstration payload when a named scenario can be loaded.",
        "After loading a demo scenario, execute the exact production recovery pipeline.",
        "Demo fixtures are not production orders, but all validation, repair, business-rule, idempotency, audit, and escalation rules still apply.",
        "",
        "Always validate the incoming order before processing it.",
        "The canonical fields are partner_id, order_id, customer_id, amount, currency, and payment_status.",
        "Partner aliases are invalid until repaired and revalidated.",
        "",
        "For a validation failure:",
        "1. Record the incident using record_incident.",
        "2. Search Neon for approved repair rules for this partner using lookup_repair_rules.",
        "3. If approved rules exist or if repair can be proposed using propose_repair, apply it in sandbox using apply_repair_in_sandbox.",
        "4. Revalidate the repaired payload with validate_order_payload.",
        "5. Validate business rules with validate_business_rules_tool.",
        "6. Process only after all checks pass using process_order.",
        "7. Record the repair attempt with record_repair_attempt.",
        "8. Save new rules using save_approved_repair_rule ONLY after successful sandbox validation and successful processing if rules were newly created.",
        "9. Retrieve the audit trail using get_incident_audit.",
        "",
        "Do not call process_order until validate_order_payload and validate_business_rules_tool both return success.",
        "Never process an order with amount <= 0.",
        "Never process a duplicate order without idempotency verification.",
        "Never invent unsupported transformations.",
        "Never claim success unless the processing tool returned success.",
        "Escalate ambiguity, unsafe amounts, unsupported values, failed retries, and duplicate conflicts using escalate_incident.",
        "",
        "After every tool call, briefly state the current business stage.",
        "Use these stage labels when appropriate: RECEIVED, VALIDATING, DIAGNOSING, LOOKING_UP_RULES, REPAIRING_IN_SANDBOX, VERIFYING, PROCESSING, LEARNED, ESCALATED, COMPLETE.",
        "At the end, provide a compact summary containing scenario, outcome, rules used, processing result, and escalation status.",
        "Use concise business-friendly explanations rather than exposing raw JSON unless requested."
    ],
)