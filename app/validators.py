from typing import Any

from app.schemas import BusinessResult, ValidationReport
from app.semantica_integration import shared_context

CANONICAL_FIELDS = {"partner_id", "order_id", "customer_id", "amount", "currency", "payment_status"}
ALLOWED_CURRENCIES = {"INR", "USD", "EUR", "GBP"}
ALLOWED_PAYMENT_STATUSES = {"PAID", "PENDING", "FAILED"}


def validate_canonical_order(payload: dict[str, Any]) -> ValidationReport:
    """Validate incoming payload strictly against canonical schema.
    Rejects partner aliases (e.g. client_id, total) and wrong types/cases.
    """
    errors: list[dict[str, Any]] = []

    if not isinstance(payload, dict):
        return ValidationReport(valid=False, errors=[{"type": "invalid_payload", "message": "Payload must be a JSON object"}])

    missing = sorted(CANONICAL_FIELDS - payload.keys())
    if missing:
        errors.append({"type": "missing_fields", "fields": missing})

    unexpected = sorted(set(payload.keys()) - CANONICAL_FIELDS)
    if unexpected:
        errors.append({"type": "unexpected_fields", "fields": unexpected})

    if "amount" in payload:
        val = payload["amount"]
        try:
            if isinstance(val, bool):
                raise TypeError("boolean")
            float(val)
        except (ValueError, TypeError):
            errors.append({
                "type": "invalid_type",
                "field": "amount",
                "expected": "number",
                "got": type(val).__name__
            })

    if "currency" in payload:
        cur = payload["currency"]
        if cur not in ALLOWED_CURRENCIES:
            errors.append({
                "type": "invalid_value",
                "field": "currency",
                "allowed": sorted(ALLOWED_CURRENCIES),
                "got": str(cur)
            })

    if "payment_status" in payload:
        status = payload["payment_status"]
        if status not in ALLOWED_PAYMENT_STATUSES:
            errors.append({
                "type": "invalid_value",
                "field": "payment_status",
                "allowed": sorted(ALLOWED_PAYMENT_STATUSES),
                "got": str(status)
            })

    return ValidationReport(valid=len(errors) == 0, errors=errors)


def validate_business_rules(payload: dict[str, Any]) -> BusinessResult:
    """Validate business safety constraints on canonical payload using Semantica ReteEngine."""
    errors: list[str] = []

    # 1. Canonical Business validation for exact contract compatibility
    if "amount" not in payload:
        errors.append("amount field missing")
    else:
        try:
            amt = float(payload["amount"])
            if amt <= 0:
                errors.append("amount must be greater than zero")
        except (ValueError, TypeError):
            errors.append("amount is not a valid number")

    currency = payload.get("currency")
    if currency not in ALLOWED_CURRENCIES:
        errors.append(f"currency must be one of {sorted(ALLOWED_CURRENCIES)}")

    payment_status = payload.get("payment_status")
    if payment_status not in ALLOWED_PAYMENT_STATUSES:
        errors.append(f"payment_status must be one of {sorted(ALLOWED_PAYMENT_STATUSES)}")

    # 2. Rete Engine Policy Rule evaluation for governance traceability
    rete_result = shared_context.validate_policy_rules(payload)
    if not rete_result.get("compliant", False):
        for v in rete_result.get("violations", []):
            if v not in errors:
                errors.append(v)

    return BusinessResult(safe=len(errors) == 0, errors=errors)



def make_idempotency_key(partner_id: str, order_id: str) -> str:
    """Generate deterministic idempotency key for partner order."""
    return f"KEY:{partner_id}:{order_id}"
