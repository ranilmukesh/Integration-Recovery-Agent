import datetime
import json
import logging

from agno.tools import tool

from app.repair import apply_repair_plan_in_sandbox
from app.repository import Repository
from app.validators import validate_business_rules, validate_canonical_order

default_repo = Repository()

DEMO_SCENARIOS = {
    "healthy_order": {
        "description": "A valid partner order that should process immediately.",
        "payload": {
            "partner_id": "partner-acme",
            "order_id": "ORD-2001",
            "customer_id": "C-1001",
            "amount": 499.0,
            "currency": "INR",
            "payment_status": "PAID",
        },
    },
    "first_schema_drift": {
        "description": "First occurrence of partner schema drift.",
        "payload": {
            "partner_id": "partner-acme",
            "order_id": "ORD-2002",
            "client_id": "C-1002",
            "total": "1299.00",
            "currency": "INR",
            "payment_status": "paid",
        },
    },
    "repeated_schema_drift": {
        "description": "The same partner sends the same known schema drift again.",
        "payload": {
            "partner_id": "partner-acme",
            "order_id": "ORD-2003",
            "client_id": "C-1003",
            "total": "749.00",
            "currency": "INR",
            "payment_status": "paid",
        },
    },
    "unsafe_order": {
        "description": "The payload can be normalized, but the amount violates business policy.",
        "payload": {
            "partner_id": "partner-acme",
            "order_id": "ORD-2004",
            "client_id": "C-1004",
            "total": "-500.00",
            "currency": "INR",
            "payment_status": "paid",
        },
    },
}


@tool
def load_demo_scenario(scenario_name: str) -> str:
    """
    Load a controlled demonstration event.

    Valid scenarios:
    healthy_order,
    first_schema_drift,
    repeated_schema_drift,
    unsafe_order.

    This tool returns a test fixture only. It does not process an order
    or modify production state.
    """
    scenario = DEMO_SCENARIOS.get(scenario_name)

    if scenario is None:
        return json.dumps({
            "success": False,
            "error": "Unknown demo scenario",
            "available_scenarios": list(DEMO_SCENARIOS),
        })

    return json.dumps({
        "success": True,
        "scenario": scenario_name,
        "description": scenario["description"],
        "payload": scenario["payload"],
        "demo_only": True,
    })


def validate_order_payload(payload: dict) -> str:
    """Validate a partner order payload against the canonical schema.
    Returns structured JSON with 'valid' boolean and 'errors' array.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        report = validate_canonical_order(payload)
        return json.dumps({"valid": report.valid, "errors": report.errors})
    except Exception as e:
        return json.dumps({"valid": False, "errors": [{"type": "parse_error", "message": str(e)}]})


def lookup_repair_rules(partner_id: str, validation_errors: list = None) -> str:
    """Lookup existing approved schema repair rules in Neon/Postgres for a partner."""
    try:
        rules = default_repo.lookup_repair_rules(partner_id=partner_id, status="approved")
        return json.dumps({"rules": rules, "count": len(rules)})
    except Exception as e:
        return json.dumps({"rules": [], "count": 0, "error": str(e)})


def propose_repair(payload: dict, validation_errors: list = None, known_rules: dict = None) -> str:
    """Propose a repair plan using known rules or safe heuristics (rename, to_float, uppercase).
    Returns repair plan JSON.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(known_rules, str):
            known_rules = json.loads(known_rules)

        partner_id = payload.get("partner_id", "unknown-partner") if isinstance(payload, dict) else "unknown-partner"
        known_rules_list = known_rules.get("rules", []) if isinstance(known_rules, dict) else []

        rules_to_apply = []

        # If known rules exist, reuse them
        if known_rules_list:
            for r in known_rules_list:
                rules_to_apply.append({
                    "source_field": r.get("source_field"),
                    "target_field": r.get("target_field"),
                    "operation": r.get("operation") or r.get("transformation")
                })
        else:
            # Discover repair rules dynamically from payload fields
            if isinstance(payload, dict):
                if "client_id" in payload and "customer_id" not in payload:
                    rules_to_apply.append({"source_field": "client_id", "target_field": "customer_id", "operation": "rename"})
                
                if "total" in payload and "amount" not in payload:
                    rules_to_apply.append({"source_field": "total", "target_field": "amount", "operation": "to_float"})
                elif "amount" in payload and isinstance(payload["amount"], str):
                    rules_to_apply.append({"source_field": "amount", "target_field": "amount", "operation": "to_float"})
                
                if (
                    "payment_status" in payload
                    and isinstance(payload["payment_status"], str)
                    and payload["payment_status"].upper() in {"PAID", "PENDING", "FAILED"}
                    and payload["payment_status"] != payload["payment_status"].upper()
                ):
                    rules_to_apply.append({"source_field": "payment_status", "target_field": "payment_status", "operation": "uppercase"})

        plan = {
            "partner_id": partner_id,
            "rules": rules_to_apply
        }
        return json.dumps(plan)
    except Exception as e:
        return json.dumps({"partner_id": "unknown", "rules": [], "error": str(e)})


def apply_repair_in_sandbox(payload: dict, repair_plan: dict) -> str:
    """Apply a repair plan to payload copy in memory (sandbox).
    Does NOT touch production data. Returns sandbox result JSON.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(repair_plan, str):
            repair_plan = json.loads(repair_plan)
        res = apply_repair_plan_in_sandbox(payload, repair_plan)
        return json.dumps({
            "success": res.success,
            "repaired_payload": res.repaired_payload,
            "applied_rules": res.applied_rules,
            "error": res.error
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def validate_business_rules_tool(payload: dict) -> str:
    """Validate business policies: amount > 0, currency valid, payment_status valid.
    Returns business safety result JSON.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        res = validate_business_rules(payload)
        return json.dumps({"safe": res.safe, "errors": res.errors})
    except Exception as e:
        return json.dumps({"safe": False, "errors": [str(e)]})


def process_order(payload: dict, idempotency_key: str) -> str:
    """Process order downstream using idempotency key. Prevents duplicate side-effects.
    Returns processing result JSON.
    """
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        order_id = payload.get("order_id", "UNKNOWN_ORDER") if isinstance(payload, dict) else "UNKNOWN_ORDER"
        
        result_body = {
            "status": "processed",
            "order_id": order_id,
            "partner_id": payload.get("partner_id") if isinstance(payload, dict) else None,
            "amount": payload.get("amount") if isinstance(payload, dict) else None,
            "currency": payload.get("currency") if isinstance(payload, dict) else None,
            "idempotency_key": idempotency_key,
            "processed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        final_res, was_new = default_repo.process_order_idempotent(
            idempotency_key=idempotency_key,
            order_id=order_id,
            payload=payload,
            result=result_body
        )
        return json.dumps({
            "status": "processed",
            "was_new": was_new,
            "result": final_res
        })
    except Exception as e:
        return json.dumps({"status": "failed", "error": str(e)})


def save_approved_repair_rule(rule_data: dict) -> str:
    """Save an approved schema repair rule to Neon for future automatic reuse.
    Expects rule JSON object, list of rules, or repair plan dictionary.
    """
    try:
        if isinstance(rule_data, str):
            rule_data = json.loads(rule_data)
        if isinstance(rule_data, dict) and "rules" in rule_data:
            partner_id = rule_data.get("partner_id", "partner-acme")
            rules_list = rule_data["rules"]
        elif isinstance(rule_data, list):
            partner_id = "partner-acme"
            rules_list = rule_data
        else:
            partner_id = rule_data.get("partner_id", "partner-acme") if isinstance(rule_data, dict) else "partner-acme"
            rules_list = [rule_data]

        saved = []
        for item in rules_list:
            if not isinstance(item, dict):
                continue
            p_id = item.get("partner_id", partner_id)
            src = item.get("source_field")
            tgt = item.get("target_field")
            op = item.get("operation") or item.get("transformation")
            if src and tgt and op:
                saved_rule = default_repo.save_approved_repair_rule(
                    partner_id=p_id,
                    source_field=src,
                    target_field=tgt,
                    operation=op
                )
                saved.append(saved_rule)

        return json.dumps({"saved": True, "count": len(saved), "rules": saved})
    except Exception as e:
        return json.dumps({"saved": False, "count": 0, "error": str(e)})


logger = logging.getLogger("app.tools")

VALID_INCIDENT_STATUSES = {"detected", "repaired", "processed", "escalated", "failed"}
INCIDENT_STATUS_MAP = {
    "RECEIVED": "detected",
    "VALIDATING": "detected",
    "DIAGNOSING": "detected",
    "REPAIRING": "detected",
    "REPAIRING_IN_SANDBOX": "detected",
    "VERIFYING": "detected",
    "PROCESSING": "processed",
    "COMPLETE": "processed",
    "ESCALATED": "escalated",
}

VALID_ATTEMPT_OUTCOMES = {"sandbox_failed", "business_failed", "processed", "escalated"}
ATTEMPT_OUTCOME_MAP = {
    "SUCCESS": "processed",
    "PASSED": "processed",
    "SANDBOX_PASSED": "processed",
    "SANDBOX_SUCCESS": "processed",
    "BUSINESS_PASSED": "processed",
    "FAILED": "sandbox_failed",
    "ERROR": "sandbox_failed",
}


def sanitize_incident_status(raw_status: str | None) -> tuple[str, str | None]:
    if not raw_status:
        return "detected", None
    s = str(raw_status).strip()
    if s in VALID_INCIDENT_STATUSES:
        return s, None
    normalized = INCIDENT_STATUS_MAP.get(s.upper(), "detected")
    logger.warning("Normalized incident status from %r to %r for DB constraint safety.", raw_status, normalized)
    return normalized, s


def sanitize_attempt_outcome(raw_outcome: str | None) -> tuple[str, str | None]:
    if not raw_outcome:
        return "processed", None
    o = str(raw_outcome).strip()
    if o in VALID_ATTEMPT_OUTCOMES:
        return o, None
    normalized = ATTEMPT_OUTCOME_MAP.get(o.upper(), "processed")
    logger.warning("Normalized attempt outcome from %r to %r for DB constraint safety.", raw_outcome, normalized)
    return normalized, o


def record_incident(incident_data: dict) -> str:
    """Record an integration incident in Neon."""
    try:
        if isinstance(incident_data, str):
            incident_data = json.loads(incident_data)
        raw_status = incident_data.get("status") if isinstance(incident_data, dict) else None
        status, normalized_from = sanitize_incident_status(raw_status)

        incident_id = default_repo.record_incident(
            partner_id=incident_data.get("partner_id", "unknown") if isinstance(incident_data, dict) else "unknown",
            order_id=incident_data.get("order_id") if isinstance(incident_data, dict) else None,
            raw_payload=incident_data.get("raw_payload", incident_data) if isinstance(incident_data, dict) else incident_data,
            validation_errors=incident_data.get("validation_errors", []) if isinstance(incident_data, dict) else [],
            incident_type=incident_data.get("incident_type", "schema_drift") if isinstance(incident_data, dict) else "schema_drift",
            status=status
        )
        res = {"success": True, "incident_id": incident_id, "stored_status": status}
        if normalized_from:
            res["normalized_from"] = normalized_from
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def record_repair_attempt(attempt_data: dict) -> str:
    """Record a repair attempt in Neon linked to an incident."""
    try:
        if isinstance(attempt_data, str):
            attempt_data = json.loads(attempt_data)
        incident_id = attempt_data.get("incident_id") if isinstance(attempt_data, dict) else None

        if not incident_id:
            incident_id = default_repo.record_incident(
                partner_id=attempt_data.get("partner_id", "unknown") if isinstance(attempt_data, dict) else "unknown",
                order_id=attempt_data.get("order_id") if isinstance(attempt_data, dict) else None,
                raw_payload=attempt_data.get("before_payload", attempt_data) if isinstance(attempt_data, dict) else attempt_data,
                validation_errors=[],
                incident_type="schema_drift",
                status="repaired"
            )

        raw_outcome = attempt_data.get("outcome") if isinstance(attempt_data, dict) else None
        outcome, normalized_from = sanitize_attempt_outcome(raw_outcome)

        attempt_id = default_repo.record_repair_attempt(
            incident_id=incident_id,
            repair_plan=attempt_data.get("repair_plan", {}) if isinstance(attempt_data, dict) else {},
            before_payload=attempt_data.get("before_payload", {}) if isinstance(attempt_data, dict) else {},
            after_payload=attempt_data.get("after_payload") if isinstance(attempt_data, dict) else None,
            validation_result=attempt_data.get("validation_result") if isinstance(attempt_data, dict) else None,
            business_result=attempt_data.get("business_result") if isinstance(attempt_data, dict) else None,
            processing_result=attempt_data.get("processing_result") if isinstance(attempt_data, dict) else None,
            outcome=outcome
        )
        res = {"success": True, "attempt_id": attempt_id, "incident_id": incident_id, "stored_outcome": outcome}
        if normalized_from:
            res["normalized_from"] = normalized_from
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def escalate_incident(incident_data: dict, reason: str) -> str:
    """Flag an incident as escalated for human review when automatic repair is unsafe or ambiguous."""
    try:
        if isinstance(incident_data, str):
            incident_data = json.loads(incident_data)
        incident_id = (incident_data.get("incident_id") or incident_data.get("id")) if isinstance(incident_data, dict) else None
        
        escalation_id = default_repo.escalate_incident(
            incident_id=incident_id,
            reason=reason,
            evidence=incident_data if isinstance(incident_data, dict) else {}
        )
        return json.dumps({
            "escalated": True,
            "escalation_id": escalation_id,
            "incident_id": incident_id,
            "reason": reason,
            "action": "human review required"
        })
    except Exception as e:
        return json.dumps({"escalated": False, "error": str(e)})


def get_incident_audit(incident_id: str) -> str:
    """Retrieve full audit log for an incident including repair attempts and escalations."""
    try:
        audit = default_repo.get_incident_audit(incident_id)
        return json.dumps(audit, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})
