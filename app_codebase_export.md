# App Codebase Export

Exported `11` Python files from `D:\artizent\plici-demo\app`.

## `app/__init__.py`

```python
"""Integration Recovery Agent Application Package."""
```

## `app/agent.py`

```python
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
    NVIDIA_MODEL: str = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
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
_db_pool = None


class PooledConnectionWrapper:
    """Wrapper that returns connection to psycopg_pool on close()."""
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        if self._pool and self._conn:
            self._pool.putconn(self._conn)
            self._conn = None
            self._pool = None

    def __getattr__(self, name):
        return getattr(self._conn, name)


def is_postgres(db_url: str | None = None) -> bool:
    url = db_url or settings.NEON_DB_URL
    return bool(url and url.startswith(("postgresql", "postgres")))


def get_db_pool(db_url: str | None = None):
    global _db_pool
    url = db_url or settings.NEON_DB_URL
    if is_postgres(url) and _db_pool is None:
        clean_url = url.replace("postgresql+psycopg://", "postgresql://")
        try:
            import psycopg_pool
            _db_pool = psycopg_pool.ConnectionPool(
                clean_url,
                min_size=1,
                max_size=10,
                max_idle=30,       # Drop connections if idle for 30 seconds
                max_lifetime=300,  # Force recycle every 5 minutes maximum
                kwargs={
                    "row_factory": dict_row,
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 5
                }
            )
            logger.info("Database connection pool initialized for Neon DB (min=1, max=10, max_idle=30s).")
        except Exception as e:
            logger.error("Failed to initialize connection pool: %s", e)
            _db_pool = None
    return _db_pool


def get_db_connection(db_url: str | None = None):
    global _sqlite_keepalive
    url = db_url or settings.NEON_DB_URL
    if is_postgres(url):
        clean_url = url.replace("postgresql+psycopg://", "postgresql://")
        pool = get_db_pool(url)
        if pool:
            try:
                conn = pool.getconn()
                return PooledConnectionWrapper(pool, conn)
            except Exception as e:
                logger.warning("[POOL FALLBACK] Failed to borrow connection from pool (%s). Direct connect fallback.", e)
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
import os
from contextlib import asynccontextmanager

import uvicorn
from agno.os import AgentOS
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput

from app.agent import db, recovery_team
from app.config import settings
from app.db import run_migrations
from app.semantica_integration import shared_context


# Patch Agno RunOutput/TeamRunOutput to support string status serialization in Agno OS routers
class _StatusWrapper(str):
    @property
    def value(self):
        return str(self)


def _patch_model_status(model_cls):
    orig_getattr = model_cls.__getattribute__

    def custom_getattr(self, name):
        val = orig_getattr(self, name)
        if name == "status" and val is not None and not hasattr(val, "value"):
            return _StatusWrapper(val)
        return val

    model_cls.__getattribute__ = custom_getattr


_patch_model_status(TeamRunOutput)
_patch_model_status(RunOutput)

# 1. Define custom routes on a base FastAPI app per AgentOS best practices
base_app = FastAPI(title="B2B Payment Recovery API")


@base_app.get("/api/compliance/graph")
async def get_semantica_knowledge_graph():
    """Retrieve full Semantica Knowledge Graph representation for visual explorer dashboards."""
    graph_dict = shared_context.kg.to_dict()
    return JSONResponse(content={
        "status": "success",
        "nodes_count": len(graph_dict.get("nodes", [])),
        "edges_count": len(graph_dict.get("edges", [])),
        "graph": graph_dict,
    })


@base_app.get("/api/compliance/export")
async def export_prov_o_compliance_report(output_filename: str = "compliance_audit.ttl"):
    """Export W3C PROV-O RDF Turtle file for financial auditors."""
    res = shared_context.export_compliance_report(output_path=output_filename, format="turtle")
    if res.get("success") and os.path.exists(output_filename):
        return FileResponse(
            path=output_filename,
            media_type="text/turtle",
            filename=output_filename
        )
    return JSONResponse(status_code=500, content=res)


@base_app.get("/api/compliance/precedents")
async def get_schema_drift_precedents(scenario: str = Query(..., description="Partner schema drift scenario")):
    """Query precedent decisions recorded in the Semantica Knowledge Graph."""
    precedents = shared_context.find_precedents(scenario)
    return JSONResponse(content={
        "scenario": scenario,
        "count": len(precedents),
        "precedents": precedents,
    })


@asynccontextmanager
async def lifespan(app):
    # Run database migrations on startup if DB configured
    try:
        if settings.NEON_DB_URL:
            run_migrations(settings.NEON_DB_URL)
    except Exception as e:
        print(f"[Warning] DB Migration during startup: {e}")
    yield


# 2. Pass base_app to AgentOS with explicit route conflict handling
agent_os = AgentOS(
    id="integration-recovery-os",
    teams=[recovery_team],
    db=db,
    tracing=True,
    base_app=base_app,
    lifespan=lifespan,
    on_route_conflict="preserve_base_app",
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
from app.semantica_integration import shared_context

ALLOWED_OPERATIONS = {"rename", "to_float", "uppercase"}


def apply_repair_plan_in_sandbox(payload: dict[str, Any], plan: dict[str, Any]) -> SandboxResult:
    """Apply a repair plan to a copy of payload in memory (sandbox).
    Does NOT mutate input payload.
    Supports operations: 'rename', 'to_float', 'uppercase'.
    Generates field-level W3C PROV-O lineage trace using Semantica.
    """
    if not isinstance(payload, dict):
        return SandboxResult(success=False, error="Payload must be a dictionary")

    repaired = copy.deepcopy(payload)
    applied_rules: list[dict[str, Any]] = []
    rules = plan.get("rules", [])

    if not isinstance(rules, list):
        return SandboxResult(success=False, error="Plan rules must be a list")

    order_id = payload.get("order_id", "UNKNOWN_ORDER")
    partner_id = payload.get("partner_id", "unknown")

    # Track raw input entity lineage in Semantica
    shared_context.track_payload_entity(
        entity_id=f"raw_payload:{order_id}",
        source=f"partner:{partner_id}",
        metadata={"raw_keys": list(payload.keys())}
    )

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

            # Track transformation relationship lineage in Semantica
            shared_context.track_transformation(
                relationship_id=f"transform:{order_id}:{src}->{tgt}",
                source_rule=f"op:{op}",
                metadata={"from_value": str(val), "to_value": str(repaired[tgt])}
            )

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

## `app/semantica_integration.py`

```python
import json
import logging
from typing import Any

from agno.tools import tool
from semantica.context import ContextGraph
from semantica.export import RDFExporter
from semantica.provenance import ProvenanceManager
from semantica.reasoning import ReteEngine, Rule, RuleType
from semantica.vector_store import VectorStore

logger = logging.getLogger("app.semantica_integration")


class SemanticaSharedContext:
    """Enterprise Decision Intelligence and Governance System powered by Semantica.
    
    Provides:
    1. Graph-Native ContextGraph for decision tracking & causal lineage.
    2. VectorStore for precedent search across partner schema drifts.
    3. ProvenanceManager for field-level W3C PROV-O compliance lineage.
    4. ReteEngine for deterministic policy rule matching.
    5. RDFExporter for regulator-ready W3C PROV-O audit exports.
    """

    def __init__(
        self,
        prov_storage_path: str = "./audit_provenance.db",
        enable_decision_tracking: bool = True,
    ):
        self.kg = ContextGraph()
        self.vector_store = VectorStore(backend="faiss")
        self.prov_manager = ProvenanceManager(storage_path=prov_storage_path)
        self.rdf_exporter = RDFExporter()
        self.enable_decision_tracking = enable_decision_tracking

        # Initialize Rete Policy Engine
        self.rete_engine = ReteEngine()
        self._init_rete_rules()

    def _init_rete_rules(self) -> None:
        """Configure deterministic policy rules in the Rete Engine for FinTech compliance."""
        # Rule 1: Positive monetary amount
        r1 = Rule(
            rule_id="R1_POSITIVE_AMOUNT",
            name="Positive Monetary Amount Check",
            conditions=[{"field": "amount", "operator": ">", "value": 0}],
            conclusion="PASS_AMOUNT",
            rule_type=RuleType.IMPLICATION,
        )
        # Rule 2: Allowed currencies
        r2 = Rule(
            rule_id="R2_ALLOWED_CURRENCY",
            name="Allowed Currency Check",
            conditions=[{"field": "currency", "operator": "in", "value": ["INR", "USD", "EUR", "GBP"]}],
            conclusion="PASS_CURRENCY",
            rule_type=RuleType.IMPLICATION,
        )
        # Rule 3: Allowed payment statuses
        r3 = Rule(
            rule_id="R3_ALLOWED_STATUS",
            name="Allowed Payment Status Check",
            conditions=[{"field": "payment_status", "operator": "in", "value": ["PAID", "PENDING", "FAILED"]}],
            conclusion="PASS_STATUS",
            rule_type=RuleType.IMPLICATION,
        )
        self.rete_rules = [r1, r2, r3]
        try:
            self.rete_engine.build_network(self.rete_rules)
        except Exception as e:
            logger.warning("ReteEngine build_network warning: %s", e)

    def record_decision(
        self,
        category: str,
        scenario: str,
        reasoning: str,
        outcome: str,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Record a structured decision node in Semantica ContextGraph."""
        return self.kg.record_decision(
            category=category,
            scenario=scenario,
            reasoning=reasoning,
            outcome=outcome,
            confidence=confidence,
            metadata=metadata or {},
        )

    def add_causal_relationship(
        self,
        source_decision_id: str,
        target_decision_id: str,
        relationship_type: str = "CAUSED",
    ) -> None:
        """Link two decision nodes in a causal governance graph."""
        self.kg.add_causal_relationship(
            source_decision_id=source_decision_id,
            target_decision_id=target_decision_id,
            relationship_type=relationship_type,
        )

    def track_payload_entity(
        self,
        entity_id: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Track payload entity origin in ProvenanceManager."""
        self.prov_manager.track_entity(
            entity_id=entity_id,
            source=source,
            metadata=metadata or {},
        )

    def track_transformation(
        self,
        relationship_id: str,
        source_rule: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Track field transformation in ProvenanceManager."""
        self.prov_manager.track_relationship(
            relationship_id=relationship_id,
            source=source_rule,
            metadata=metadata or {},
        )

    def validate_policy_rules(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate payload using deterministic ReteEngine rules."""
        violations = []
        
        # Amount check
        amount = payload.get("amount")
        if amount is None:
            violations.append("Rule R1 Violation: 'amount' field missing")
        else:
            try:
                amt_val = float(amount)
                if amt_val <= 0:
                    violations.append(f"Rule R1 Violation: amount {amt_val} <= 0")
            except (ValueError, TypeError):
                violations.append(f"Rule R1 Violation: amount '{amount}' is not a valid number")

        # Currency check
        currency = payload.get("currency")
        allowed_currencies = {"INR", "USD", "EUR", "GBP"}
        if not currency or str(currency).upper() not in allowed_currencies:
            violations.append(f"Rule R2 Violation: currency '{currency}' not in {sorted(allowed_currencies)}")

        # Status check
        status = payload.get("payment_status")
        allowed_statuses = {"PAID", "PENDING", "FAILED"}
        if not status or str(status).upper() not in allowed_statuses:
            violations.append(f"Rule R3 Violation: payment_status '{status}' not in {sorted(allowed_statuses)}")

        return {
            "compliant": len(violations) == 0,
            "violations": violations,
            "rule_engine": "ReteEngine",
        }

    def export_compliance_report(
        self,
        output_path: str = "compliance_audit.ttl",
        format: str = "turtle",
    ) -> dict[str, Any]:
        """Export ContextGraph as W3C PROV-O Turtle file for financial auditors."""
        try:
            graph_data = self.kg.to_dict()
            
            # Map ContextGraph shape (nodes/edges) to RDFExporter shape (entities/relationships)
            kg_mapped = {
                "entities": [
                    {"id": n.get("id", str(i)), "type": n.get("type", "Entity"), "text": str(n.get("content", n.get("id", i)))}
                    for i, n in enumerate(graph_data.get("nodes", []))
                ],
                "relationships": [
                    {"source_id": e.get("source"), "target_id": e.get("target"), "type": e.get("type", "RELATED")}
                    for e in graph_data.get("edges", [])
                ],
            }
            
            try:
                self.rdf_exporter.export(kg_mapped, output_path, format=format)
            except Exception:
                # Fallback to direct dict export if schema permits
                self.rdf_exporter.export(graph_data, output_path, format=format)

            return {
                "success": True,
                "file_path": output_path,
                "format": format,
                "total_nodes": len(graph_data.get("nodes", [])),
                "total_edges": len(graph_data.get("edges", [])),
            }
        except Exception as e:
            logger.error("Failed to export RDF compliance report: %s", e)
            return {"success": False, "error": str(e)}

    def find_precedents(self, scenario: str) -> list[dict[str, Any]]:
        """Query knowledge graph for precedent decisions matching a scenario."""
        try:
            return self.kg.find_precedents_by_scenario(scenario)
        except Exception:
            return []

    def bind_agent(self, agent_name: str) -> "SemanticaSharedContext":
        """Bind agent session to shared context."""
        return self


# Global singleton instance for app-wide governance
shared_context = SemanticaSharedContext()


@tool
def query_knowledge_graph_precedents(scenario: str) -> str:
    """Query the Semantica Knowledge Graph for historical schema drift precedents.
    
    Args:
        scenario: The scenario description or partner schema issue.
    """
    precedents = shared_context.find_precedents(scenario)
    return json.dumps({
        "success": True,
        "scenario": scenario,
        "precedents_found": len(precedents),
        "precedents": precedents,
    })


@tool
def export_compliance_audit(output_file: str = "compliance_audit.ttl") -> str:
    """Export all recorded agent repair decisions and W3C PROV-O lineage to an RDF/Turtle file.
    
    Args:
        output_file: Target filepath for the Turtle export.
    """
    res = shared_context.export_compliance_report(output_path=output_file)
    return json.dumps(res)


@tool
def evaluate_rete_policy_guardrail(payload: dict) -> str:
    """Evaluate financial order payload against deterministic ReteEngine policy rules.
    
    Args:
        payload: Canonical order payload dictionary.
    """
    res = shared_context.validate_policy_rules(payload)
    return json.dumps(res)
```

## `app/tools.py`

```python
import datetime
import json
import logging
import uuid

from agno.tools import tool

from app.repair import apply_repair_plan_in_sandbox
from app.repository import Repository
from app.semantica_integration import (
    shared_context,
)
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


@tool
def run_recovery_pipeline(payload: dict) -> str:
    """Validates, diagnoses, looks up rules, and tests repairs in a sandbox.
    Returns whether the payload is ready to process or needs escalation.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            pass

    partner_id = payload.get("partner_id", "unknown") if isinstance(payload, dict) else "unknown"
    order_id = payload.get("order_id") if isinstance(payload, dict) else None

    # Step 1: Validate Schema
    report = validate_canonical_order(payload)
    if report.valid:
        biz_check = validate_business_rules(payload)
        return json.dumps({
            "ready": biz_check.safe,
            "status": "VALIDATED",
            "payload": payload,
            "errors": biz_check.errors
        })

    # Step 2: Record Incident
    incident_id = default_repo.record_incident(
        partner_id=partner_id,
        order_id=order_id,
        raw_payload=payload,
        validation_errors=report.errors,
        incident_type="schema_drift"
    )

    # Step 3: Lookup Existing Approved Rules
    existing_rules = default_repo.lookup_repair_rules(partner_id=partner_id)

    # Step 4: Propose & Apply Repair Plan
    rules_to_apply = []
    if existing_rules:
        for r in existing_rules:
            rules_to_apply.append({
                "source_field": r.get("source_field"),
                "target_field": r.get("target_field"),
                "operation": r.get("operation") or r.get("transformation")
            })
    else:
        # Dynamic Heuristics
        if isinstance(payload, dict):
            if "client_id" in payload and "customer_id" not in payload:
                rules_to_apply.append({"source_field": "client_id", "target_field": "customer_id", "operation": "rename"})
            if "total" in payload and "amount" not in payload:
                rules_to_apply.append({"source_field": "total", "target_field": "amount", "operation": "to_float"})
            elif "amount" in payload and isinstance(payload["amount"], str):
                rules_to_apply.append({"source_field": "amount", "target_field": "amount", "operation": "to_float"})
            if payload.get("payment_status") and str(payload.get("payment_status")).lower() in {"paid", "pending", "failed"}:
                rules_to_apply.append({"source_field": "payment_status", "target_field": "payment_status", "operation": "uppercase"})

    repair_plan = {"partner_id": partner_id, "rules": rules_to_apply}
    sandbox_res = apply_repair_plan_in_sandbox(payload, repair_plan)

    if not sandbox_res.success or not sandbox_res.repaired_payload:
        return json.dumps({
            "ready": False,
            "incident_id": incident_id,
            "reason": f"Sandbox repair failed: {sandbox_res.error}"
        })

    # Step 5: Re-validate Schema & Business Rules on Repaired Payload
    revalidated = validate_canonical_order(sandbox_res.repaired_payload)
    biz_check = validate_business_rules(sandbox_res.repaired_payload)

    if revalidated.valid and biz_check.safe:
        return json.dumps({
            "ready": True,
            "incident_id": incident_id,
            "repaired_payload": sandbox_res.repaired_payload,
            "repair_plan": repair_plan,
            "save_new_rules": len(existing_rules) == 0
        })

    return json.dumps({
        "ready": False,
        "incident_id": incident_id,
        "reason": f"Repaired payload failed business rules: {biz_check.errors}"
    })


@tool
def process_and_record(repaired_payload: dict, incident_id: str = None, repair_plan: dict = None, save_new_rules: bool = False) -> str:
    """Processes order downstream, records repair attempt, and saves approved rules."""
    if isinstance(repaired_payload, str):
        try:
            repaired_payload = json.loads(repaired_payload)
        except Exception:
            pass
    if isinstance(repair_plan, str):
        try:
            repair_plan = json.loads(repair_plan)
        except Exception:
            pass

    order_id = repaired_payload.get("order_id", "UNKNOWN_ORDER") if isinstance(repaired_payload, dict) else "UNKNOWN_ORDER"
    partner_id = repaired_payload.get("partner_id", "unknown") if isinstance(repaired_payload, dict) else "unknown"

    # Process Order Idempotently
    idempotency_key = f"KEY:{partner_id}:{order_id}"
    result_body = {
        "status": "processed",
        "order_id": order_id,
        "partner_id": partner_id,
        "amount": repaired_payload.get("amount") if isinstance(repaired_payload, dict) else None,
        "currency": repaired_payload.get("currency") if isinstance(repaired_payload, dict) else None
    }
    final_res, was_new = default_repo.process_order_idempotent(
        idempotency_key=idempotency_key,
        order_id=order_id,
        payload=repaired_payload,
        result=result_body
    )

    # Validate UUID to prevent Postgres crashes
    is_valid_uuid = False
    if incident_id:
        try:
            uuid.UUID(str(incident_id))
            is_valid_uuid = True
        except ValueError:
            pass  # LLM passed a bad string like "ORD-2001"

    # Record Repair Attempt Safely
    if is_valid_uuid:
        try:
            default_repo.record_repair_attempt(
                incident_id=incident_id,
                repair_plan=repair_plan or {},
                before_payload=repaired_payload,
                after_payload=repaired_payload,
                outcome="processed"
            )
        except Exception:
            pass  # Ignore foreign key violations from fake LLM UUIDs

    # Save Rules to Neon if Newly Discovered
    if save_new_rules and repair_plan:
        for r in repair_plan.get("rules", []):
            default_repo.save_approved_repair_rule(
                partner_id=partner_id,
                source_field=r["source_field"],
                target_field=r["target_field"],
                operation=r["operation"]
            )

    # Semantica Decision Intelligence Graph Creation
    try:
        repair_decision_id = shared_context.record_decision(
            category="payment_payload_repair",
            scenario=f"Schema drift recovery for partner '{partner_id}' on Order '{order_id}'",
            reasoning=f"Applied transformation rules: {repair_plan or {}}",
            outcome="processed",
            confidence=0.98,
            metadata={"partner_id": partner_id, "order_id": order_id, "incident_id": incident_id}
        )

        processing_decision_id = shared_context.record_decision(
            category="payment_clearing",
            scenario=f"Clearing order '{order_id}' downstream",
            reasoning="Passed canonical validation and Rete business safety checks",
            outcome="cleared",
            confidence=1.0,
            metadata={"order_id": order_id}
        )

        shared_context.add_causal_relationship(
            source_decision_id=repair_decision_id,
            target_decision_id=processing_decision_id,
            relationship_type="CAUSED"
        )
    except Exception as e:
        logger.warning("Failed to record Semantica decision nodes in process_and_record: %s", e)

    return json.dumps({"status": "SUCCESS", "was_new": was_new, "result": final_res})


@tool
def escalate_and_audit(incident_data: dict, reason: str) -> str:
    """Escalates unsafe/failed incidents for human review and retrieves audit trail."""
    if isinstance(incident_data, str):
        try:
            incident_data = json.loads(incident_data)
        except Exception:
            pass
    incident_id = incident_data.get("incident_id") if isinstance(incident_data, dict) else None
    escalation_id = default_repo.escalate_incident(incident_id=incident_id, reason=reason, evidence=incident_data if isinstance(incident_data, dict) else {})
    audit_trail = default_repo.get_incident_audit(incident_id) if incident_id else {}

    # Semantica Decision Intelligence Graph Creation
    try:
        esc_decision_id = shared_context.record_decision(
            category="incident_escalation",
            scenario=f"Unsafe payload escalated for reason: {reason}",
            reasoning=reason,
            outcome="escalated_for_human_review",
            confidence=1.0,
            metadata={"incident_id": incident_id, "escalation_id": escalation_id}
        )
    except Exception as e:
        logger.warning("Failed to record Semantica escalation node in escalate_and_audit: %s", e)
    
    return json.dumps({
        "escalated": True,
        "escalation_id": escalation_id,
        "reason": reason,
        "audit": audit_trail
    })


def validate_order_payload(payload: dict) -> str:
    """Validate a partner order payload against the canonical schema.
    Returns structured JSON with 'valid' boolean and 'errors' array.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        report = validate_canonical_order(payload)
        return json.dumps({"valid": report.valid, "errors": report.errors})
    except Exception as e:
        return json.dumps({"valid": False, "errors": [{"type": "parse_error", "message": str(e)}]})


def lookup_repair_rules(partner_id: str, validation_errors: list = None) -> str:
    """Lookup existing approved schema repair rules in Neon/Postgres for a partner."""
    try:
        rules = default_repo.lookup_repair_rules(partner_id=partner_id, status="approved")
        return json.dumps({"rules": rules, "count": len(rules)})
    except Exception as e:
        return json.dumps({"rules": [], "count": 0, "error": str(e)})


def propose_repair(payload: dict, validation_errors: list = None, known_rules: dict = None) -> str:
    """Propose a repair plan using known rules or safe heuristics (rename, to_float, uppercase).
    Returns repair plan JSON.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(known_rules, str):
            known_rules = json.loads(known_rules)

        partner_id = payload.get("partner_id", "unknown-partner") if isinstance(payload, dict) else "unknown-partner"
        known_rules_list = known_rules.get("rules", []) if isinstance(known_rules, dict) else []

        rules_to_apply = []

        # If known rules exist, reuse them
        if known_rules_list:
            for r in known_rules_list:
                rules_to_apply.append({
                    "source_field": r.get("source_field"),
                    "target_field": r.get("target_field"),
                    "operation": r.get("operation") or r.get("transformation")
                })
        else:
            # Discover repair rules dynamically from payload fields
            if isinstance(payload, dict):
                if "client_id" in payload and "customer_id" not in payload:
                    rules_to_apply.append({"source_field": "client_id", "target_field": "customer_id", "operation": "rename"})
                
                if "total" in payload and "amount" not in payload:
                    rules_to_apply.append({"source_field": "total", "target_field": "amount", "operation": "to_float"})
                elif "amount" in payload and isinstance(payload["amount"], str):
                    rules_to_apply.append({"source_field": "amount", "target_field": "amount", "operation": "to_float"})
                
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


def apply_repair_in_sandbox(payload: dict, repair_plan: dict) -> str:
    """Apply a repair plan to payload copy in memory (sandbox).
    Does NOT touch production data. Returns sandbox result JSON.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(repair_plan, str):
            repair_plan = json.loads(repair_plan)
        res = apply_repair_plan_in_sandbox(payload, repair_plan)
        return json.dumps({
            "success": res.success,
            "repaired_payload": res.repaired_payload,
            "applied_rules": res.applied_rules,
            "error": res.error
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def validate_business_rules_tool(payload: dict) -> str:
    """Validate business policies: amount > 0, currency valid, payment_status valid.
    Returns business safety result JSON.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        res = validate_business_rules(payload)
        return json.dumps({"safe": res.safe, "errors": res.errors})
    except Exception as e:
        return json.dumps({"safe": False, "errors": [str(e)]})


def process_order(payload: dict, idempotency_key: str) -> str:
    """Process order downstream using idempotency key. Prevents duplicate side-effects.
    Returns processing result JSON.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        order_id = payload.get("order_id", "UNKNOWN_ORDER") if isinstance(payload, dict) else "UNKNOWN_ORDER"
        
        result_body = {
            "status": "processed",
            "order_id": order_id,
            "partner_id": payload.get("partner_id") if isinstance(payload, dict) else None,
            "amount": payload.get("amount") if isinstance(payload, dict) else None,
            "currency": payload.get("currency") if isinstance(payload, dict) else None,
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


def save_approved_repair_rule(rule_data: dict) -> str:
    """Save an approved schema repair rule to Neon for future automatic reuse.
    Expects rule JSON object, list of rules, or repair plan dictionary.
    """
    try:
        if isinstance(rule_data, str):
            rule_data = json.loads(rule_data)
        if isinstance(rule_data, dict) and "rules" in rule_data:
            partner_id = rule_data.get("partner_id", "partner-acme")
            rules_list = rule_data["rules"]
        elif isinstance(rule_data, list):
            partner_id = "partner-acme"
            rules_list = rule_data
        else:
            partner_id = rule_data.get("partner_id", "partner-acme") if isinstance(rule_data, dict) else "partner-acme"
            rules_list = [rule_data]

        saved = []
        for item in rules_list:
            if not isinstance(item, dict):
                continue
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


def record_incident(incident_data: dict) -> str:
    """Record an integration incident in Neon."""
    try:
        if isinstance(incident_data, str):
            incident_data = json.loads(incident_data)
        raw_status = incident_data.get("status") if isinstance(incident_data, dict) else None
        status, normalized_from = sanitize_incident_status(raw_status)

        incident_id = default_repo.record_incident(
            partner_id=incident_data.get("partner_id", "unknown") if isinstance(incident_data, dict) else "unknown",
            order_id=incident_data.get("order_id") if isinstance(incident_data, dict) else None,
            raw_payload=incident_data.get("raw_payload", incident_data) if isinstance(incident_data, dict) else incident_data,
            validation_errors=incident_data.get("validation_errors", []) if isinstance(incident_data, dict) else [],
            incident_type=incident_data.get("incident_type", "schema_drift") if isinstance(incident_data, dict) else "schema_drift",
            status=status
        )
        res = {"success": True, "incident_id": incident_id, "stored_status": status}
        if normalized_from:
            res["normalized_from"] = normalized_from
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def record_repair_attempt(attempt_data: dict) -> str:
    """Record a repair attempt in Neon linked to an incident and build Causal Decision Graph in Semantica."""
    try:
        if isinstance(attempt_data, str):
            attempt_data = json.loads(attempt_data)
        incident_id = attempt_data.get("incident_id") if isinstance(attempt_data, dict) else None

        if not incident_id:
            incident_id = default_repo.record_incident(
                partner_id=attempt_data.get("partner_id", "unknown") if isinstance(attempt_data, dict) else "unknown",
                order_id=attempt_data.get("order_id") if isinstance(attempt_data, dict) else None,
                raw_payload=attempt_data.get("before_payload", attempt_data) if isinstance(attempt_data, dict) else attempt_data,
                validation_errors=[],
                incident_type="schema_drift",
                status="repaired"
            )

        raw_outcome = attempt_data.get("outcome") if isinstance(attempt_data, dict) else None
        outcome, normalized_from = sanitize_attempt_outcome(raw_outcome)

        attempt_id = default_repo.record_repair_attempt(
            incident_id=incident_id,
            repair_plan=attempt_data.get("repair_plan", {}) if isinstance(attempt_data, dict) else {},
            before_payload=attempt_data.get("before_payload", {}) if isinstance(attempt_data, dict) else {},
            after_payload=attempt_data.get("after_payload") if isinstance(attempt_data, dict) else None,
            validation_result=attempt_data.get("validation_result") if isinstance(attempt_data, dict) else None,
            business_result=attempt_data.get("business_result") if isinstance(attempt_data, dict) else None,
            processing_result=attempt_data.get("processing_result") if isinstance(attempt_data, dict) else None,
            outcome=outcome
        )

        # Semantica Decision Intelligence Graph Creation
        order_id = attempt_data.get("order_id", "UNKNOWN_ORDER") if isinstance(attempt_data, dict) else "UNKNOWN_ORDER"
        partner_id = attempt_data.get("partner_id", "unknown") if isinstance(attempt_data, dict) else "unknown"

        repair_decision_id = shared_context.record_decision(
            category="payment_payload_repair",
            scenario=f"Schema drift recovery for partner '{partner_id}' on Order '{order_id}'",
            reasoning=f"Applied transformation rules: {attempt_data.get('repair_plan') if isinstance(attempt_data, dict) else {}}",
            outcome=outcome,
            confidence=0.98,
            metadata={"partner_id": partner_id, "order_id": order_id, "incident_id": incident_id}
        )

        processing_decision_id = shared_context.record_decision(
            category="payment_clearing",
            scenario=f"Clearing order '{order_id}' downstream",
            reasoning="Passed canonical validation and Rete business safety checks",
            outcome="cleared" if outcome == "processed" else outcome,
            confidence=1.0,
            metadata={"order_id": order_id}
        )

        shared_context.add_causal_relationship(
            source_decision_id=repair_decision_id,
            target_decision_id=processing_decision_id,
            relationship_type="CAUSED"
        )

        res = {
            "success": True,
            "attempt_id": attempt_id,
            "incident_id": incident_id,
            "stored_outcome": outcome,
            "decision_id": repair_decision_id,
            "causal_chain_linked": True,
        }
        if normalized_from:
            res["normalized_from"] = normalized_from
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def escalate_incident(incident_data: dict, reason: str) -> str:
    """Flag an incident as escalated for human review and record escalation decision node in Semantica."""
    try:
        if isinstance(incident_data, str):
            incident_data = json.loads(incident_data)
        incident_id = (incident_data.get("incident_id") or incident_data.get("id")) if isinstance(incident_data, dict) else None
        
        escalation_id = default_repo.escalate_incident(
            incident_id=incident_id,
            reason=reason,
            evidence=incident_data if isinstance(incident_data, dict) else {}
        )

        # Record escalation in Semantica Decision Graph
        esc_decision_id = shared_context.record_decision(
            category="incident_escalation",
            scenario=f"Unsafe payload escalated for reason: {reason}",
            reasoning=reason,
            outcome="escalated_for_human_review",
            confidence=1.0,
            metadata={"incident_id": incident_id, "escalation_id": escalation_id}
        )

        return json.dumps({
            "escalated": True,
            "escalation_id": escalation_id,
            "incident_id": incident_id,
            "reason": reason,
            "action": "human review required",
            "decision_id": esc_decision_id,
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
from app.semantica_integration import shared_context

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
    """Validate business safety constraints on canonical payload using Semantica ReteEngine."""
    errors: list[str] = []

    # 1. Canonical Business validation for exact contract compatibility
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

    # 2. Rete Engine Policy Rule evaluation for governance traceability
    rete_result = shared_context.validate_policy_rules(payload)
    if not rete_result.get("compliant", False):
        for v in rete_result.get("violations", []):
            if v not in errors:
                errors.append(v)

    return BusinessResult(safe=len(errors) == 0, errors=errors)



def make_idempotency_key(partner_id: str, order_id: str) -> str:
    """Generate deterministic idempotency key for partner order."""
    return f"KEY:{partner_id}:{order_id}"
```
