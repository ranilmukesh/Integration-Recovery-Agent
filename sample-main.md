import os
import subprocess
import time
import json
import sqlite3
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError
from agno.agent import Agent
from agno.models.ollama import Ollama
from agno.db.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.tools import tool
from rich.pretty import pprint
import nest_asyncio

nest_asyncio.apply()

# ==========================================
# 1. INFRASTRUCTURE
# ==========================================
print("🚀 Launching Ollama Server...")
subprocess.Popen(["ollama", "serve"])
time.sleep(5)

# LFM2.5-2.6B — purpose-built for agentic tool-calling, ~1.7GB Q4_K_M,
# comfortably fits a Colab T4. Confirmed working in prior run.
MODEL_ID = "hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M"
subprocess.run(["ollama", "pull", MODEL_ID], capture_output=True)

os.makedirs("tmp", exist_ok=True)

# ==========================================
# 2. PERSISTENT MEMORY — SQLite ledger for schema corrections
# ==========================================
CORRECTIONS_DB = "tmp/healing_memory.db"

def _get_conn():
    conn = sqlite3.connect(CORRECTIONS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_corrections (
            wrong_key   TEXT PRIMARY KEY,
            correct_key TEXT NOT NULL,
            hit_count   INTEGER DEFAULT 1,
            first_seen  TEXT,
            last_seen   TEXT
        )
    """)
    conn.commit()
    return conn

def _load_corrections() -> dict:
    conn = _get_conn()
    rows = conn.execute("SELECT wrong_key, correct_key FROM schema_corrections").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

# ==========================================
# 3. CORE SCHEMA
# ==========================================
class Transaction(BaseModel):
    tx_id: str
    amount: float
    currency: str

# ==========================================
# 4. TOOLS
# ==========================================
@tool
def process_data_pipeline(raw_json_str: str) -> str:
    """
    Submits JSON data to the strict Transaction processing pipeline.
    Always call this first when given new data.
    Returns SUCCESS or a VALIDATION ERROR with details.
    """
    try:
        raw_data = json.loads(raw_json_str.replace("'", '"'))
    except json.JSONDecodeError:
        return "ERROR: Invalid JSON format."

    print(f"\n[⚙️  PIPELINE] Received: {raw_data}")

    # AUTO-HEAL: apply known corrections loaded from SQLite
    corrections = _load_corrections()
    for k in list(raw_data.keys()):
        if k in corrections:
            correct_key = corrections[k]
            print(f"[✨ AUTO-HEAL] SQLite memory: '{k}' -> '{correct_key}'")
            raw_data[correct_key] = raw_data.pop(k)

    try:
        clean = Transaction(**raw_data)
        return f"SUCCESS: {clean.model_dump()}"
    except ValidationError as e:
        msg = f"VALIDATION ERROR: {e.errors()}"
        print(f"[🚨 ALERT] {msg}")
        return (
            msg
            + " -> Call 'record_schema_correction' with the wrong key and correct key, "
              "then retry 'process_data_pipeline' with the ORIGINAL data."
        )

@tool
def record_schema_correction(wrong_key: str, correct_key: str) -> str:
    """
    Persists a schema correction to the SQLite healing ledger (tmp/healing_memory.db).
    Call this when process_data_pipeline returns a VALIDATION ERROR due to a wrong key name.

    Args:
        wrong_key:   The bad field name seen in the incoming data (e.g. 'transaction_id').
        correct_key: The correct schema field name (e.g. 'tx_id').
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    existing = conn.execute(
        "SELECT hit_count FROM schema_corrections WHERE wrong_key=?", (wrong_key,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE schema_corrections SET hit_count=hit_count+1, last_seen=? WHERE wrong_key=?",
            (now, wrong_key),
        )
        msg = f"MEMORY UPDATED (hit #{existing[0] + 1}): '{wrong_key}' -> '{correct_key}'"
    else:
        conn.execute(
            "INSERT INTO schema_corrections VALUES (?,?,1,?,?)",
            (wrong_key, correct_key, now, now),
        )
        msg = f"MEMORY SAVED (new rule): '{wrong_key}' -> '{correct_key}'"

    conn.commit()
    conn.close()
    print(f"\n[🧠 LEDGER] {msg}")
    return msg + ". Now retry process_data_pipeline with the original data."

@tool
def get_healing_ledger() -> str:
    """
    Returns all learned schema corrections from the persistent SQLite ledger.
    Use this to audit what the system has learned so far.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT wrong_key, correct_key, hit_count, first_seen FROM schema_corrections ORDER BY hit_count DESC"
    ).fetchall()
    conn.close()
    if not rows:
        return "Ledger is empty - no corrections learned yet."
    lines = ["Healing Ledger:"]
    for r in rows:
        lines.append(f"  '{r[0]}' -> '{r[1]}' | hits: {r[2]} | first seen: {r[3]}")
    return "\n".join(lines)

# ==========================================
# 5. AGENT
# ==========================================
agent_db = SqliteDb(db_file="tmp/agent_sessions.db")  # persistent session + run history

SYSTEM_PROMPT = """
You are a Self-Healing Data Engineer AI responsible for ingesting financial transactions.

Target schema: tx_id (str), amount (float), currency (str).

Workflow:
1. Call process_data_pipeline with the raw data.
2. If SUCCESS -> done.
3. If VALIDATION ERROR -> identify the mismatched key from the error details.
4. Call record_schema_correction(wrong_key, correct_key).
5. Retry process_data_pipeline with the EXACT original data to confirm auto-healing.
6. Optionally call get_healing_ledger to show what has been learned.
"""

agent = Agent(
    model=Ollama(id=MODEL_ID),
    tools=[process_data_pipeline, record_schema_correction, get_healing_ledger],
    instructions=[SYSTEM_PROMPT],
    db=agent_db,                      # SQLite-backed session storage
    add_history_to_context=True,      # agent remembers prior runs in session
    debug_mode=True,                  # full verbose logs, payloads, tool call details
    markdown=True,
)

# ==========================================
# 6. STREAMING + METRICS RUNNER
# ==========================================
def run_with_metrics(prompt: str):
    response = None
    for event in agent.run(prompt, stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            response = event
        else:
            print(event.content or "", end="", flush=True)
    print()  # newline after stream

    if response and response.metrics:
        print("\n--- RUN METRICS ---")
        pprint(response.metrics.to_dict())
        for msg in response.messages:
            if msg.role == "assistant" and msg.metrics:
                pprint(msg.metrics.to_dict())
    return response

# ==========================================
# 7. DEMO EXECUTION
# ==========================================
print("\n" + "=" * 55)
print("🎬  SELF-HEALING PIPELINE DEMO (LFM2.5-2.6B + SQLite)")
print("=" * 55)

print("\n--- 🟢 SCENARIO 1: Clean data (baseline) ---")
run_with_metrics("Process this: {'tx_id': 'TX-001', 'amount': 500.0, 'currency': 'USD'}")

print("\n--- 🟡 SCENARIO 2: Schema drift - 'transaction_id' instead of 'tx_id' ---")
run_with_metrics("Process this: {'transaction_id': 'TX-002', 'amount': 750.0, 'currency': 'EUR'}")

print("\n--- 🟢 SCENARIO 3: Same drift - auto-healed from SQLite ledger ---")
run_with_metrics(
    "Process this. The pipeline should auto-heal: "
    "{'transaction_id': 'TX-003', 'amount': 900.0, 'currency': 'GBP'}"
)

print("\n--- 🔵 SCENARIO 4: Audit the healing ledger ---")
run_with_metrics("Show me everything the system has learned so far.")

print("\n✅ DEMO COMPLETE")
print(f"Persistent correction ledger: {CORRECTIONS_DB}")
print(f"Persistent session history:  tmp/agent_sessions.db")