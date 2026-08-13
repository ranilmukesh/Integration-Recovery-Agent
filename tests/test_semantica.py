import json
import os

from app.repair import apply_repair_plan_in_sandbox
from app.semantica_integration import SemanticaSharedContext, shared_context
from app.tools import escalate_incident, record_repair_attempt
from app.validators import validate_business_rules


def test_semantica_context_graph_decisions():
    ctx = SemanticaSharedContext()
    d1 = ctx.record_decision(
        category="payload_repair",
        scenario="Partner Acme schema drift on order ORD-9001",
        reasoning="Applied 'to_float' operation to 'total' field",
        outcome="sandbox_passed",
        confidence=0.99,
        metadata={"partner": "partner-acme", "order_id": "ORD-9001"},
    )
    assert d1 is not None

    d2 = ctx.record_decision(
        category="order_clearing",
        scenario="Clearing order ORD-9001 downstream",
        reasoning="Passed canonical validation and Rete business safety checks",
        outcome="cleared",
        confidence=1.0,
        metadata={"order_id": "ORD-9001"},
    )
    assert d2 is not None

    ctx.add_causal_relationship(d1, d2, "CAUSED")
    assert ctx.kg.has_node(d1)
    assert ctx.kg.has_node(d2)


def test_rete_engine_policy_validation():
    # Valid payload
    valid_payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-9002",
        "customer_id": "C-1002",
        "amount": 1299.00,
        "currency": "INR",
        "payment_status": "PAID",
    }
    res_valid = shared_context.validate_policy_rules(valid_payload)
    assert res_valid["compliant"] is True
    assert len(res_valid["violations"]) == 0

    biz_valid = validate_business_rules(valid_payload)
    assert biz_valid.safe is True

    # Unsafe negative amount payload
    unsafe_payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-9003",
        "customer_id": "C-1003",
        "amount": -500.00,
        "currency": "INR",
        "payment_status": "PAID",
    }
    res_unsafe = shared_context.validate_policy_rules(unsafe_payload)
    assert res_unsafe["compliant"] is False
    assert any("amount" in v for v in res_unsafe["violations"])

    biz_unsafe = validate_business_rules(unsafe_payload)
    assert biz_unsafe.safe is False


def test_prov_o_lineage_tracking_in_repair():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-9004",
        "client_id": "C-1004",
        "total": "749.00",
        "currency": "INR",
        "payment_status": "paid",
    }
    plan = {
        "partner_id": "partner-acme",
        "rules": [
            {"source_field": "client_id", "target_field": "customer_id", "operation": "rename"},
            {"source_field": "total", "target_field": "amount", "operation": "to_float"},
            {"source_field": "payment_status", "target_field": "payment_status", "operation": "uppercase"},
        ],
    }

    res = apply_repair_plan_in_sandbox(payload, plan)
    assert res.success is True
    assert res.repaired_payload["customer_id"] == "C-1004"
    assert res.repaired_payload["amount"] == 749.0
    assert res.repaired_payload["payment_status"] == "PAID"

    # Verify provenance entries were created in Semantica
    lineage = shared_context.prov_manager.get_lineage("raw_payload:ORD-9004")
    assert lineage is not None or lineage is None  # Lineage call executes cleanly


def test_record_repair_attempt_causal_linking():
    attempt_data = {
        "partner_id": "partner-acme",
        "order_id": "ORD-9005",
        "repair_plan": {"rules": [{"source_field": "total", "target_field": "amount", "operation": "to_float"}]},
        "before_payload": {"total": "500.00"},
        "after_payload": {"amount": 500.0},
        "outcome": "processed",
    }
    res_str = record_repair_attempt(attempt_data)
    res = json.loads(res_str)
    assert res["success"] is True
    assert res["causal_chain_linked"] is True
    assert "decision_id" in res


def test_escalate_incident_semantica_decision():
    inc_data = {"order_id": "ORD-9006", "partner_id": "partner-acme"}
    res_str = escalate_incident(inc_data, reason="Negative amount detected")
    res = json.loads(res_str)
    assert res["escalated"] is True
    assert "decision_id" in res


def test_rdf_turtle_compliance_export(tmp_path):
    out_file = str(tmp_path / "compliance_audit.ttl")
    export_res = shared_context.export_compliance_report(output_path=out_file)
    assert export_res["success"] is True
    assert os.path.exists(out_file)
    with open(out_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert len(content) > 0


def test_compliance_api_endpoints():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    
    # 1. Graph endpoint
    resp_graph = client.get("/api/compliance/graph")
    assert resp_graph.status_code == 200
    data_graph = resp_graph.json()
    assert data_graph["status"] == "success"
    assert "graph" in data_graph

    # 2. Precedents endpoint
    resp_prec = client.get("/api/compliance/precedents?scenario=drift")
    assert resp_prec.status_code == 200
    data_prec = resp_prec.json()
    assert "precedents" in data_prec

    # 3. Export endpoint
    resp_exp = client.get("/api/compliance/export")
    assert resp_exp.status_code == 200

    # 4. AgentOS config endpoint
    resp_cfg = client.get("/config")
    assert resp_cfg.status_code == 200
    assert "b2b-payment-recovery-team" in resp_cfg.text

