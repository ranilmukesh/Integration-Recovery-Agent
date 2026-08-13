import json

import pytest

import app.tools as tools_mod
from app.db import get_db_connection, run_migrations


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    db_url = ":memory:"
    run_migrations(db_url)
    conn = get_db_connection(db_url)
    cur = conn.cursor()
    cur.executescript("DELETE FROM repair_rules; DELETE FROM integration_incidents; DELETE FROM repair_attempts; DELETE FROM processed_orders; DELETE FROM escalations;")
    conn.commit()
    cur.close()
    conn.close()
    test_repo = tools_mod.Repository(db_url=db_url)
    monkeypatch.setattr(tools_mod, "default_repo", test_repo)


def test_tool_load_demo_scenario():
    res_str = tools_mod.load_demo_scenario.entrypoint("first_schema_drift")
    res = json.loads(res_str)
    assert res["success"] is True
    assert res["scenario"] == "first_schema_drift"
    assert res["payload"]["order_id"] == "ORD-2002"

    res_invalid_str = tools_mod.load_demo_scenario.entrypoint("invalid_scenario_name")
    res_invalid = json.loads(res_invalid_str)
    assert res_invalid["success"] is False
    assert "Unknown demo scenario" in res_invalid["error"]


def test_tool_validate_order_payload():
    valid_payload = json.dumps({
        "partner_id": "partner-acme",
        "order_id": "ORD-1001",
        "customer_id": "C-100",
        "amount": 499.0,
        "currency": "INR",
        "payment_status": "PAID"
    })
    res_str = tools_mod.validate_order_payload(valid_payload)
    res = json.loads(res_str)
    assert res["valid"] is True
    assert len(res["errors"]) == 0


def test_tool_repair_flow_first_drift():
    drifted_payload = json.dumps({
        "partner_id": "partner-acme",
        "order_id": "ORD-1007",
        "client_id": "C-8831",
        "total": "1299.00",
        "currency": "INR",
        "payment_status": "paid"
    })

    val_res = json.loads(tools_mod.validate_order_payload(drifted_payload))
    assert val_res["valid"] is False

    rules_res = json.loads(tools_mod.lookup_repair_rules("partner-acme"))
    assert rules_res["count"] == 0

    plan_res = json.loads(tools_mod.propose_repair(drifted_payload, json.dumps(val_res["errors"]), json.dumps(rules_res)))
    assert len(plan_res["rules"]) == 3

    sandbox_res = json.loads(tools_mod.apply_repair_in_sandbox(drifted_payload, json.dumps(plan_res)))
    assert sandbox_res["success"] is True

    revalidated = json.loads(tools_mod.validate_order_payload(json.dumps(sandbox_res["repaired_payload"])))
    assert revalidated["valid"] is True

    biz_res = json.loads(tools_mod.validate_business_rules_tool(json.dumps(sandbox_res["repaired_payload"])))
    assert biz_res["safe"] is True

    proc_res = json.loads(tools_mod.process_order(json.dumps(sandbox_res["repaired_payload"]), "KEY:partner-acme:ORD-1007"))
    assert proc_res["status"] == "processed"

    save_res = json.loads(tools_mod.save_approved_repair_rule(json.dumps(sandbox_res["applied_rules"])))
    assert save_res["saved"] is True
    assert save_res["count"] == 3


def test_tool_escalation_on_negative_amount():
    negative_payload = json.dumps({
        "partner_id": "partner-acme",
        "order_id": "ORD-1009",
        "client_id": "C-3321",
        "total": "-500.00",
        "currency": "INR",
        "payment_status": "paid"
    })

    plan_res = json.loads(tools_mod.propose_repair(negative_payload, "[]", "{}"))
    sandbox_res = json.loads(tools_mod.apply_repair_in_sandbox(negative_payload, json.dumps(plan_res)))
    assert sandbox_res["success"] is True

    biz_res = json.loads(tools_mod.validate_business_rules_tool(json.dumps(sandbox_res["repaired_payload"])))
    assert biz_res["safe"] is False
    assert "amount must be greater than zero" in biz_res["errors"][0]

    esc_res = json.loads(tools_mod.escalate_incident(
        json.dumps({"order_id": "ORD-1009", "partner_id": "partner-acme"}),
        reason=biz_res["errors"][0]
    ))
    assert esc_res["escalated"] is True
    assert esc_res["action"] == "human review required"


def test_status_sanitization_and_logging():
    # Test passing UI stage 'DIAGNOSING' to record_incident
    inc_res = json.loads(tools_mod.record_incident(json.dumps({
        "partner_id": "partner-acme",
        "order_id": "ORD-TEST",
        "status": "DIAGNOSING"
    })))
    assert inc_res["success"] is True
    assert inc_res["stored_status"] == "detected"
    assert inc_res["normalized_from"] == "DIAGNOSING"

    # Test passing outcome 'passed' to record_repair_attempt
    attempt_res = json.loads(tools_mod.record_repair_attempt(json.dumps({
        "partner_id": "partner-acme",
        "order_id": "ORD-TEST",
        "outcome": "passed"
    })))
    assert attempt_res["success"] is True
    assert attempt_res["stored_outcome"] == "processed"
    assert attempt_res["normalized_from"] == "passed"


def test_tool_get_incident_audit():
    inc_res = json.loads(tools_mod.record_incident(json.dumps({
        "partner_id": "partner-acme",
        "order_id": "ORD-AUDIT",
        "status": "detected"
    })))
    inc_id = inc_res["incident_id"]

    audit_str = tools_mod.get_incident_audit(inc_id)
    audit = json.loads(audit_str)

    assert "incident" in audit
    assert audit["incident"]["id"] == inc_id
    assert "attempts" in audit
    assert "escalations" in audit


def test_macro_run_recovery_pipeline_success():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-MACRO-100",
        "client_id": "C-999",
        "total": "250.00",
        "currency": "INR",
        "payment_status": "paid"
    }

    pipeline_res_str = tools_mod.run_recovery_pipeline.entrypoint(payload)
    pipeline_res = json.loads(pipeline_res_str)

    assert pipeline_res["ready"] is True
    assert "repaired_payload" in pipeline_res
    assert pipeline_res["repaired_payload"]["customer_id"] == "C-999"
    assert pipeline_res["repaired_payload"]["amount"] == 250.0

    proc_res_str = tools_mod.process_and_record.entrypoint(
        repaired_payload=pipeline_res["repaired_payload"],
        incident_id=pipeline_res.get("incident_id"),
        repair_plan=pipeline_res.get("repair_plan"),
        save_new_rules=pipeline_res.get("save_new_rules", False)
    )
    proc_res = json.loads(proc_res_str)
    assert proc_res["status"] == "SUCCESS"
    assert proc_res["was_new"] is True


def test_macro_run_recovery_pipeline_unsafe():
    unsafe_payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-MACRO-UNSAFE",
        "client_id": "C-100",
        "total": "-500.00",
        "currency": "INR",
        "payment_status": "paid"
    }

    pipeline_res_str = tools_mod.run_recovery_pipeline.entrypoint(unsafe_payload)
    pipeline_res = json.loads(pipeline_res_str)

    assert pipeline_res["ready"] is False
    assert "reason" in pipeline_res

    esc_res_str = tools_mod.escalate_and_audit.entrypoint(
        incident_data=pipeline_res,
        reason=pipeline_res["reason"]
    )
    esc_res = json.loads(esc_res_str)
    assert esc_res["escalated"] is True
    assert "escalation_id" in esc_res

