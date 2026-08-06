import copy
from typing import Any

from app.schemas import SandboxResult

ALLOWED_OPERATIONS = {"rename", "to_float", "uppercase"}


def apply_repair_plan_in_sandbox(payload: dict[str, Any], plan: dict[str, Any]) -> SandboxResult:
    """Apply a repair plan to a copy of payload in memory (sandbox).
    Does NOT mutate input payload.
    Supports operations: 'rename', 'to_float', 'uppercase'.
    """
    if not isinstance(payload, dict):
        return SandboxResult(success=False, error="Payload must be a dictionary")

    repaired = copy.deepcopy(payload)
    applied_rules: list[dict[str, Any]] = []
    rules = plan.get("rules", [])

    if not isinstance(rules, list):
        return SandboxResult(success=False, error="Plan rules must be a list")

    target_fields_populated = set()

    for rule in rules:
        if not isinstance(rule, dict):
            return SandboxResult(success=False, error="Rule must be a dictionary")

        src = rule.get("source_field")
        tgt = rule.get("target_field")
        op = rule.get("operation")

        if not src or not tgt or not op:
            return SandboxResult(
                success=False,
                error=f"Invalid rule structure: {rule}. Must have source_field, target_field, operation"
            )

        if op not in ALLOWED_OPERATIONS:
            return SandboxResult(
                success=False,
                error=f"Unsupported operation '{op}'. Allowed operations: {sorted(ALLOWED_OPERATIONS)}"
            )

        if src not in repaired:
            # Source field not in payload, skip or return error if required
            continue

        if tgt in target_fields_populated:
            return SandboxResult(
                success=False,
                error=f"Duplicate target field collision: '{tgt}' assigned multiple times"
            )

        val = repaired.pop(src)

        try:
            if op == "rename":
                repaired[tgt] = val
            elif op == "to_float":
                repaired[tgt] = float(val)
            elif op == "uppercase":
                repaired[tgt] = str(val).upper()
            
            target_fields_populated.add(tgt)
            applied_rules.append({
                "source_field": src,
                "target_field": tgt,
                "operation": op
            })
        except (ValueError, TypeError) as e:
            return SandboxResult(
                success=False,
                error=f"Conversion failure on field '{src}' to '{tgt}' using op '{op}': {e!s}"
            )

    return SandboxResult(
        success=True,
        repaired_payload=repaired,
        applied_rules=applied_rules
    )
