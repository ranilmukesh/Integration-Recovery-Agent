import datetime
import json
import logging
import uuid

from agno.tools import tool

from app.repair import apply_repair_plan_in_sandbox
from app.repository import Repository
from app.semantica_integration import (
    shared_context,
)
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


@tool
def run_recovery_pipeline(payload: dict) -> str:
    """Validates, diagnoses, looks up rules, and tests repairs in a sandbox.
    Returns whether the payload is ready to process or needs escalation.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            pass

    partner_id = payload.get("partner_id", "unknown") if isinstance(payload, dict) else "unknown"
    order_id = payload.get("order_id") if isinstance(payload, dict) else None

    # Step 1: Validate Schema
    report = validate_canonical_order(payload)
    if report.valid:
        biz_check = validate_business_rules(payload)
        return json.dumps({
            "ready": biz_check.safe,
            "status": "VALIDATED",
            "payload": payload,
            "errors": biz_check.errors
        })

    # Step 2: Record Incident
    incident_id = default_repo.record_incident(
        partner_id=partner_id,
        order_id=order_id,
        raw_payload=payload,
        validation_errors=report.errors,
        incident_type="schema_drift"
    )

    # Step 3: Lookup Existing Approved Rules
    existing_rules = default_repo.lookup_repair_rules(partner_id=partner_id)

    # Step 4: Propose & Apply Repair Plan
    rules_to_apply = []
    if existing_rules:
        for r in existing_rules:
            rules_to_apply.append({
                "source_field": r.get("source_field"),
                "target_field": r.get("target_field"),
                "operation": r.get("operation") or r.get("transformation")
            })
    else:
        # Dynamic Heuristics
        if isinstance(payload, dict):
            if "client_id" in payload and "customer_id" not in payload:
                rules_to_apply.append({"source_field": "client_id", "target_field": "customer_id", "operation": "rename"})
            if "total" in payload and "amount" not in payload:
                rules_to_apply.append({"source_field": "total", "target_field": "amount", "operation": "to_float"})
            elif "amount" in payload and isinstance(payload["amount"], str):
                rules_to_apply.append({"source_field": "amount", "target_field": "amount", "operation": "to_float"})
            if payload.get("payment_status") and str(payload.get("payment_status")).lower() in {"paid", "pending", "failed"}:
                rules_to_apply.append({"source_field": "payment_status", "target_field": "payment_status", "operation": "uppercase"})

    repair_plan = {"partner_id": partner_id, "rules": rules_to_apply}
    sandbox_res = apply_repair_plan_in_sandbox(payload, repair_plan)

    if not sandbox_res.success or not sandbox_res.repaired_payload:
        return json.dumps({
            "ready": False,
            "incident_id": incident_id,
            "reason": f"Sandbox repair failed: {sandbox_res.error}"
        })

    # Step 5: Re-validate Schema & Business Rules on Repaired Payload
    revalidated = validate_canonical_order(sandbox_res.repaired_payload)
    biz_check = validate_business_rules(sandbox_res.repaired_payload)

    if revalidated.valid and biz_check.safe:
        return json.dumps({
            "ready": True,
            "incident_id": incident_id,
            "repaired_payload": sandbox_res.repaired_payload,
            "repair_plan": repair_plan,
            "save_new_rules": len(existing_rules) == 0
        })

    return json.dumps({
        "ready": False,
        "incident_id": incident_id,
        "reason": f"Repaired payload failed business rules: {biz_check.errors}"
    })


@tool
def process_and_record(repaired_payload: dict, incident_id: str = None, repair_plan: dict = None, save_new_rules: bool = False) -> str:
    """Processes order downstream, records repair attempt, and saves approved rules."""
    if isinstance(repaired_payload, str):
        try:
            repaired_payload = json.loads(repaired_payload)
        except Exception:
            pass
    if isinstance(repair_plan, str):
        try:
            repair_plan = json.loads(repair_plan)
        except Exception:
            pass

    order_id = repaired_payload.get("order_id", "UNKNOWN_ORDER") if isinstance(repaired_payload, dict) else "UNKNOWN_ORDER"
    partner_id = repaired_payload.get("partner_id", "unknown") if isinstance(repaired_payload, dict) else "unknown"

    # Process Order Idempotently
    idempotency_key = f"KEY:{partner_id}:{order_id}"
    result_body = {
        "status": "processed",
        "order_id": order_id,
        "partner_id": partner_id,
        "amount": repaired_payload.get("amount") if isinstance(repaired_payload, dict) else None,
        "currency": repaired_payload.get("currency") if isinstance(repaired_payload, dict) else None
    }
    final_res, was_new = default_repo.process_order_idempotent(
        idempotency_key=idempotency_key,
        order_id=order_id,
        payload=repaired_payload,
        result=result_body
    )

    # Validate UUID to prevent Postgres crashes
    is_valid_uuid = False
    if incident_id:
        try:
            uuid.UUID(str(incident_id))
            is_valid_uuid = True
        except ValueError:
            pass  # LLM passed a bad string like "ORD-2001"

    # Record Repair Attempt Safely
    if is_valid_uuid:
        try:
            default_repo.record_repair_attempt(
                incident_id=incident_id,
                repair_plan=repair_plan or {},
                before_payload=repaired_payload,
                after_payload=repaired_payload,
                outcome="processed"
            )
        except Exception:
            pass  # Ignore foreign key violations from fake LLM UUIDs

    # Save Rules to Neon if Newly Discovered
    if save_new_rules and repair_plan:
        for r in repair_plan.get("rules", []):
            default_repo.save_approved_repair_rule(
                partner_id=partner_id,
                source_field=r["source_field"],
                target_field=r["target_field"],
                operation=r["operation"]
            )

    return json.dumps({"status": "SUCCESS", "was_new": was_new, "result": final_res})


@tool
def escalate_and_audit(incident_data: dict, reason: str) -> str:
    """Escalates unsafe/failed incidents for human review and retrieves audit trail."""
    if isinstance(incident_data, str):
        try:
            incident_data = json.loads(incident_data)
        except Exception:
            pass
    incident_id = incident_data.get("incident_id") if isinstance(incident_data, dict) else None
    escalation_id = default_repo.escalate_incident(incident_id=incident_id, reason=reason, evidence=incident_data if isinstance(incident_data, dict) else {})
    audit_trail = default_repo.get_incident_audit(incident_id) if incident_id else {}
    
    return json.dumps({
        "escalated": True,
        "escalation_id": escalation_id,
        "reason": reason,
        "audit": audit_trail
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
    """Record a repair attempt in Neon linked to an incident and build Causal Decision Graph in Semantica."""
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

        # Semantica Decision Intelligence Graph Creation
        order_id = attempt_data.get("order_id", "UNKNOWN_ORDER") if isinstance(attempt_data, dict) else "UNKNOWN_ORDER"
        partner_id = attempt_data.get("partner_id", "unknown") if isinstance(attempt_data, dict) else "unknown"

        repair_decision_id = shared_context.record_decision(
            category="payment_payload_repair",
            scenario=f"Schema drift recovery for partner '{partner_id}' on Order '{order_id}'",
            reasoning=f"Applied transformation rules: {attempt_data.get('repair_plan') if isinstance(attempt_data, dict) else {}}",
            outcome=outcome,
            confidence=0.98,
            metadata={"partner_id": partner_id, "order_id": order_id, "incident_id": incident_id}
        )

        processing_decision_id = shared_context.record_decision(
            category="payment_clearing",
            scenario=f"Clearing order '{order_id}' downstream",
            reasoning="Passed canonical validation and Rete business safety checks",
            outcome="cleared" if outcome == "processed" else outcome,
            confidence=1.0,
            metadata={"order_id": order_id}
        )

        shared_context.add_causal_relationship(
            source_decision_id=repair_decision_id,
            target_decision_id=processing_decision_id,
            relationship_type="CAUSED"
        )

        res = {
            "success": True,
            "attempt_id": attempt_id,
            "incident_id": incident_id,
            "stored_outcome": outcome,
            "decision_id": repair_decision_id,
            "causal_chain_linked": True,
        }
        if normalized_from:
            res["normalized_from"] = normalized_from
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def escalate_incident(incident_data: dict, reason: str) -> str:
    """Flag an incident as escalated for human review and record escalation decision node in Semantica."""
    try:
        if isinstance(incident_data, str):
            incident_data = json.loads(incident_data)
        incident_id = (incident_data.get("incident_id") or incident_data.get("id")) if isinstance(incident_data, dict) else None
        
        escalation_id = default_repo.escalate_incident(
            incident_id=incident_id,
            reason=reason,
            evidence=incident_data if isinstance(incident_data, dict) else {}
        )

        # Record escalation in Semantica Decision Graph
        esc_decision_id = shared_context.record_decision(
            category="incident_escalation",
            scenario=f"Unsafe payload escalated for reason: {reason}",
            reasoning=reason,
            outcome="escalated_for_human_review",
            confidence=1.0,
            metadata={"incident_id": incident_id, "escalation_id": escalation_id}
        )

        return json.dumps({
            "escalated": True,
            "escalation_id": escalation_id,
            "incident_id": incident_id,
            "reason": reason,
            "action": "human review required",
            "decision_id": esc_decision_id,
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
