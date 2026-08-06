import json
import os
import sys

# Ensure root workspace is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.tools as tools_mod
from app.db import get_db_connection, is_postgres, run_migrations


def run_all_demo_scenarios(db_url: str = ":memory:"):
    print("=" * 80)
    print(" INTEGRATION RECOVERY AGENT — DEMO EXECUTION ")
    print("=" * 80)

    # Initialize DB environment & tables
    try:
        run_migrations(db_url)
        conn = get_db_connection(db_url)
        cur = conn.cursor()
        if is_postgres(db_url):
            cur.execute("TRUNCATE TABLE repair_rules, integration_incidents, repair_attempts, processed_orders, escalations CASCADE;")
        else:
            cur.executescript("DELETE FROM repair_rules; DELETE FROM integration_incidents; DELETE FROM repair_attempts; DELETE FROM processed_orders; DELETE FROM escalations;")
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[Note] DB setup error ({e}). Using in-memory fallback.")
        db_url = ":memory:"
        run_migrations(db_url)

    repo = tools_mod.Repository(db_url=db_url)
    tools_mod.default_repo = repo

    # -------------------------------------------------------------------------
    # SCENARIO A: Healthy Event
    # -------------------------------------------------------------------------
    print("\n--- SCENARIO A: Healthy Event (healthy_order / ORD-2001) ---")
    fixture_a = json.loads(tools_mod.load_demo_scenario.entrypoint("healthy_order"))
    payload_a = fixture_a["payload"]
    print(f"Loaded Scenario: {fixture_a['scenario']} - {fixture_a['description']}")
    print(f"Incoming Payload: {json.dumps(payload_a)}")
    
    val_a = json.loads(tools_mod.validate_order_payload(json.dumps(payload_a)))
    print(f"1. Validation Result: valid={val_a['valid']}")
    assert val_a['valid'] is True

    biz_a = json.loads(tools_mod.validate_business_rules_tool(json.dumps(payload_a)))
    print(f"2. Business Rules Check: safe={biz_a['safe']}")
    assert biz_a['safe'] is True

    proc_a = json.loads(tools_mod.process_order(json.dumps(payload_a), "KEY:partner-acme:ORD-2001"))
    print(f"3. Order Processing Result: status={proc_a['status']}, was_new={proc_a['was_new']}")
    print("RESULT SCENARIO A: Processed Immediately [SUCCESS]")

    # -------------------------------------------------------------------------
    # SCENARIO B: First Schema Drift
    # -------------------------------------------------------------------------
    print("\n--- SCENARIO B: First Schema Drift (first_schema_drift / ORD-2002) ---")
    fixture_b = json.loads(tools_mod.load_demo_scenario.entrypoint("first_schema_drift"))
    payload_b = fixture_b["payload"]
    print(f"Loaded Scenario: {fixture_b['scenario']} - {fixture_b['description']}")
    print(f"Incoming Payload: {json.dumps(payload_b)}")

    val_b = json.loads(tools_mod.validate_order_payload(json.dumps(payload_b)))
    print(f"1. Validation Result: valid={val_b['valid']}, errors={val_b['errors']}")
    assert val_b['valid'] is False

    inc_res = json.loads(tools_mod.record_incident(json.dumps({
        "partner_id": "partner-acme",
        "order_id": "ORD-2002",
        "raw_payload": payload_b,
        "validation_errors": val_b['errors'],
        "incident_type": "schema_drift"
    })))
    inc_id_b = inc_res.get("incident_id")
    print(f"2. Incident Recorded: ID={inc_id_b} (res={inc_res})")

    rules_b = json.loads(tools_mod.lookup_repair_rules("partner-acme"))
    print(f"3. Existing Rules Search: count={rules_b['count']}")
    assert rules_b['count'] == 0

    plan_b = json.loads(tools_mod.propose_repair(json.dumps(payload_b), json.dumps(val_b['errors']), json.dumps(rules_b)))
    print(f"4. Proposed Repair Plan: {json.dumps(plan_b['rules'])}")

    sandbox_b = json.loads(tools_mod.apply_repair_in_sandbox(json.dumps(payload_b), json.dumps(plan_b)))
    print(f"5. Sandbox Repair Result: success={sandbox_b['success']}")
    assert sandbox_b['success'] is True
    print(f"   Repaired Payload: {json.dumps(sandbox_b['repaired_payload'])}")

    reval_b = json.loads(tools_mod.validate_order_payload(json.dumps(sandbox_b['repaired_payload'])))
    print(f"6. Sandbox Payload Re-validation: valid={reval_b['valid']}")
    assert reval_b['valid'] is True

    biz_b = json.loads(tools_mod.validate_business_rules_tool(json.dumps(sandbox_b['repaired_payload'])))
    print(f"7. Business Rules Check: safe={biz_b['safe']}")
    assert biz_b['safe'] is True

    proc_b = json.loads(tools_mod.process_order(json.dumps(sandbox_b['repaired_payload']), "KEY:partner-acme:ORD-2002"))
    print(f"8. Order Processing Result: status={proc_b['status']}")

    tools_mod.record_repair_attempt(json.dumps({
        "incident_id": inc_id_b,
        "repair_plan": plan_b,
        "before_payload": payload_b,
        "after_payload": sandbox_b['repaired_payload'],
        "validation_result": reval_b,
        "business_result": biz_b,
        "processing_result": proc_b,
        "outcome": "processed"
    }))

    save_b = json.loads(tools_mod.save_approved_repair_rule(json.dumps({
        "partner_id": "partner-acme",
        "rules": sandbox_b['applied_rules']
    })))
    print(f"9. Save Approved Repair Rules: {save_b}")
    print("RESULT SCENARIO B: Repaired, Processed, and Rules Saved [SUCCESS]")

    # -------------------------------------------------------------------------
    # SCENARIO C: Repeated Schema Drift (Reuse Rules)
    # -------------------------------------------------------------------------
    print("\n--- SCENARIO C: Repeated Schema Drift (repeated_schema_drift / ORD-2003) ---")
    fixture_c = json.loads(tools_mod.load_demo_scenario.entrypoint("repeated_schema_drift"))
    payload_c = fixture_c["payload"]
    print(f"Loaded Scenario: {fixture_c['scenario']} - {fixture_c['description']}")
    print(f"Incoming Payload: {json.dumps(payload_c)}")

    val_c = json.loads(tools_mod.validate_order_payload(json.dumps(payload_c)))
    print(f"1. Validation Result: valid={val_c['valid']}")
    assert val_c['valid'] is False

    rules_c = json.loads(tools_mod.lookup_repair_rules("partner-acme"))
    print(f"2. Existing Approved Rules Found: {rules_c}")
    assert rules_c['count'] > 0

    plan_c = json.loads(tools_mod.propose_repair(json.dumps(payload_c), json.dumps(val_c['errors']), json.dumps(rules_c)))
    print(f"3. Applying Known Rules Plan: {json.dumps(plan_c['rules'])}")

    sandbox_c = json.loads(tools_mod.apply_repair_in_sandbox(json.dumps(payload_c), json.dumps(plan_c)))
    print(f"4. Sandbox Repair Result: success={sandbox_c['success']}")
    assert sandbox_c['success'] is True

    reval_c = json.loads(tools_mod.validate_order_payload(json.dumps(sandbox_c['repaired_payload'])))
    print(f"5. Re-validation: valid={reval_c['valid']}")
    assert reval_c['valid'] is True

    proc_c = json.loads(tools_mod.process_order(json.dumps(sandbox_c['repaired_payload']), "KEY:partner-acme:ORD-2003"))
    print(f"6. Order Processing Result: status={proc_c['status']}")

    # Increment hit counts
    for r in sandbox_c['applied_rules']:
        repo.increment_rule_hit_count("partner-acme", r["source_field"], r["target_field"], r["operation"])
    
    updated_rules = repo.lookup_repair_rules("partner-acme")
    print(f"7. Updated Rule Hit Counts: {[r['hit_count'] for r in updated_rules]}")
    print("RESULT SCENARIO C: Known Rules Reused & Hit Counts Incremented [SUCCESS]")

    # -------------------------------------------------------------------------
    # SCENARIO D: Unsafe Business Failure
    # -------------------------------------------------------------------------
    print("\n--- SCENARIO D: Unsafe Business Failure (unsafe_order / ORD-2004) ---")
    fixture_d = json.loads(tools_mod.load_demo_scenario.entrypoint("unsafe_order"))
    payload_d = fixture_d["payload"]
    print(f"Loaded Scenario: {fixture_d['scenario']} - {fixture_d['description']}")
    print(f"Incoming Payload: {json.dumps(payload_d)}")

    val_d = json.loads(tools_mod.validate_order_payload(json.dumps(payload_d)))
    print(f"1. Initial Validation: valid={val_d['valid']}")
    assert val_d['valid'] is False

    inc_res_d = json.loads(tools_mod.record_incident(json.dumps({
        "partner_id": "partner-acme",
        "order_id": "ORD-2004",
        "raw_payload": payload_d,
        "validation_errors": val_d['errors'],
        "incident_type": "schema_drift_and_policy"
    })))
    inc_id_d = inc_res_d.get("incident_id")

    rules_d = json.loads(tools_mod.lookup_repair_rules("partner-acme"))
    plan_d = json.loads(tools_mod.propose_repair(json.dumps(payload_d), json.dumps(val_d['errors']), json.dumps(rules_d)))
    sandbox_d = json.loads(tools_mod.apply_repair_in_sandbox(json.dumps(payload_d), json.dumps(plan_d)))
    print(f"2. Sandbox Repair Result: success={sandbox_d['success']}")
    assert sandbox_d['success'] is True

    biz_d = json.loads(tools_mod.validate_business_rules_tool(json.dumps(sandbox_d['repaired_payload'])))
    print(f"3. Business Rules Check: safe={biz_d['safe']}, errors={biz_d['errors']}")
    assert biz_d['safe'] is False

    esc_d = json.loads(tools_mod.escalate_incident(
        json.dumps({"incident_id": inc_id_d, "order_id": "ORD-2004", "partner_id": "partner-acme"}),
        reason=biz_d['errors'][0]
    ))
    print(f"4. Escalation Status: escalated={esc_d['escalated']}, reason='{esc_d['reason']}'")
    print("5. Order Processed: NO (Blocked by business validation failure)")
    print("RESULT SCENARIO D: Safely Escalated without Processing [SUCCESS]")

    print("\n" + "=" * 80)
    print(" ALL 4 DEMO SCENARIOS PASSED PERFECTLY! ")
    print("=" * 80)


if __name__ == "__main__":
    db_url = os.environ.get("NEON_DB_URL", ":memory:")
    try:
        if db_url != ":memory:":
            # Test connection
            conn = get_db_connection(db_url)
            conn.close()
    except Exception as e:
        print(f"[Note] Could not connect to NEON_DB_URL ({e}). Falling back to in-memory SQLite database for demo execution.")
        db_url = ":memory:"

    run_all_demo_scenarios(db_url)
