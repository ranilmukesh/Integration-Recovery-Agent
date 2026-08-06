<!-- ---
title: Integration Recovery Agent
emoji: 🛠️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
--- -->

# Integration Recovery Agent

An autonomous **Integration Recovery Agent** built with **Agno (v2.7.2)**, **Neon/Postgres**, **NVIDIA LLM provider**, and **AgentOS**.

The system receives partner order events, detects integration failures and schema drift, safely repairs payloads in an in-memory sandbox, validates business rules, retries order processing with idempotency keys, persists approved repair rules in Neon for automatic reuse, and escalates unsafe or ambiguous incidents.

---

## Technical Features

1. **Deterministic Schema & Business Rules**: Enforces strict canonical order schemas and business safety policies (e.g. `amount > 0`).
2. **In-Memory Sandbox Repair**: Tests schema transformations (`rename`, `to_float`, `uppercase`) safely in memory without mutating production data.
3. **Idempotent Processing**: Prevents duplicate downstream order processing side-effects.
4. **Agno Tracing & Learning Machine**: Integrates OpenTelemetry tracing and automatic learning memory across user sessions.
5. **FastAPI AgentOS Runtime**: Exposes standard OpenAI-compatible and Agno control plane API endpoints.

---

## Repository Structure

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
└── README.md
```

---

## Environment Secrets / Setup

Configure the following secrets in your Hugging Face Space settings or local `.env` file:

| Variable | Description |
|---|---|
| `NEON_DB_URL` | Neon PostgreSQL Connection URL (`postgresql+psycopg://...`) |
| `NVIDIA_API_KEY` | NVIDIA Inference API Key (`nvapi-...`) |
| `NVIDIA_MODEL` | NVIDIA Model Identifier (default: `stepfun-ai/step-3.7-flash` or `meta/llama-3.3-70b-instruct`) |
| `PORT` | App server port (default: `7860`) |

---

## Deploying to Hugging Face Spaces

1. Create a new Space on [Hugging Face](https://huggingface.co/new-space) and select **Docker** as the SDK.
2. Push this repository to your Hugging Face Space repository.
3. Add `NEON_DB_URL` and `NVIDIA_API_KEY` under **Space Settings -> Repository Secrets**.
4. Hugging Face Spaces will automatically build the container and serve the AgentOS API at port `7860`.

---

## Local Development & Docker Commands

### Install Dependencies locally
```bash
pip install -r requirements.txt
```

### Run Unit Tests
```bash
pytest
```

### Run Demonstration Scenarios
```bash
python scripts/run_demo.py
```

### Build & Run Docker Container locally
```bash
docker build -t integration-recovery-agent .
docker run -p 7860:7860 --env-file .env integration-recovery-agent
```

```bash
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

---

## Connecting to os.agno.com Control Plane

1. Start AgentOS locally or on Hugging Face Spaces at port `7860`.
2. Open [os.agno.com](https://os.agno.com).
3. Connect custom endpoint: `http://localhost:7860` (or your Hugging Face Space direct URL).
4. View real-time Agent runs, Traces, and Learnings from the Agno control plane interface.
