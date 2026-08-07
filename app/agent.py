from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.nvidia import Nvidia
from agno.tracing import setup_tracing

from app.config import settings
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
        run_recovery_pipeline,
        process_and_record,
        escalate_and_audit,
    ],
    add_history_to_context=False, # Prevents context inflation
    learning=learning,           # Stops background quota burn
    retries=0,                   # Stops infinite retry loops
    markdown=True,
    debug_mode=True,
    instructions=[
        "You are the Integration Recovery Agent.",
        "Execute the recovery workflow ONCE per request using the provided macro tools.",
        "",
        "Workflow:",
        "1. If requested to run a demo without a payload, call `load_demo_scenario`.",
        "2. Call `run_recovery_pipeline` with the order payload. It will automatically validate, diagnose, lookup rules, and test sandbox repairs.",
        "3. If `run_recovery_pipeline` returns `ready: true`, call `process_and_record` with the repaired payload, incident_id, repair_plan, and save_new_rules boolean to complete the transaction.",
        "4. If `run_recovery_pipeline` returns `ready: false` or safety violations, call `escalate_and_audit` with incident_data and the reason.",
        "5. Stop immediately and provide a concise business summary once processing or escalation completes."
    ],
)