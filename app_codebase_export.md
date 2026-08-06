# App Codebase Export

Exported `10` Python files from `D:\artizent\plici-demo\app`.

## `app/__init__.py`

```python
"""Integration Recovery Agent Application Package."""
```

## `app/agent.py`

```python
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
    retries=5,
    delay_between_retries=2,
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
```

## `app/config.py`

```python
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "local")
    ALLOW_SQLITE_FALLBACK: bool = os.getenv("ALLOW_SQLITE_FALLBACK", "true").lower() in ("true", "1", "yes")
    NEON_DB_URL: str = os.getenv(
        "NEON_DB_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/integration_recovery_demo"
    )
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
    NVIDIA_MODEL: str = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    PORT: int = int(os.getenv("PORT", "7860"))


settings = Settings()
```

## `app/db.py`

```python
import logging
import os
import sqlite3

import psycopg
from psycopg.rows import dict_row

from app.config import settings

logger = logging.getLogger("app.db")
_sqlite_keepalive = None


def is_postgres(db_url: str | None = None) -> bool:
    url = db_url or settings.NEON_DB_URL
    return bool(url and url.startswith(("postgresql", "postgres")))


def get_db_connection(db_url: str | None = None):
    global _sqlite_keepalive
    url = db_url or settings.NEON_DB_URL
    if is_postgres(url):
        clean_url = url.replace("postgresql+psycopg://", "postgresql://")
        try:
            return psycopg.connect(clean_url, row_factory=dict_row)
        except Exception as e:
            if not settings.ALLOW_SQLITE_FALLBACK:
                logger.error("[CRITICAL DB FAILURE] Neon PostgreSQL connection failed: %s", e)
                raise RuntimeError(f"Database connection to Neon failed and ALLOW_SQLITE_FALLBACK is False: {e}") from e
            logger.warning("[EXPLICIT FALLBACK] Neon connection failed (%s). Using SQLite in-memory fallback (ALLOW_SQLITE_FALLBACK=True).", e)
            url = ":memory:"

    # SQLite fallback
    conn_str = "file:memdb1?mode=memory&cache=shared" if url == ":memory:" else url
    if url == ":memory:" and _sqlite_keepalive is None:
        _sqlite_keepalive = sqlite3.connect(conn_str, uri=True)
    conn = sqlite3.connect(conn_str, uri=bool(url == ":memory:" or "file:" in conn_str))
    conn.row_factory = sqlite3.Row
    return conn


def run_migrations(db_url: str | None = None):
    url = db_url or settings.NEON_DB_URL
    migration_file = os.path.join(os.path.dirname(__file__), "..", "migrations", "001_initial.sql")
    
    if not os.path.exists(migration_file):
        return

    with open(migration_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    try:
        conn = get_db_connection(url)
        try:
            cur = conn.cursor()
            try:
                if is_postgres(url):
                    cur.execute(sql_content)
                else:
                    sqlite_sql = sql_content.replace("gen_random_uuid()", "(lower(hex(randomblob(16))))")
                    sqlite_sql = sqlite_sql.replace("JSONB", "TEXT").replace("TIMESTAMPTZ", "TEXT").replace("now()", "CURRENT_TIMESTAMP")
                    sqlite_sql = sqlite_sql.replace("CREATE EXTENSION IF NOT EXISTS pgcrypto;", "")
                    sqlite_sql = sqlite_sql.replace("::jsonb", "")
                    sqlite_sql = sqlite_sql.replace("NUMERIC(4,3)", "REAL")
                    cur.executescript(sqlite_sql)
            finally:
                cur.close()
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("[Warning] DB Migration error: %s", e)
```

## `app/main.py`

```python
from contextlib import asynccontextmanager

import uvicorn
from agno.os import AgentOS

from app.agent import agent, db
from app.config import settings
from app.db import run_migrations


@asynccontextmanager
async def lifespan(app):
    # Run database migrations on startup if DB configured
    try:
        if settings.NEON_DB_URL:
            run_migrations(settings.NEON_DB_URL)
    except Exception as e:
        print(f"[Warning] DB Migration during startup: {e}")
    yield


agent_os = AgentOS(
    id="integration-recovery-os",
    agents=[agent],
    db=db,
    tracing=True,
    lifespan=lifespan
)

app = agent_os.get_app()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
```

## `app/repair.py`

```python
import copy
from typing import Any

from app.schemas import SandboxResult

ALLOWED_OPERATIONS = {"rename", "to_float", "uppercase"}


def apply_repair_plan_in_sandbox(payload: dict[str, Any], plan: dict[str, Any]) -> SandboxResult:
    """Apply a repair plan to a copy of payload in memory (sandbox).
    Does NOT mutate input payload.
    Supports operations: 'rename', 'to_float', 'uppercase'.
    """
    if not isinstance(payload, dict):
        return SandboxResult(success=False, error="Payload must be a dictionary")

    repaired = copy.deepcopy(payload)
    applied_rules: list[dict[str, Any]] = []
    rules = plan.get("rules", [])

    if not isinstance(rules, list):
        return SandboxResult(success=False, error="Plan rules must be a list")

    target_fields_populated = set()

    for rule in rules:
        if not isinstance(rule, dict):
            return SandboxResult(success=False, error="Rule must be a dictionary")

        src = rule.get("source_field")
        tgt = rule.get("target_field")
        op = rule.get("operation")

        if not src or not tgt or not op:
            return SandboxResult(
                success=False,
                error=f"Invalid rule structure: {rule}. Must have source_field, target_field, operation"
            )

        if op not in ALLOWED_OPERATIONS:
            return SandboxResult(
                success=False,
                error=f"Unsupported operation '{op}'. Allowed operations: {sorted(ALLOWED_OPERATIONS)}"
            )

        if src not in repaired:
            # Source field not in payload, skip or return error if required
            continue

        if tgt in target_fields_populated:
            return SandboxResult(
                success=False,
                error=f"Duplicate target field collision: '{tgt}' assigned multiple times"
            )

        val = repaired.pop(src)

        try:
            if op == "rename":
                repaired[tgt] = val
            elif op == "to_float":
                repaired[tgt] = float(val)
            elif op == "uppercase":
                repaired[tgt] = str(val).upper()
            
            target_fields_populated.add(tgt)
            applied_rules.append({
                "source_field": src,
                "target_field": tgt,
                "operation": op
            })
        except (ValueError, TypeError) as e:
            return SandboxResult(
                success=False,
                error=f"Conversion failure on field '{src}' to '{tgt}' using op '{op}': {e!s}"
            )

    return SandboxResult(
        success=True,
        repaired_payload=repaired,
        applied_rules=applied_rules
    )
```

## `app/repository.py`

```python
import json
import uuid
from typing import Any

from app.db import get_db_connection, is_postgres


class Repository:
    def __init__(self, db_url: str | None = None):
        self.db_url = db_url

    def _get_conn(self):
        return get_db_connection(self.db_url)

    def _sql(self, query: str) -> str:
        if not is_postgres(self.db_url):
            return query.replace("%s", "?")
        return query

    def _json(self, val: Any) -> str:
        if isinstance(val, str):
            return val
        return json.dumps(val)

    def _parse_json(self, val: Any) -> Any:
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return val
        return val

    def lookup_repair_rules(self, partner_id: str, status: str = "approved") -> list[dict[str, Any]]:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            query = self._sql(
                "SELECT id, partner_id, source_field, target_field, operation, confidence, status, hit_count "
                "FROM repair_rules WHERE partner_id = %s AND status = %s ORDER BY hit_count DESC"
            )
            cur.execute(query, (partner_id, status))
            rows = cur.fetchall()
            results = []
            for r in rows:
                r_dict = dict(r) if hasattr(r, "keys") else {
                    "id": str(r[0]), "partner_id": r[1], "source_field": r[2],
                    "target_field": r[3], "operation": r[4], "confidence": float(r[5]),
                    "status": r[6], "hit_count": r[7]
                }
                r_dict["id"] = str(r_dict["id"])
                if "confidence" in r_dict and r_dict["confidence"] is not None:
                    r_dict["confidence"] = float(r_dict["confidence"])
                results.append(r_dict)
            return results
        finally:
            cur.close()
            conn.close()

    def save_approved_repair_rule(
        self,
        partner_id: str,
        source_field: str,
        target_field: str,
        operation: str,
        confidence: float = 1.0
    ) -> dict[str, Any]:
        conn = self._get_conn()
        cur = conn.cursor()
        rule_id = str(uuid.uuid4())
        try:
            if is_postgres(self.db_url):
                cur.execute(
                    """
                    INSERT INTO repair_rules (id, partner_id, source_field, target_field, operation, confidence, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'approved')
                    ON CONFLICT (partner_id, source_field, target_field, operation)
                    DO UPDATE SET status = 'approved', last_used_at = now()
                    RETURNING id, partner_id, source_field, target_field, operation, status, hit_count
                    """,
                    (rule_id, partner_id, source_field, target_field, operation, confidence)
                )
                row = cur.fetchone()
                result = dict(row)
                if "id" in result:
                    result["id"] = str(result["id"])
            else:
                query = self._sql(
                    """
                    INSERT OR REPLACE INTO repair_rules (id, partner_id, source_field, target_field, operation, confidence, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'approved')
                    """
                )
                cur.execute(query, (rule_id, partner_id, source_field, target_field, operation, confidence))
                result = {
                    "id": str(rule_id),
                    "partner_id": partner_id,
                    "source_field": source_field,
                    "target_field": target_field,
                    "operation": operation,
                    "status": "approved",
                    "hit_count": 0
                }
            conn.commit()
            return result
        finally:
            cur.close()
            conn.close()

    def increment_rule_hit_count(self, partner_id: str, source_field: str, target_field: str, operation: str) -> None:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            if is_postgres(self.db_url):
                cur.execute(
                    """
                    UPDATE repair_rules
                    SET hit_count = hit_count + 1, last_used_at = now()
                    WHERE partner_id = %s AND source_field = %s AND target_field = %s AND operation = %s
                    """,
                    (partner_id, source_field, target_field, operation)
                )
            else:
                query = self._sql(
                    """
                    UPDATE repair_rules
                    SET hit_count = hit_count + 1, last_used_at = CURRENT_TIMESTAMP
                    WHERE partner_id = %s AND source_field = %s AND target_field = %s AND operation = %s
                    """
                )
                cur.execute(query, (partner_id, source_field, target_field, operation))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def record_incident(
        self,
        partner_id: str,
        order_id: str | None,
        raw_payload: dict[str, Any],
        validation_errors: list[dict[str, Any]],
        incident_type: str,
        status: str = "detected"
    ) -> str:
        conn = self._get_conn()
        cur = conn.cursor()
        incident_id = str(uuid.uuid4())
        try:
            query = self._sql(
                """
                INSERT INTO integration_incidents (id, partner_id, order_id, raw_payload, validation_errors, incident_type, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
            )
            cur.execute(
                query,
                (
                    incident_id, partner_id, order_id,
                    self._json(raw_payload), self._json(validation_errors),
                    incident_type, status
                )
            )
            conn.commit()
            return incident_id
        finally:
            cur.close()
            conn.close()

    def update_incident_status(self, incident_id: str, status: str) -> None:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            if is_postgres(self.db_url):
                cur.execute(
                    "UPDATE integration_incidents SET status = %s, resolved_at = now() WHERE id = %s",
                    (status, incident_id)
                )
            else:
                query = self._sql("UPDATE integration_incidents SET status = %s, resolved_at = CURRENT_TIMESTAMP WHERE id = %s")
                cur.execute(query, (status, incident_id))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def record_repair_attempt(
        self,
        incident_id: str,
        repair_plan: dict[str, Any],
        before_payload: dict[str, Any],
        after_payload: dict[str, Any] | None = None,
        validation_result: dict[str, Any] | None = None,
        business_result: dict[str, Any] | None = None,
        processing_result: dict[str, Any] | None = None,
        outcome: str = "processed"
    ) -> str:
        conn = self._get_conn()
        cur = conn.cursor()
        attempt_id = str(uuid.uuid4())
        try:
            query = self._sql(
                """
                INSERT INTO repair_attempts (id, incident_id, repair_plan, before_payload, after_payload, validation_result, business_result, processing_result, outcome)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
            )
            cur.execute(
                query,
                (
                    attempt_id, incident_id,
                    self._json(repair_plan), self._json(before_payload),
                    self._json(after_payload) if after_payload else None,
                    self._json(validation_result) if validation_result else None,
                    self._json(business_result) if business_result else None,
                    self._json(processing_result) if processing_result else None,
                    outcome
                )
            )
            conn.commit()
            return attempt_id
        finally:
            cur.close()
            conn.close()

    def process_order_idempotent(
        self,
        idempotency_key: str,
        order_id: str,
        payload: dict[str, Any],
        result: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            query_check = self._sql("SELECT result FROM processed_orders WHERE idempotency_key = %s")
            cur.execute(query_check, (idempotency_key,))
            row = cur.fetchone()
            if row:
                existing_res = dict(row)["result"] if hasattr(row, "keys") else row[0]
                return self._parse_json(existing_res), False

            query_ins = self._sql(
                """
                INSERT INTO processed_orders (idempotency_key, order_id, payload, result)
                VALUES (%s, %s, %s, %s)
                """
            )
            cur.execute(query_ins, (idempotency_key, order_id, self._json(payload), self._json(result)))
            conn.commit()
            return result, True
        finally:
            cur.close()
            conn.close()

    def escalate_incident(self, incident_id: str | None, reason: str, evidence: dict[str, Any]) -> str:
        conn = self._get_conn()
        cur = conn.cursor()
        escalation_id = str(uuid.uuid4())
        try:
            query_esc = self._sql(
                """
                INSERT INTO escalations (id, incident_id, reason, evidence, status)
                VALUES (%s, %s, %s, %s, 'open')
                """
            )
            cur.execute(query_esc, (escalation_id, incident_id, reason, self._json(evidence)))
            if incident_id:
                if is_postgres(self.db_url):
                    cur.execute("UPDATE integration_incidents SET status = 'escalated', resolved_at = now() WHERE id = %s", (incident_id,))
                else:
                    query_upd = self._sql("UPDATE integration_incidents SET status = 'escalated', resolved_at = CURRENT_TIMESTAMP WHERE id = %s")
                    cur.execute(query_upd, (incident_id,))
            conn.commit()
            return escalation_id
        finally:
            cur.close()
            conn.close()

    def get_incident_audit(self, incident_id: str) -> dict[str, Any]:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            query_inc = self._sql("SELECT * FROM integration_incidents WHERE id = %s")
            cur.execute(query_inc, (incident_id,))
            row = cur.fetchone()
            if not row:
                return {"error": f"Incident {incident_id} not found"}
            incident = dict(row)
            incident["id"] = str(incident["id"])
            incident["raw_payload"] = self._parse_json(incident.get("raw_payload"))
            incident["validation_errors"] = self._parse_json(incident.get("validation_errors"))
            if incident.get("created_at"):
                incident["created_at"] = str(incident["created_at"])
            if incident.get("resolved_at"):
                incident["resolved_at"] = str(incident["resolved_at"])

            query_att = self._sql("SELECT * FROM repair_attempts WHERE incident_id = %s")
            cur.execute(query_att, (incident_id,))
            attempts_rows = cur.fetchall()
            attempts = []
            for a in attempts_rows:
                att = dict(a)
                att["id"] = str(att["id"])
                att["incident_id"] = str(att["incident_id"])
                att["repair_plan"] = self._parse_json(att.get("repair_plan"))
                att["before_payload"] = self._parse_json(att.get("before_payload"))
                att["after_payload"] = self._parse_json(att.get("after_payload"))
                att["validation_result"] = self._parse_json(att.get("validation_result"))
                att["business_result"] = self._parse_json(att.get("business_result"))
                att["processing_result"] = self._parse_json(att.get("processing_result"))
                if att.get("created_at"):
                    att["created_at"] = str(att["created_at"])
                attempts.append(att)

            query_esc = self._sql("SELECT * FROM escalations WHERE incident_id = %s")
            cur.execute(query_esc, (incident_id,))
            escalation_rows = cur.fetchall()
            escalations = []
            for e in escalation_rows:
                esc = dict(e)
                esc["id"] = str(esc["id"])
                if esc.get("incident_id"):
                    esc["incident_id"] = str(esc["incident_id"])
                esc["evidence"] = self._parse_json(esc.get("evidence"))
                if esc.get("created_at"):
                    esc["created_at"] = str(esc["created_at"])
                escalations.append(esc)

            return {
                "incident": incident,
                "attempts": attempts,
                "escalations": escalations
            }
        finally:
            cur.close()
            conn.close()
```

## `app/schemas.py`

```python
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CanonicalOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partner_id: str
    order_id: str
    customer_id: str
    amount: float
    currency: Literal["INR", "USD", "EUR", "GBP"]
    payment_status: Literal["PAID", "PENDING", "FAILED"]


class ValidationErrorDetail(BaseModel):
    type: str
    field: str | None = None
    fields: list[str] | None = None
    expected: str | None = None
    allowed: list[str] | None = None
    message: str | None = None


class ValidationReport(BaseModel):
    valid: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)


class RepairRuleItem(BaseModel):
    source_field: str
    target_field: str
    operation: Literal["rename", "to_float", "uppercase"]
    confidence: float = 1.0
    status: Literal["proposed", "approved", "rejected"] = "approved"


class RepairPlan(BaseModel):
    partner_id: str
    rules: list[RepairRuleItem]


class SandboxResult(BaseModel):
    success: bool
    repaired_payload: dict[str, Any] | None = None
    applied_rules: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class BusinessResult(BaseModel):
    safe: bool
    errors: list[str] = Field(default_factory=list)


class IncidentRecord(BaseModel):
    id: str | None = None
    partner_id: str
    order_id: str | None = None
    raw_payload: dict[str, Any]
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    incident_type: str
    status: Literal["detected", "repaired", "processed", "escalated", "failed"] = "detected"
    created_at: str | None = None
    resolved_at: str | None = None


class EscalationRecord(BaseModel):
    id: str | None = None
    incident_id: str | None = None
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "acknowledged", "resolved"] = "open"
    created_at: str | None = None
```

## `app/tools.py`

```python
import datetime
import json
import logging

from agno.tools import tool

from app.repair import apply_repair_plan_in_sandbox
from app.repository import Repository
from app.validators import validate_business_rules, validate_canonical_order

default_repo = Repository()

DEMO_SCENARIOS = {
    "healthy_order": {
        "description": "A valid partner order that should process immediately.",
        "payload": {
            "partner_id": "partner-acme",
            "order_id": "ORD-2001",
            "customer_id": "C-1001",
            "amount": 499.0,
            "currency": "INR",
            "payment_status": "PAID",
        },
    },
    "first_schema_drift": {
        "description": "First occurrence of partner schema drift.",
        "payload": {
            "partner_id": "partner-acme",
            "order_id": "ORD-2002",
            "client_id": "C-1002",
            "total": "1299.00",
            "currency": "INR",
            "payment_status": "paid",
        },
    },
    "repeated_schema_drift": {
        "description": "The same partner sends the same known schema drift again.",
        "payload": {
            "partner_id": "partner-acme",
            "order_id": "ORD-2003",
            "client_id": "C-1003",
            "total": "749.00",
            "currency": "INR",
            "payment_status": "paid",
        },
    },
    "unsafe_order": {
        "description": "The payload can be normalized, but the amount violates business policy.",
        "payload": {
            "partner_id": "partner-acme",
            "order_id": "ORD-2004",
            "client_id": "C-1004",
            "total": "-500.00",
            "currency": "INR",
            "payment_status": "paid",
        },
    },
}


@tool
def load_demo_scenario(scenario_name: str) -> str:
    """
    Load a controlled demonstration event.

    Valid scenarios:
    healthy_order,
    first_schema_drift,
    repeated_schema_drift,
    unsafe_order.

    This tool returns a test fixture only. It does not process an order
    or modify production state.
    """
    scenario = DEMO_SCENARIOS.get(scenario_name)

    if scenario is None:
        return json.dumps({
            "success": False,
            "error": "Unknown demo scenario",
            "available_scenarios": list(DEMO_SCENARIOS),
        })

    return json.dumps({
        "success": True,
        "scenario": scenario_name,
        "description": scenario["description"],
        "payload": scenario["payload"],
        "demo_only": True,
    })


def validate_order_payload(payload_json: str) -> str:
    """Validate a partner order payload against the canonical schema.
    Returns structured JSON with 'valid' boolean and 'errors' array.
    """
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        report = validate_canonical_order(payload)
        return json.dumps({"valid": report.valid, "errors": report.errors})
    except Exception as e:
        return json.dumps({"valid": False, "errors": [{"type": "parse_error", "message": str(e)}]})


def lookup_repair_rules(partner_id: str, validation_errors_json: str = "[]") -> str:
    """Lookup existing approved schema repair rules in Neon/Postgres for a partner."""
    try:
        rules = default_repo.lookup_repair_rules(partner_id=partner_id, status="approved")
        return json.dumps({"rules": rules, "count": len(rules)})
    except Exception as e:
        return json.dumps({"rules": [], "count": 0, "error": str(e)})


def propose_repair(payload_json: str, validation_errors_json: str, known_rules_json: str) -> str:
    """Propose a repair plan using known rules or safe heuristics (rename, to_float, uppercase).
    Returns repair plan JSON.
    """
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        partner_id = payload.get("partner_id", "unknown-partner")
        
        known_data = json.loads(known_rules_json) if isinstance(known_rules_json, str) else known_rules_json
        known_rules = known_data.get("rules", []) if isinstance(known_data, dict) else []

        rules_to_apply = []

        # If known rules exist, reuse them
        if known_rules:
            for r in known_rules:
                rules_to_apply.append({
                    "source_field": r.get("source_field"),
                    "target_field": r.get("target_field"),
                    "operation": r.get("operation") or r.get("transformation")
                })
        else:
            # Discover repair rules dynamically from payload fields
            # client_id -> customer_id (rename)
            if "client_id" in payload and "customer_id" not in payload:
                rules_to_apply.append({"source_field": "client_id", "target_field": "customer_id", "operation": "rename"})
            
            # total -> amount (to_float)
            if "total" in payload and "amount" not in payload:
                rules_to_apply.append({"source_field": "total", "target_field": "amount", "operation": "to_float"})
            elif "amount" in payload and isinstance(payload["amount"], str):
                rules_to_apply.append({"source_field": "amount", "target_field": "amount", "operation": "to_float"})
            
            # payment_status case normalization (uppercase)
            if (
                "payment_status" in payload
                and isinstance(payload["payment_status"], str)
                and payload["payment_status"].upper() in {"PAID", "PENDING", "FAILED"}
                and payload["payment_status"] != payload["payment_status"].upper()
            ):
                rules_to_apply.append({"source_field": "payment_status", "target_field": "payment_status", "operation": "uppercase"})

        plan = {
            "partner_id": partner_id,
            "rules": rules_to_apply
        }
        return json.dumps(plan)
    except Exception as e:
        return json.dumps({"partner_id": "unknown", "rules": [], "error": str(e)})


def apply_repair_in_sandbox(payload_json: str, repair_plan_json: str) -> str:
    """Apply a repair plan to payload copy in memory (sandbox).
    Does NOT touch production data. Returns sandbox result JSON.
    """
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        plan = json.loads(repair_plan_json) if isinstance(repair_plan_json, str) else repair_plan_json
        res = apply_repair_plan_in_sandbox(payload, plan)
        return json.dumps({
            "success": res.success,
            "repaired_payload": res.repaired_payload,
            "applied_rules": res.applied_rules,
            "error": res.error
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def validate_business_rules_tool(payload_json: str) -> str:
    """Validate business policies: amount > 0, currency valid, payment_status valid.
    Returns business safety result JSON.
    """
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        res = validate_business_rules(payload)
        return json.dumps({"safe": res.safe, "errors": res.errors})
    except Exception as e:
        return json.dumps({"safe": False, "errors": [str(e)]})


def process_order(payload_json: str, idempotency_key: str) -> str:
    """Process order downstream using idempotency key. Prevents duplicate side-effects.
    Returns processing result JSON.
    """
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        order_id = payload.get("order_id", "UNKNOWN_ORDER")
        
        result_body = {
            "status": "processed",
            "order_id": order_id,
            "partner_id": payload.get("partner_id"),
            "amount": payload.get("amount"),
            "currency": payload.get("currency"),
            "idempotency_key": idempotency_key,
            "processed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        final_res, was_new = default_repo.process_order_idempotent(
            idempotency_key=idempotency_key,
            order_id=order_id,
            payload=payload,
            result=result_body
        )
        return json.dumps({
            "status": "processed",
            "was_new": was_new,
            "result": final_res
        })
    except Exception as e:
        return json.dumps({"status": "failed", "error": str(e)})


def save_approved_repair_rule(rule_json: str) -> str:
    """Save an approved schema repair rule to Neon for future automatic reuse.
    Expects rule JSON object, list of rules, or repair plan dictionary.
    """
    try:
        data = json.loads(rule_json) if isinstance(rule_json, str) else rule_json
        if isinstance(data, dict) and "rules" in data:
            partner_id = data.get("partner_id", "partner-acme")
            rules_list = data["rules"]
        elif isinstance(data, list):
            partner_id = "partner-acme"
            rules_list = data
        else:
            partner_id = data.get("partner_id", "partner-acme")
            rules_list = [data]

        saved = []
        for item in rules_list:
            p_id = item.get("partner_id", partner_id)
            src = item.get("source_field")
            tgt = item.get("target_field")
            op = item.get("operation") or item.get("transformation")
            if src and tgt and op:
                saved_rule = default_repo.save_approved_repair_rule(
                    partner_id=p_id,
                    source_field=src,
                    target_field=tgt,
                    operation=op
                )
                saved.append(saved_rule)

        return json.dumps({"saved": True, "count": len(saved), "rules": saved})
    except Exception as e:
        return json.dumps({"saved": False, "count": 0, "error": str(e)})


logger = logging.getLogger("app.tools")

VALID_INCIDENT_STATUSES = {"detected", "repaired", "processed", "escalated", "failed"}
INCIDENT_STATUS_MAP = {
    "RECEIVED": "detected",
    "VALIDATING": "detected",
    "DIAGNOSING": "detected",
    "REPAIRING": "detected",
    "REPAIRING_IN_SANDBOX": "detected",
    "VERIFYING": "detected",
    "PROCESSING": "processed",
    "COMPLETE": "processed",
    "ESCALATED": "escalated",
}

VALID_ATTEMPT_OUTCOMES = {"sandbox_failed", "business_failed", "processed", "escalated"}
ATTEMPT_OUTCOME_MAP = {
    "SUCCESS": "processed",
    "PASSED": "processed",
    "SANDBOX_PASSED": "processed",
    "SANDBOX_SUCCESS": "processed",
    "BUSINESS_PASSED": "processed",
    "FAILED": "sandbox_failed",
    "ERROR": "sandbox_failed",
}


def sanitize_incident_status(raw_status: str | None) -> tuple[str, str | None]:
    if not raw_status:
        return "detected", None
    s = str(raw_status).strip()
    if s in VALID_INCIDENT_STATUSES:
        return s, None
    normalized = INCIDENT_STATUS_MAP.get(s.upper(), "detected")
    logger.warning("Normalized incident status from %r to %r for DB constraint safety.", raw_status, normalized)
    return normalized, s


def sanitize_attempt_outcome(raw_outcome: str | None) -> tuple[str, str | None]:
    if not raw_outcome:
        return "processed", None
    o = str(raw_outcome).strip()
    if o in VALID_ATTEMPT_OUTCOMES:
        return o, None
    normalized = ATTEMPT_OUTCOME_MAP.get(o.upper(), "processed")
    logger.warning("Normalized attempt outcome from %r to %r for DB constraint safety.", raw_outcome, normalized)
    return normalized, o


def record_incident(incident_json: str) -> str:
    """Record an integration incident in Neon."""
    try:
        data = json.loads(incident_json) if isinstance(incident_json, str) else incident_json
        raw_status = data.get("status")
        status, normalized_from = sanitize_incident_status(raw_status)

        incident_id = default_repo.record_incident(
            partner_id=data.get("partner_id", "unknown"),
            order_id=data.get("order_id"),
            raw_payload=data.get("raw_payload", data),
            validation_errors=data.get("validation_errors", []),
            incident_type=data.get("incident_type", "schema_drift"),
            status=status
        )
        res = {"success": True, "incident_id": incident_id, "stored_status": status}
        if normalized_from:
            res["normalized_from"] = normalized_from
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def record_repair_attempt(attempt_json: str) -> str:
    """Record a repair attempt in Neon linked to an incident."""
    try:
        data = json.loads(attempt_json) if isinstance(attempt_json, str) else attempt_json
        incident_id = data.get("incident_id")

        if not incident_id:
            incident_id = default_repo.record_incident(
                partner_id=data.get("partner_id", "unknown"),
                order_id=data.get("order_id"),
                raw_payload=data.get("before_payload", data),
                validation_errors=[],
                incident_type="schema_drift",
                status="repaired"
            )

        raw_outcome = data.get("outcome")
        outcome, normalized_from = sanitize_attempt_outcome(raw_outcome)

        attempt_id = default_repo.record_repair_attempt(
            incident_id=incident_id,
            repair_plan=data.get("repair_plan", {}),
            before_payload=data.get("before_payload", {}),
            after_payload=data.get("after_payload"),
            validation_result=data.get("validation_result"),
            business_result=data.get("business_result"),
            processing_result=data.get("processing_result"),
            outcome=outcome
        )
        res = {"success": True, "attempt_id": attempt_id, "incident_id": incident_id, "stored_outcome": outcome}
        if normalized_from:
            res["normalized_from"] = normalized_from
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def escalate_incident(incident_json: str, reason: str) -> str:
    """Flag an incident as escalated for human review when automatic repair is unsafe or ambiguous."""
    try:
        data = json.loads(incident_json) if isinstance(incident_json, str) else {}
        incident_id = data.get("incident_id") or data.get("id")
        
        escalation_id = default_repo.escalate_incident(
            incident_id=incident_id,
            reason=reason,
            evidence=data
        )
        return json.dumps({
            "escalated": True,
            "escalation_id": escalation_id,
            "incident_id": incident_id,
            "reason": reason,
            "action": "human review required"
        })
    except Exception as e:
        return json.dumps({"escalated": False, "error": str(e)})


def get_incident_audit(incident_id: str) -> str:
    """Retrieve full audit log for an incident including repair attempts and escalations."""
    try:
        audit = default_repo.get_incident_audit(incident_id)
        return json.dumps(audit, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
```

## `app/validators.py`

```python
from typing import Any

from app.schemas import BusinessResult, ValidationReport

CANONICAL_FIELDS = {"partner_id", "order_id", "customer_id", "amount", "currency", "payment_status"}
ALLOWED_CURRENCIES = {"INR", "USD", "EUR", "GBP"}
ALLOWED_PAYMENT_STATUSES = {"PAID", "PENDING", "FAILED"}


def validate_canonical_order(payload: dict[str, Any]) -> ValidationReport:
    """Validate incoming payload strictly against canonical schema.
    Rejects partner aliases (e.g. client_id, total) and wrong types/cases.
    """
    errors: list[dict[str, Any]] = []

    if not isinstance(payload, dict):
        return ValidationReport(valid=False, errors=[{"type": "invalid_payload", "message": "Payload must be a JSON object"}])

    missing = sorted(CANONICAL_FIELDS - payload.keys())
    if missing:
        errors.append({"type": "missing_fields", "fields": missing})

    unexpected = sorted(set(payload.keys()) - CANONICAL_FIELDS)
    if unexpected:
        errors.append({"type": "unexpected_fields", "fields": unexpected})

    if "amount" in payload:
        val = payload["amount"]
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            errors.append({
                "type": "invalid_type",
                "field": "amount",
                "expected": "number",
                "got": type(val).__name__
            })

    if "currency" in payload:
        cur = payload["currency"]
        if cur not in ALLOWED_CURRENCIES:
            errors.append({
                "type": "invalid_value",
                "field": "currency",
                "allowed": sorted(ALLOWED_CURRENCIES),
                "got": str(cur)
            })

    if "payment_status" in payload:
        status = payload["payment_status"]
        if status not in ALLOWED_PAYMENT_STATUSES:
            errors.append({
                "type": "invalid_value",
                "field": "payment_status",
                "allowed": sorted(ALLOWED_PAYMENT_STATUSES),
                "got": str(status)
            })

    return ValidationReport(valid=len(errors) == 0, errors=errors)


def validate_business_rules(payload: dict[str, Any]) -> BusinessResult:
    """Validate business safety constraints on canonical payload."""
    errors: list[str] = []

    if "amount" not in payload:
        errors.append("amount field missing")
    else:
        try:
            amt = float(payload["amount"])
            if amt <= 0:
                errors.append("amount must be greater than zero")
        except (ValueError, TypeError):
            errors.append("amount is not a valid number")

    currency = payload.get("currency")
    if currency not in ALLOWED_CURRENCIES:
        errors.append(f"currency must be one of {sorted(ALLOWED_CURRENCIES)}")

    payment_status = payload.get("payment_status")
    if payment_status not in ALLOWED_PAYMENT_STATUSES:
        errors.append(f"payment_status must be one of {sorted(ALLOWED_PAYMENT_STATUSES)}")

    return BusinessResult(safe=len(errors) == 0, errors=errors)


def make_idempotency_key(partner_id: str, order_id: str) -> str:
    """Generate deterministic idempotency key for partner order."""
    return f"KEY:{partner_id}:{order_id}"
```
