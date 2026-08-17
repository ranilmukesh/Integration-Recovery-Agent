import pytest

from app.db import get_db_connection, run_migrations
from app.repository import Repository


@pytest.fixture
def test_repo():
    db_url = ":memory:"
    run_migrations(db_url)
    conn = get_db_connection(db_url)
    cur = conn.cursor()
    cur.executescript("DELETE FROM repair_rules; DELETE FROM integration_incidents; DELETE FROM repair_attempts; DELETE FROM processed_orders; DELETE FROM escalations;")
    conn.commit()
    cur.close()
    conn.close()
    return Repository(db_url=db_url)


def test_repository_save_and_lookup_repair_rules(test_repo):
    test_repo.save_approved_repair_rule("partner-acme", "client_id", "customer_id", "rename")
    rules = test_repo.lookup_repair_rules("partner-acme")

    assert len(rules) == 1
    assert rules[0]["source_field"] == "client_id"
    assert rules[0]["target_field"] == "customer_id"
    assert rules[0]["operation"] == "rename"
    assert rules[0]["hit_count"] == 0

    test_repo.increment_rule_hit_count("partner-acme", "client_id", "customer_id", "rename")
    updated_rules = test_repo.lookup_repair_rules("partner-acme")
    assert updated_rules[0]["hit_count"] == 1


def test_repository_idempotency_prevents_duplicate_processing(test_repo):
    key = "KEY:partner-acme:ORD-1001"
    payload = {"order_id": "ORD-1001", "amount": 499.0}
    result_1 = {"status": "processed", "order_id": "ORD-1001", "idempotency_key": key}

    res_1, was_new_1 = test_repo.process_order_idempotent(key, "ORD-1001", payload, result_1)
    assert was_new_1 is True
    assert res_1["status"] == "processed"

    # Second processing attempt with exact same key
    result_2 = {"status": "processed", "order_id": "ORD-1001", "idempotency_key": key, "extra": "new_call"}
    res_2, was_new_2 = test_repo.process_order_idempotent(key, "ORD-1001", payload, result_2)

    assert was_new_2 is False
    assert res_2 == result_1  # Original result returned


def test_repository_incident_recording_and_escalation(test_repo):
    incident_id = test_repo.record_incident(
        partner_id="partner-acme",
        order_id="ORD-1009",
        raw_payload={"amount": -500.0, "customer_id": "C-123", "client_id": "CL-456"},
        validation_errors=[{"type": "negative_amount"}],
        incident_type="business_policy_violation"
    )
    assert incident_id is not None

    esc_id = test_repo.escalate_incident(
        incident_id=incident_id,
        reason="amount must be greater than zero",
        evidence={"amount": -500.0}
    )
    assert esc_id is not None

    audit = test_repo.get_incident_audit(incident_id)
    assert audit["incident"]["status"] == "escalated"
    assert len(audit["escalations"]) == 1
    assert audit["escalations"][0]["reason"] == "amount must be greater than zero"
    import hashlib
    raw = audit["incident"]["raw_payload"]
    assert raw["customer_id"] == hashlib.sha256("C-123".encode()).hexdigest()
    assert raw["client_id"] == hashlib.sha256("CL-456".encode()).hexdigest()
