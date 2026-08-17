from app.validators import make_idempotency_key, validate_business_rules, validate_canonical_order


def test_healthy_canonical_order_passes():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1001",
        "customer_id": "C-100",
        "amount": 499.0,
        "currency": "INR",
        "payment_status": "PAID"
    }
    report = validate_canonical_order(payload)
    assert report.valid is True
    assert len(report.errors) == 0

    biz_res = validate_business_rules(payload)
    assert biz_res.safe is True


def test_missing_fields_fails():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1001"
    }
    report = validate_canonical_order(payload)
    assert report.valid is False
    err_types = [e["type"] for e in report.errors]
    assert "missing_fields" in err_types


def test_unexpected_fields_reported():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1007",
        "client_id": "C-8831",
        "total": "1299.00",
        "currency": "INR",
        "payment_status": "paid"
    }
    report = validate_canonical_order(payload)
    assert report.valid is False
    unexpected_err = next(e for e in report.errors if e["type"] == "unexpected_fields")
    assert "client_id" in unexpected_err["fields"]
    assert "total" in unexpected_err["fields"]


def test_numeric_strings_accepted_before_repair():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1001",
        "customer_id": "C-100",
        "amount": "499.00",
        "currency": "INR",
        "payment_status": "PAID"
    }
    report = validate_canonical_order(payload)
    assert report.valid is True

def test_invalid_strings_rejected_before_repair():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1001",
        "customer_id": "C-100",
        "amount": "invalid_string",
        "currency": "INR",
        "payment_status": "PAID"
    }
    report = validate_canonical_order(payload)
    assert report.valid is True

def test_invalid_strings_rejected_before_repair():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1001",
        "customer_id": "C-100",
        "amount": "invalid_string",
        "currency": "INR",
        "payment_status": "PAID"
    }
    report = validate_canonical_order(payload)
    assert report.valid is False
    type_err = next(e for e in report.errors if e["type"] == "invalid_type")
    assert type_err["field"] == "amount"


def test_lowercase_status_rejected_before_repair():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1001",
        "customer_id": "C-100",
        "amount": 499.0,
        "currency": "INR",
        "payment_status": "paid"
    }
    report = validate_canonical_order(payload)
    assert report.valid is False
    val_err = next(e for e in report.errors if e["type"] == "invalid_value")
    assert val_err["field"] == "payment_status"


def test_negative_and_zero_amount_fails_business_validation():
    payload_neg = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1009",
        "customer_id": "C-3321",
        "amount": -500.0,
        "currency": "INR",
        "payment_status": "PAID"
    }
    biz_neg = validate_business_rules(payload_neg)
    assert biz_neg.safe is False
    assert any("amount must be greater than zero" in err for err in biz_neg.errors)

    payload_zero = dict(payload_neg, amount=0.0)
    biz_zero = validate_business_rules(payload_zero)
    assert biz_zero.safe is False


def test_unsupported_currency_fails():
    payload = {
        "partner_id": "partner-acme",
        "order_id": "ORD-1001",
        "customer_id": "C-100",
        "amount": 100.0,
        "currency": "XYZ",
        "payment_status": "PAID"
    }
    biz_res = validate_business_rules(payload)
    assert biz_res.safe is False
    assert any("currency must be one of" in err for err in biz_res.errors)


def test_idempotency_key_generator():
    key = make_idempotency_key("partner-acme", "ORD-1001")
    assert key == "KEY:partner-acme:ORD-1001"
