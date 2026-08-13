from app.repair import apply_repair_plan_in_sandbox


def test_sandbox_repair_does_not_mutate_original_payload():
    original = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1007",
        "client_id": "C-8831",
        "total": "1299.00",
        "currency": "INR",
        "payment_status": "paid"
    }
    original_copy = dict(original)

    plan = {
        "partner_id": "partner-acme",
        "rules": [
            {"source_field": "client_id", "target_field": "customer_id", "operation": "rename"},
            {"source_field": "total", "target_field": "amount", "operation": "to_float"},
            {"source_field": "payment_status", "target_field": "payment_status", "operation": "uppercase"}
        ]
    }

    res = apply_repair_plan_in_sandbox(original, plan)

    assert res.success is True
    assert original == original_copy  # Immutability check
    assert res.repaired_payload["customer_id"] == "C-8831"
    assert res.repaired_payload["amount"] == 1299.00
    assert res.repaired_payload["payment_status"] == "PAID"
    assert "client_id" not in res.repaired_payload
    assert "total" not in res.repaired_payload


def test_to_float_converts_valid_numeric_strings():
    payload = {"total": "749.50"}
    plan = {"rules": [{"source_field": "total", "target_field": "amount", "operation": "to_float"}]}
    res = apply_repair_plan_in_sandbox(payload, plan)
    assert res.success is True
    assert res.repaired_payload["amount"] == 749.50


def test_to_float_rejects_non_numeric_strings():
    payload = {"total": "invalid_number"}
    plan = {"rules": [{"source_field": "total", "target_field": "amount", "operation": "to_float"}]}
    res = apply_repair_plan_in_sandbox(payload, plan)
    assert res.success is False
    assert "Conversion failure" in res.error


def test_unsupported_operation_rejected():
    payload = {"address": "123 Street"}
    plan = {"rules": [{"source_field": "address", "target_field": "customer_id", "operation": "magic_map"}]}
    res = apply_repair_plan_in_sandbox(payload, plan)
    assert res.success is False
    assert "Unsupported operation" in res.error
