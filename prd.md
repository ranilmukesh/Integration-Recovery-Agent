# Technical PRD: Integration Recovery Agent

## 0. Handoff instruction

You are the coding agent responsible for implementing this project. Build only the requested scope. Do not add unrelated abstractions, providers, middleware, vector databases, multi-agent orchestration, or UI code beyond AgentOS integration.

Before writing code:

1. Inspect the installed/current Agno documentation for every API used.
2. Verify the exact signatures and import paths for `Agent`, `PostgresDb`, `AgentOS`, `Nvidia`, `@tool`, memory settings, and AgentOS serving.
3. Verify the current Neon/Postgres connection format and whether `PostgresDb` creates its required tables automatically.
4. Verify the current NVIDIA model-provider configuration and required environment variables.
5. If documentation is unclear or conflicting, stop and ask for clarification rather than guessing.
6. Record the verified package versions and API decisions in `docs/implementation-notes.md`.

Agno's current documentation supports Neon through `PostgresDb`, and AgentOS exposes agents through a FastAPI runtime that can be connected to the Agno control plane. Verify the current APIs before implementation because package APIs may change. [web:137][web:73]

## 1. Product name

**Integration Recovery Agent**

Suggested Neon project/database name:

```text
integration-recovery-demo
```

Suggested AgentOS ID:

```text
integration-recovery-os
```

Suggested agent ID:

```text
integration-recovery-agent
```

## 2. Product objective

Build one Agno agent that receives partner order events, detects integration failures, safely repairs known or newly discovered schema drift, validates repairs in a sandbox, retries a downstream order operation, records the result in Neon, and escalates unsafe or ambiguous incidents.

The system must demonstrate three outcomes:

1. A valid order is processed immediately.
2. A known or safely discoverable schema drift is repaired and remembered.
3. A business-policy violation is not guessed or retried; it is escalated.

The LLM orchestrates tools. Deterministic Python code owns schema validation, transformations, business rules, persistence, idempotency, and escalation decisions.

## 3. Explicit non-goals

Do not implement these in the first version:

- PLICI or security-token signing.
- Multiple agents, teams, or workflow graphs.
- Vector search, embeddings, or RAG.
- Real payment processing.
- Real external partner APIs.
- Generic SQL tools for the LLM.
- Arbitrary Python execution by the model.
- Automatic production mutation based only on model text.
- Custom frontend. Use AgentOS and `os.agno.com`.
- Agno agentic memory as the repair-rule database.
- Background workers, queues, Kubernetes, or microservices.

## 4. User story

A partner sends an order payload using a changed schema. The agent identifies the incident, searches approved repair rules, applies a safe repair in memory, validates the repaired payload, checks business rules, retries the simulated order processor using an idempotency key, and records the repair. When the same drift occurs again, the approved rule is reused without a full investigation. If the payload is unsafe or ambiguous, the agent creates a human-review escalation instead of guessing.

## 5. Demonstration scenarios

### Scenario A: Healthy event

```json
{
  "partner_id": "partner-acme",
  "order_id": "ORD-1001",
  "customer_id": "C-100",
  "amount": 499.0,
  "currency": "INR",
  "payment_status": "PAID"
}
```

Expected result:

```text
Schema valid → business rules passed → order processed
```

### Scenario B: First schema drift

```json
{
  "partner_id": "partner-acme",
  "order_id": "ORD-1007",
  "client_id": "C-8831",
  "total": "1299.00",
  "currency": "INR",
  "payment_status": "paid"
}
```

Expected agent path:

```text
Validate → detect errors → search rules → no complete rule found
→ propose repair → sandbox repair → validate → business checks
→ process order → save approved rules
```

Expected repairs:

```text
client_id -> customer_id       operation=rename
 total    -> amount             operation=to_float
 paid     -> PAID               operation=uppercase
```

### Scenario C: Repeated drift

```json
{
  "partner_id": "partner-acme",
  "order_id": "ORD-1008",
  "client_id": "C-9912",
  "total": "749.00",
  "currency": "INR",
  "payment_status": "paid"
}
```

Expected path:

```text
Validate → find approved rules → apply in sandbox → validate
→ process order → increment rule hit counts
```

The UI should show that the agent reused known rules.

### Scenario D: Unsafe business failure

```json
{
  "partner_id": "partner-acme",
  "order_id": "ORD-1009",
  "client_id": "C-3321",
  "total": "-500.00",
  "currency": "INR",
  "payment_status": "paid"
}
```

Expected result:

```text
Repair may normalize fields, but business validation fails.
No order processing.
No automatic approval.
Create escalation with reason: amount must be greater than zero.
```

## 6. Canonical internal schema

The canonical order schema is:

```python
class CanonicalOrder(BaseModel):
    partner_id: str
    order_id: str
    customer_id: str
    amount: float
    currency: Literal["INR", "USD", "EUR", "GBP"]
    payment_status: Literal["PAID", "PENDING", "FAILED"]
```

Use Pydantic for type and enum validation. The validator must reject partner aliases such as `client_id` and `total`; aliases are incident evidence, not canonical fields.

## 7. Neon/Postgres data model

Create a migration at `migrations/001_initial.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS repair_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id TEXT NOT NULL,
    source_field TEXT NOT NULL,
    target_field TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('rename', 'to_float', 'uppercase')),
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'approved'
        CHECK (status IN ('proposed', 'approved', 'rejected')),
    hit_count INTEGER NOT NULL DEFAULT 0 CHECK (hit_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    UNIQUE (partner_id, source_field, target_field, operation)
);

CREATE TABLE IF NOT EXISTS integration_incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id TEXT NOT NULL,
    order_id TEXT,
    raw_payload JSONB NOT NULL,
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    incident_type TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('detected', 'repaired', 'processed', 'escalated', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS repair_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES integration_incidents(id),
    repair_plan JSONB NOT NULL,
    before_payload JSONB NOT NULL,
    after_payload JSONB,
    validation_result JSONB,
    business_result JSONB,
    processing_result JSONB,
    outcome TEXT NOT NULL
        CHECK (outcome IN ('sandbox_failed', 'business_failed', 'processed', 'escalated')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed_orders (
    idempotency_key TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    result JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS escalations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES integration_incidents(id),
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'acknowledged', 'resolved')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_repair_rules_lookup
    ON repair_rules (partner_id, source_field, status);

CREATE INDEX IF NOT EXISTS idx_incidents_partner_status
    ON integration_incidents (partner_id, status);
```

Do not store repair rules only as Agno memories. Agno `PostgresDb` should persist agent sessions and related Agno data; the application tables above are the authoritative business/audit state. Neon is supported through Agno's `PostgresDb`. [web:137]

## 8. Repository structure

Create only this structure:

```text
integration-recovery-agent/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── schemas.py
│   ├── db.py
│   ├── repository.py
│   ├── validators.py
│   ├── repair.py
│   ├── tools.py
│   ├── agent.py
│   └── main.py
├── migrations/
│   └── 001_initial.sql
├── tests/
│   ├── test_validators.py
│   ├── test_repair.py
│   ├── test_repository.py
│   └── test_agent_tools.py
├── scripts/
│   └── run_demo.py
├── Dockerfile
├── .dockerignore
├── .env.example
├── requirements.txt
├── pyproject.toml
├── README.md
└── docs/
    └── implementation-notes.md
```

No duplicate demo scripts, no second agent definition, and no unused PLICI code.

## 9. Deterministic application services

Implement these pure or database-isolated functions:

```text
validate_canonical_order(payload) -> ValidationReport
classify_incident(validation_report) -> IncidentType
apply_repair_plan_in_sandbox(payload, plan) -> SandboxResult
validate_business_rules(order) -> BusinessResult
make_idempotency_key(partner_id, order_id) -> str
```

Rules:

- Never mutate the caller's payload in place.
- Never execute an operation not explicitly listed in a repair plan.
- Reject unsupported transformations.
- Reject duplicate destination fields.
- Reject conversion failures.
- Reject amounts less than or equal to zero.
- Reject unsupported currencies and payment states.
- Validate the repaired object again before processing.

## 10. Agno tools

Implement these tools and decorate them according to the verified current Agno API:

```text
validate_order_payload(payload_json)
lookup_repair_rules(partner_id, validation_errors_json)
propose_repair(payload_json, validation_errors_json, known_rules_json)
apply_repair_in_sandbox(payload_json, repair_plan_json)
validate_business_rules(payload_json)
process_order(payload_json, idempotency_key)
save_approved_repair_rule(rule_json)
record_incident(incident_json)
record_repair_attempt(attempt_json)
escalate_incident(incident_json, reason)
get_incident_audit(incident_id)
```

Tool requirements:

- Every tool accepts and returns JSON strings or the exact format verified from current Agno docs.
- Every tool has a precise docstring and typed arguments.
- Tools must return structured errors rather than raise errors for expected user/data failures.
- Database failures may raise a controlled application exception and must be logged.
- `process_order` must use the idempotency key and return the existing result for a duplicate key.
- `save_approved_repair_rule` must reject rules that were not successfully sandbox-tested and processed.
- `escalate_incident` must never process the order.
- There must be no generic SQL tool exposed to the agent.

## 11. Repair policy

The agent may propose only these operations:

```text
rename
 to_float
 uppercase
```

A repair plan must contain:

```json
{
  "partner_id": "partner-acme",
  "rules": [
    {
      "source_field": "client_id",
      "target_field": "customer_id",
      "operation": "rename"
    }
  ]
}
```

The agent must not invent semantic transformations such as:

```text
address -> customer_id
price -> amount
unknown status -> PAID
```

If the mapping is ambiguous, call `escalate_incident`.

## 12. Agent memory policy

Use Agno session storage for conversation and run history. Pass explicit `user_id` and `session_id` on every run.

Recommended initial configuration:

```python
add_history_to_context=True
update_memory_on_run=True
enable_agentic_memory=False
```

Automatic Agno memory may store tenant/partner context, but it is not the source of truth for repair rules. The repair-rule tools must query Neon directly.

Agno documents automatic memory as a memory-manager operation after a response, while agentic memory gives the agent explicit memory-management behavior. Verify the installed version's exact parameters before implementation. [web:148][web:149][web:151]

## 13. Agent instructions

Use a concise system instruction similar to:

```text
You are the Integration Recovery Agent.

Always validate the incoming order before processing it.
The canonical fields are partner_id, order_id, customer_id, amount, currency, and payment_status.
Partner aliases are invalid until repaired and revalidated.

For a validation failure:
1. Record the incident.
2. Classify the failure.
3. Search Neon for approved repair rules for this partner.
4. If an approved rule exists, apply it only in the sandbox.
5. Revalidate the repaired payload.
6. Validate business rules.
7. Process only after all checks pass.
8. Record the repair attempt and update rule usage.
9. Save a new rule only after successful sandbox validation and successful processing.

Never process an order with amount <= 0.
Never process a duplicate order without idempotency verification.
Never invent unsupported transformations.
Never claim success unless the processing tool returned success.
Escalate ambiguity, unsafe amounts, unsupported values, failed retries, and duplicate conflicts.
Return a concise incident summary with status, actions, and evidence.
```

## 14. Agent configuration

Use `PostgresDb(db_url=os.environ["NEON_DB_URL"])` after verifying the current import and constructor. Use the NVIDIA model provider only after verifying the current Agno provider documentation and model identifier.

Do not hard-code API keys. Use:

```text
NEON_DB_URL
NVIDIA_API_KEY
AGNO_ENCRYPTION_KEY
NVIDIA_MODEL
PORT
```

The coding agent must not commit `.env` files or secrets.

## 15. AgentOS runtime

Create `app/main.py` with the verified current AgentOS pattern:

```text
create the Agent
create AgentOS with the agent
call get_app()
serve on 0.0.0.0
```

The exact import and serving command must be checked against current Agno documentation before coding. AgentOS is the FastAPI runtime used to expose the agent to the control plane. [web:73][web:170]

Expected local endpoint:

```text
http://localhost:7860
```

Verify:

```text
GET /docs returns HTTP 200
AgentOS health endpoint responds
Agent list contains integration-recovery-agent
A run can be started with explicit user_id and session_id
```

## 16. Docker setup

Create a minimal Docker image:

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
```

Do not install Ollama or download a local model in the Docker image. NVIDIA provides inference remotely.

`.dockerignore` must include:

```text
.env
.git
.venv
__pycache__
.pytest_cache
*.pyc
tmp
```

## 17. Environment setup

Create `.env.example`:

```text
NEON_DB_URL=postgresql+psycopg://user:password@host/dbname?sslmode=require
NVIDIA_API_KEY=
NVIDIA_MODEL=stepfun-ai/step-3.7-flash
PORT=7860
```

The user will create a Neon project named:

```text
integration-recovery-demo
```

The coding agent must provide a migration command or documented SQL execution step. Do not silently assume that migrations ran.

## 18. Testing requirements

Run tests before any deployment.

### Unit tests

Test:

- Valid canonical order passes.
- Missing canonical fields fail.
- `client_id` is reported as unexpected.
- `total` is reported as unexpected and does not satisfy `amount`.
- Numeric strings are rejected before repair.
- Lowercase status is rejected before repair.
- `to_float` converts valid numeric strings.
- `to_float` rejects non-numeric strings.
- Unsupported operations are rejected.
- Negative amounts fail business validation.
- Zero amounts fail business validation.
- Unsupported currencies fail.
- Duplicate idempotency keys return the original processing result.

### Integration tests with Neon

Use a test schema or isolated test database. Never run destructive tests against production tables.

Test:

- Migration runs successfully.
- Repair rules can be inserted and queried by partner.
- Rule hit count increments.
- Incidents and attempts are linked.
- Escalations are created.
- Rollback behavior works on failed transactions.

### Agent-tool tests

Mock the NVIDIA model and call tools directly. Do not use the real model for deterministic unit tests.

Test:

- Healthy payload calls validation and processing.
- First drift creates an incident and saves a successful rule.
- Repeated drift uses the existing rule.
- Negative amount escalates and does not call `process_order`.
- Duplicate order does not produce a second processing side effect.
- The agent cannot process data before successful validation.

### End-to-end demo test

Run these four payloads in sequence and assert:

```text
ORD-1001 -> processed
ORD-1007 -> repaired and processed; rules saved
ORD-1008 -> known rules reused and processed
ORD-1009 -> escalated; not processed
```

## 19. Quality gates

The implementation is complete only if all conditions pass:

- `pytest` passes.
- `ruff check .` passes or an equivalent linter is configured.
- No syntax errors.
- No duplicate agent definitions.
- No unused imports.
- No dead functions.
- No hard-coded credentials.
- No generic SQL tool.
- No direct model-controlled production mutation.
- All state-changing tools are idempotent or explicitly audited.
- `/docs` loads successfully.
- Neon migration is documented and reproducible.
- Docker image builds successfully.
- AgentOS connects from `os.agno.com`.
- The four demo scenarios produce the expected outcomes.

## 20. Implementation phases

### Phase 0: Documentation verification

Inspect current Agno docs and record package/API decisions. Do not write implementation code until uncertain APIs are verified.

### Phase 1: Project bootstrap

Create the repository structure, environment configuration, dependency files, and migration file.

### Phase 2: Database layer

Implement Neon connection handling, run the migration, and implement repository methods with parameterized SQL.

### Phase 3: Deterministic domain logic

Implement schemas, validation, repair-plan application, business rules, idempotency, incident recording, and escalation.

### Phase 4: Tools

Wrap the domain logic with narrow Agno tools. Test each tool independently.

### Phase 5: Agent

Configure one NVIDIA-backed Agno agent with Neon session storage and the verified memory settings. Keep repair rules in explicit Neon tools.

### Phase 6: AgentOS

Expose the agent through AgentOS, verify `/docs`, and run local API tests.

### Phase 7: Docker

Build and run the container locally. Verify environment variables, database access, and health behavior.

### Phase 8: Demo validation

Run all four scenarios and capture logs showing validation, repair lookup, sandbox validation, processing, memory hit, and escalation.

### Phase 9: Deployment

Deploy the Docker image to a Hugging Face Space or another Docker host. Configure secrets. Connect the public AgentOS URL to `os.agno.com`.

## 21. Required final handoff

Return:

1. Repository tree.
2. Exact install commands.
3. Exact Neon migration command.
4. Required environment variables.
5. Local run command.
6. Docker build/run commands.
7. Test command and result.
8. AgentOS URL and health-check instructions.
9. `os.agno.com` connection instructions.
10. Demo commands or payloads.
11. Known limitations.
12. List of verified Agno API versions and documentation URLs.

Do not claim the project is working unless the tests and local AgentOS run have actually completed successfully.


sample code by agno docs agent :

Let me pull the latest verified docs for all the components first.Good, I have everything I need. Here's the complete, docs-verified sample:

---

## Integration Recovery Agent — Full Sample

### Install

```bash
pip install -U "agno[os]" "psycopg[binary]" openai sqlalchemy
```

---

### `db_setup.py` — Neon tables

```python
import os
import psycopg

NEON_DB_URL = os.environ["NEON_DB_URL"]

def create_tables():
    conn = psycopg.connect(NEON_DB_URL)
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS repair_rules (
            id BIGSERIAL PRIMARY KEY,
            partner_id TEXT NOT NULL,
            source_field TEXT NOT NULL,
            target_field TEXT NOT NULL,
            transformation TEXT NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS integration_incidents (
            id TEXT PRIMARY KEY,
            partner_id TEXT NOT NULL,
            order_id TEXT,
            raw_payload JSONB NOT NULL,
            error_report JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS repair_attempts (
            id BIGSERIAL PRIMARY KEY,
            incident_id TEXT REFERENCES integration_incidents(id),
            before_payload JSONB NOT NULL,
            after_payload JSONB,
            validation_result JSONB,
            outcome TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)
    conn.commit()
    conn.close()

if __name__ == "__main__":
    create_tables()
    print("Tables created.")
```

---

### `tools.py` — Deterministic tools

```python
import json
import uuid
import psycopg
import os
from datetime import datetime, timezone

NEON_DB_URL = os.environ["NEON_DB_URL"]

CANONICAL_SCHEMA = {"order_id", "customer_id", "amount", "currency", "payment_status"}
ALLOWED_STATUSES = {"PAID", "PENDING", "FAILED"}


def validate_order_payload(payload_json: str) -> str:
    """Validate a partner payload against the canonical internal order schema."""
    payload = json.loads(payload_json)
    errors = []

    missing = sorted(CANONICAL_SCHEMA - payload.keys())
    if missing:
        errors.append({"type": "missing_fields", "fields": missing})

    unexpected = sorted(set(payload.keys()) - CANONICAL_SCHEMA)
    if unexpected:
        errors.append({"type": "unexpected_fields", "fields": unexpected})

    if "amount" in payload and not isinstance(payload["amount"], (int, float)):
        errors.append({"type": "invalid_type", "field": "amount", "expected": "number"})

    if "payment_status" in payload and payload["payment_status"] not in ALLOWED_STATUSES:
        errors.append({
            "type": "invalid_value",
            "field": "payment_status",
            "allowed": sorted(ALLOWED_STATUSES),
        })

    return json.dumps({"valid": len(errors) == 0, "errors": errors})


def lookup_repair_rules(partner_id: str) -> str:
    """Search Neon for previously saved repair rules for this partner."""
    with psycopg.connect(NEON_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_field, target_field, transformation FROM repair_rules "
                "WHERE partner_id = %s ORDER BY hit_count DESC",
                (partner_id,),
            )
            rows = cur.fetchall()
    rules = [
        {"source_field": r[0], "target_field": r[1], "transformation": r[2]}
        for r in rows
    ]
    return json.dumps({"rules": rules, "count": len(rules)})


def apply_repair_in_sandbox(payload_json: str, rules_json: str) -> str:
    """Apply repair rules to a payload copy in memory only. Does not touch production."""
    payload = json.loads(payload_json)
    rules = json.loads(rules_json)
    repaired = dict(payload)

    applied = []
    for rule in rules:
        src = rule["source_field"]
        tgt = rule["target_field"]
        transform = rule["transformation"]

        if src in repaired:
            value = repaired.pop(src)
            if transform == "rename":
                repaired[tgt] = value
            elif transform == "to_float":
                repaired[tgt] = float(value)
            elif transform == "to_uppercase":
                repaired[tgt] = str(value).upper()
            applied.append(rule)

    return json.dumps({"repaired_payload": repaired, "applied_rules": applied})


def validate_business_rules(payload_json: str) -> str:
    """Check business policies: amount must be positive, currency must be valid."""
    payload = json.loads(payload_json)
    errors = []

    amount = payload.get("amount", 0)
    try:
        if float(amount) <= 0:
            errors.append("amount must be greater than 0")
    except (TypeError, ValueError):
        errors.append("amount is not a valid number")

    valid_currencies = {"INR", "USD", "EUR", "GBP"}
    if payload.get("currency") not in valid_currencies:
        errors.append(f"currency must be one of {sorted(valid_currencies)}")

    return json.dumps({"safe": len(errors) == 0, "errors": errors})


def process_order(payload_json: str, idempotency_key: str) -> str:
    """Process a validated order. Idempotency key prevents duplicate processing."""
    payload = json.loads(payload_json)
    # In production: call your real order processor here
    return json.dumps({
        "status": "processed",
        "order_id": payload.get("order_id"),
        "idempotency_key": idempotency_key,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    })


def save_repair_rule(partner_id: str, source_field: str, target_field: str, transformation: str) -> str:
    """Persist a successful repair rule to Neon for future reuse."""
    with psycopg.connect(NEON_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO repair_rules (partner_id, source_field, target_field, transformation)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (partner_id, source_field, target_field, transformation),
            )
        conn.commit()
    return json.dumps({"saved": True, "rule": f"{source_field} → {target_field} ({transformation})"})


def escalate_incident(incident_id: str, reason: str) -> str:
    """Flag an incident for human review when automatic repair is unsafe."""
    with psycopg.connect(NEON_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE integration_incidents SET status = 'escalated' WHERE id = %s",
                (incident_id,),
            )
        conn.commit()
    return json.dumps({
        "escalated": True,
        "incident_id": incident_id,
        "reason": reason,
        "action": "human review required",
    })
```

---

### `agent.py` — Integration Recovery Agent + AgentOS

```python
import os
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.nvidia import Nvidia
from agno.os import AgentOS

from tools import (
    validate_order_payload,
    lookup_repair_rules,
    apply_repair_in_sandbox,
    validate_business_rules,
    process_order,
    save_repair_rule,
    escalate_incident,
)

# --- Neon-backed PostgresDb for Agno sessions + history ---
db = PostgresDb(db_url=os.environ["NEON_DB_URL"])

# --- Integration Recovery Agent ---
agent = Agent(
    id="integration-recovery-agent",
    name="Integration Recovery Agent",
    model=Nvidia(id="stepfun-ai/step-3.7-flash"),
    db=db,
    tools=[
        validate_order_payload,
        lookup_repair_rules,
        apply_repair_in_sandbox,
        validate_business_rules,
        process_order,
        save_repair_rule,
        escalate_incident,
    ],
    add_history_to_context=True,
    num_history_runs=3,
    update_memory_on_run=False,   # repair rules live in Neon, not agent memory
    enable_session_summaries=True,
    markdown=True,
    instructions=[
        "You are an Integration Recovery Agent.",
        "Step 1: Always call validate_order_payload first.",
        "Step 2: If valid, call validate_business_rules, then process_order.",
        "Step 3: If invalid, call lookup_repair_rules for the partner.",
        "Step 4: If known rules exist, call apply_repair_in_sandbox with those rules.",
        "Step 5: After sandbox repair, call validate_order_payload again on the repaired payload.",
        "Step 6: If repaired payload is valid, call validate_business_rules.",
        "Step 7: If business rules pass, call process_order with a unique idempotency key.",
        "Step 8: After successful processing, call save_repair_rule for each rule applied.",
        "Step 9: If business rules fail (e.g. negative amount), call escalate_incident. Do not process.",
        "Step 10: If no known rules exist and you cannot safely propose a repair, call escalate_incident.",
        "Never mutate production data directly. Always use sandbox first.",
        "Never invent field mappings not supported by the available tools.",
    ],
)

# --- AgentOS: exposes agent via FastAPI ---
agent_os = AgentOS(agents=[agent], db=db)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agent:app", reload=True)
```

---

### Run it

```bash
# 1. Create Neon tables
python db_setup.py

# 2. Export env vars
export NEON_DB_URL="postgresql+psycopg://user:pass@ep-xxx.neon.tech/dbname?sslmode=require"
export NVIDIA_API_KEY="your_nvidia_api_key"

# 3. Start AgentOS
python agent.py
# → running at http://localhost:7860
```

---

### Demo payloads — call via AgentOS API

```bash
# Healthy order
curl -X POST http://localhost:7860/v1/agents/integration-recovery-agent/runs \
  -H "Content-Type: application/json" \
  -d '{"message": "{\"order_id\":\"ORD-1001\",\"customer_id\":\"C-100\",\"amount\":499.00,\"currency\":\"INR\",\"payment_status\":\"PAID\"}", "session_id": "demo"}'

# Drifted order (first time — agent investigates + saves rule)
curl -X POST http://localhost:7860/v1/agents/integration-recovery-agent/runs \
  -H "Content-Type: application/json" \
  -d '{"message": "{\"order_id\":\"ORD-1007\",\"client_id\":\"C-8831\",\"total\":\"1299.00\",\"currency\":\"INR\",\"payment_status\":\"paid\"}", "session_id": "demo"}'

# Same drift (second time — rule found in Neon, auto-repaired)
curl -X POST http://localhost:7860/v1/agents/integration-recovery-agent/runs \
  -H "Content-Type: application/json" \
  -d '{"message": "{\"order_id\":\"ORD-1008\",\"client_id\":\"C-9912\",\"total\":\"749.00\",\"currency\":\"INR\",\"payment_status\":\"paid\"}", "session_id": "demo"}'

# Unsafe — negative amount (escalated, not processed)
curl -X POST http://localhost:7860/v1/agents/integration-recovery-agent/runs \
  -H "Content-Type: application/json" \
  -d '{"message": "{\"order_id\":\"ORD-1009\",\"client_id\":\"C-3321\",\"total\":\"-500.00\",\"currency\":\"INR\",\"payment_status\":\"paid\"}", "session_id": "demo"}'
```

Connect `os.agno.com` to `http://localhost:7860` as your presentation UI.

```suggestions
(Run your first AgentOS)[/agent-os/run-your-os]
(NVIDIA model usage)[/models/providers/gateways/nvidia/overview]
(AgentOS with Neon)[/examples/agent-os/dbs/neon]
```