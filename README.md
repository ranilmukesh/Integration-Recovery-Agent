<!-- ---
title: Integration Recovery Agent
emoji: 🛠️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
--- -->

# Integration Recovery Agent

An autonomous **B2B Payment Integration Recovery Agent** built with **Agno (v2.7.2)**, **Semantica (Graph Intelligence & Governance)**, **Neon PostgreSQL**, **NVIDIA LLM Provider (`nvidia/nemotron-3.5-lightning-30b-a3b`)**, and **AgentOS**.

The system intercepts partner order payloads, diagnoses schema drift, safely repairs payloads in an in-memory sandbox, evaluates deterministic Rete Engine policy rules, tracks W3C PROV-O causal lineage, processes orders with idempotency keys, persists approved repair rules in Neon DB for automated zero-shot reuse, exports regulator-ready RDF Turtle audit trails, and escalates unsafe or ambiguous incidents for human review.

---

## Technical Features & Architecture

1. **Swarm Multi-Agent Architecture (`TeamMode.coordinate`)**:
   - **Payment Schema Diagnostic Agent (`diagnostic-agent`)**: Intercepts malformed payloads, queries knowledge graph precedents, and runs sandbox repair.
   - **Financial Policy & Compliance Agent (`compliance-agent`)**: Evaluates deterministic Rete policy guardrails, executes idempotent transaction clearing, and exports W3C PROV-O audit trails.
   - **B2B Payment Recovery Team (`recovery_team`)**: Swarm Orchestrator managing multi-agent handoffs with hard delegation bounds and anti-looping guardrails (`tool_call_limit=4` on team, `tool_call_limit=3` on sub-agents, `max_tokens=2048`).

2. **Semantica Decision Intelligence & Graph Governance**:
   - **Graph-Native `ContextGraph`**: Tracks all autonomous decisions (repair, clearing, escalation) and builds causal governance chains (`<CAUSED>` edges).
   - **Deterministic `ReteEngine`**: Evaluates policy rules (`R1_POSITIVE_AMOUNT`, `R2_ALLOWED_CURRENCY`, `R3_ALLOWED_STATUS`) prior to order clearing.
   - **W3C PROV-O `ProvenanceManager` & `RDFExporter`**: Generates regulator-ready RDF Turtle (`.ttl`) compliance audit trails (e.g. `audit_ORD-2002.ttl`, `compliance_audit.ttl`).
   - **FAISS `VectorStore`**: Queries historical precedent decisions across partner schema drift incidents.

3. **Deterministic Dual-Stage Validation**:
   - **Canonical Schema Validation**: Checks incoming payloads strictly against canonical fields (`partner_id`, `order_id`, `customer_id`, `amount`, `currency`, `payment_status`).
   - **Business Policy Guardrails**: Enforces hard compliance rules (`amount > 0`, allowed ISO currencies, allowed payment statuses).

4. **In-Memory Sandbox Repair**:
   - Applies schema transformations (`rename`, `to_float`, `uppercase`) safely in memory without mutating raw payloads or production state until validated.

5. **Dynamic Repair Rule Learning & Zero-Shot Reuse**:
   - Persists approved repair rules in Neon/Postgres DB with hit counts (`hit_count`).
   - Reuses learned rules on repeated partner drift to instantly repair subsequent orders without re-discovering transformations.

6. **Idempotency & Duplicate Prevention**:
   - Generates deterministic idempotency keys (`KEY:{partner_id}:{order_id}`) to prevent duplicate downstream order processing.

7. **FastAPI & AgentOS Compliance Endpoints**:
   - `GET /api/compliance/graph`: Returns Semantica ContextGraph representation (nodes & edges) for visualization dashboards.
   - `GET /api/compliance/export`: Generates and exports W3C PROV-O RDF Turtle compliance audit files (`compliance_audit.ttl`).
   - `GET /api/compliance/precedents`: Queries historical precedent decisions recorded in the Knowledge Graph.

---

## System Architecture & Data Flow

![Integration Recovery Agent - Swarm Orchestration & Semantica Governance Architecture](architecture.png)


### Architectural Component Specifications

1. **Ingress & Canonical Validation**: Intercepts partner payloads. If field name or data type mismatches occur (e.g. `client_id` instead of `customer_id`, string `total` instead of float `amount`), the event is flagged as a schema drift incident.
2. **Swarm Multi-Agent Orchestration**: Operates in Agno `coordinate` mode. The **Swarm Orchestrator** maintains rigid state-machine protocols, delegating Phase 1 to `diagnostic-agent` and Phase 2 to `compliance-agent` with strict anti-looping bounds.
3. **Semantica Graph Intelligence**:
   - **ReteEngine**: Provides zero-latency deterministic pattern matching for financial compliance rules prior to transaction clearance.
   - **ContextGraph**: Creates graph decision nodes (`payment_payload_repair`, `payment_clearing`) connected via `<CAUSED>` causal links.
   - **W3C PROV-O Audit**: Exports complete Turtle (`.ttl`) graph audit files for financial regulatory reporting.
4. **Idempotency & Zero-Shot Learning**: Approved schema repair rules are stored in Neon PostgreSQL. Subsequent occurrences of the same schema drift increment the rule's `hit_count` and execute zero-shot repair without re-discovering transformations.

---


## Repository Structure

```text
integration-recovery-agent/
├── app/
│   ├── __init__.py
│   ├── agent.py                 # Multi-agent Swarm (Team & sub-agents) definition
│   ├── config.py                # Environment settings & fallback configs
│   ├── db.py                    # SQLite & Neon/Postgres database pool & migrations
│   ├── main.py                  # FastAPI application & Agno AgentOS entrypoint + compliance endpoints
│   ├── repair.py                # In-memory sandbox repair execution engine & Semantica lineage tracking
│   ├── repository.py            # Database repository layer (Postgres / SQLite)
│   ├── schemas.py               # Pydantic data models & validation reports
│   ├── semantica_integration.py # Semantica ContextGraph, ReteEngine, Provenance & RDFExporter integration
│   ├── tools.py                 # Agno Agent tools (recovery pipeline, process & record, escalation)
│   └── validators.py            # Schema and business rule validation logic
├── migrations/
│   └── 001_initial.sql          # PostgreSQL initial database schema
├── scripts/
│   ├── export_app_codebase.py   # Codebase exporter script
│   └── run_demo.py              # Standalone demo script running all 4 scenarios
├── tests/
│   ├── test_agent_tools.py      # Unit tests for agent tool signatures & flows
│   ├── test_repair.py           # Unit tests for sandbox repair engine
│   ├── test_repository.py       # Unit tests for repository layer
│   ├── test_semantica.py        # Unit tests for Semantica ContextGraph, ReteEngine & RDF exports
│   └── test_validators.py       # Unit tests for canonical & business validators
├── Dockerfile                   # Production container definition
├── .dockerignore
├── .env.example
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Demonstration Scenarios

The system includes 4 built-in demonstration scenarios executed by `scripts/run_demo.py`:

| Scenario | Key | Description | Expected Outcome |
|---|---|---|---|
| **Scenario A** | `healthy_order` | Canonical order payload with correct types and values | Validated & processed immediately |
| **Scenario B** | `first_schema_drift` | First occurrence of schema drift (`client_id`, `total="1299.00"`, `payment_status="paid"`) | Incident logged -> Propose repair -> Sandbox verified -> Business checked -> Processed -> Repair rules saved in DB |
| **Scenario C** | `repeated_schema_drift` | Same partner sends drifted schema again | Looks up approved rules in DB -> Instant zero-shot repair -> Processed -> Rule hit count incremented |
| **Scenario D** | `unsafe_order` | Drifted schema with invalid negative amount (`total="-500.00"`) | Schema repaired in sandbox -> Business validation fails (`amount <= 0`) -> Safely escalated without processing |

---

## Environment Configuration

Configure the following environment variables in your local `.env` file or cloud secrets:

| Variable | Default | Description |
|---|---|---|
| `NEON_DB_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/integration_recovery_demo` | Connection string for Neon PostgreSQL database. Falls back to in-memory SQLite if unconfigured/unreachable. |
| `ALLOW_SQLITE_FALLBACK` | `true` | Enables automatic SQLite in-memory fallback for local development & testing. |
| `NVIDIA_API_KEY` | `""` | NVIDIA Inference API key (`nvapi-...`). |
| `NVIDIA_MODEL` | `nvidia/nemotron-3.5-lightning-30b-a3b` | Model identifier for NVIDIA LLM provider. |
| `PORT` | `7860` | Server HTTP port (default: `7860` for Hugging Face Spaces compatibility). |
| `ENVIRONMENT` | `local` | Environment mode (`local`, `production`, etc.). |

---

## Quickstart & Local Development

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Test Suite
Run the 30 automated unit tests across validators, repository layer, sandbox repair engine, agent tools, and Semantica graph governance:
```bash
pytest
```

### 3. Run Standalone Demonstration Scenarios
Run all 4 integration recovery demo scenarios end-to-end:
```bash
python scripts/run_demo.py
```

### 4. Start Local Server (FastAPI / AgentOS)
```bash
uvicorn app.main:app --host 0.0.0.0 --port 7860 --reload
```
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 7860
```

---

## Docker & Deployment

### Build & Run Docker Container Locally
```bash
docker build -t integration-recovery-agent .
docker run -p 7860:7860 --env-file .env integration-recovery-agent
```

### Deploying to Hugging Face Spaces
1. Create a new Space on [Hugging Face](https://huggingface.co/new-space) and select **Docker** as the SDK.
2. Push this repository to your Hugging Face Space repository.
3. Configure `NEON_DB_URL` and `NVIDIA_API_KEY` under **Space Settings -> Repository Secrets**.
4. Hugging Face Spaces will automatically build the image and serve the container on port `7860`.

---

## Connecting to os.agno.com Control Plane

1. Start AgentOS locally or on Hugging Face Spaces at port `7860`.
2. Navigate to [os.agno.com](https://os.agno.com).
3. Add custom endpoint: `http://localhost:7860` (or your HF Space URL).
4. Monitor real-time Agent runs, execution traces, session histories, and learning memory.
