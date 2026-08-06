<!-- ---
title: Integration Recovery Agent
emoji: 🛠️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
--- -->

# Integration Recovery Agent

An autonomous **Integration Recovery Agent** built with **Agno (v2.7.2)**, **Neon PostgreSQL**, **NVIDIA LLM Provider**, and **AgentOS**.

The system receives partner order events, detects integration failures and schema drift, safely repairs payloads in an in-memory sandbox, validates business rules, processes orders with deterministic idempotency keys, persists approved repair rules in Neon DB for automated zero-shot reuse, and escalates unsafe or ambiguous incidents for human review.

---

## Technical Features

1. **Deterministic Dual-Stage Validation**:
   - **Canonical Schema Validation**: Checks incoming payloads strictly against required canonical fields (`partner_id`, `order_id`, `customer_id`, `amount`, `currency`, `payment_status`) and flags field aliases or unexpected fields.
   - **Business Safety Validation**: Enforces hard policies (`amount > 0`, allowed currency lists, valid payment statuses).

2. **In-Memory Sandbox Repair**:
   - Applies schema transformations (`rename`, `to_float`, `uppercase`) safely in memory without mutating production data or database state.

3. **Dynamic Repair Rule Learning & Reuse**:
   - Persists approved repair rules in Neon/Postgres DB with hit counts (`hit_count`).
   - Automatically reuses learned rules on repeated partner drift to instantly repair subsequent orders without re-discovering transformations.

4. **Idempotency & Duplicate Prevention**:
   - Generates deterministic idempotency keys (`KEY:{partner_id}:{order_id}`) to prevent duplicate downstream order processing side-effects.

5. **Native Tool Function Calling & Parsing Safety**:
   - Tool signatures in `app/tools.py` accept typed native data structures (`dict`, `list`, `str`) for native LLM object parsing, eliminating nested JSON string-escaping syntax errors (`Expecting ',' delimiter`).

6. **Rate-Limit Guardrails & Circuit Breakers**:
   - Agno agent configuration includes retry backoff (`delay_between_retries=10`, `retries=1`) and system instructions to stop execution cleanly if hard API rate limits (`ResourceExhausted`) occur.

7. **Agno Tracing, Memory & AgentOS Runtime**:
   - Built with OpenTelemetry tracing and Learning Machine memory (`LearningMachine`).
   - Exposes standard OpenAI-compatible and Agno control plane API endpoints via FastAPI.

---

## Repository Structure

```text
integration-recovery-agent/
├── app/
│   ├── __init__.py
│   ├── agent.py         # Agno Agent definition & instructions
│   ├── config.py        # Environment settings & fallback configs
│   ├── db.py            # SQLite & Neon/Postgres database driver & migrations
│   ├── main.py          # FastAPI application & Agno AgentOS entrypoint
│   ├── repair.py        # In-memory sandbox repair execution engine
│   ├── repository.py    # Database repository layer (Postgres / SQLite)
│   ├── schemas.py       # Pydantic data models & validation reports
│   ├── tools.py         # Agent tool definitions with native dict parameter signatures
│   └── validators.py    # Schema and business rule validation logic
├── migrations/
│   └── 001_initial.sql # PostgreSQL initial database schema
├── scripts/
│   ├── export_app_codebase.py # Codebase exporter script
│   └── run_demo.py     # Standalone demo script running all 4 scenarios
├── tests/
│   ├── test_agent_tools.py # Unit tests for agent tool signatures & flows
│   ├── test_repair.py      # Unit tests for sandbox repair engine
│   ├── test_repository.py  # Unit tests for repository layer
│   └── test_validators.py  # Unit tests for canonical & business validators
├── Dockerfile           # Production container definition
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
| `NVIDIA_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b` | Model identifier for NVIDIA LLM provider. |
| `PORT` | `7860` | Server HTTP port (default: `7860` for Hugging Face Spaces compatibility). |
| `ENVIRONMENT` | `local` | Environment mode (`local`, `production`, etc.). |

---

## Quickstart & Local Development

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Test Suite
Run the 21 automated unit tests across validators, repository layer, sandbox repair engine, and agent tools:
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
