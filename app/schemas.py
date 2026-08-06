from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CanonicalOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partner_id: str
    order_id: str
    customer_id: str
    amount: float
    currency: Literal["INR", "USD", "EUR", "GBP"]
    payment_status: Literal["PAID", "PENDING", "FAILED"]


class ValidationErrorDetail(BaseModel):
    type: str
    field: str | None = None
    fields: list[str] | None = None
    expected: str | None = None
    allowed: list[str] | None = None
    message: str | None = None


class ValidationReport(BaseModel):
    valid: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)


class RepairRuleItem(BaseModel):
    source_field: str
    target_field: str
    operation: Literal["rename", "to_float", "uppercase"]
    confidence: float = 1.0
    status: Literal["proposed", "approved", "rejected"] = "approved"


class RepairPlan(BaseModel):
    partner_id: str
    rules: list[RepairRuleItem]


class SandboxResult(BaseModel):
    success: bool
    repaired_payload: dict[str, Any] | None = None
    applied_rules: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class BusinessResult(BaseModel):
    safe: bool
    errors: list[str] = Field(default_factory=list)


class IncidentRecord(BaseModel):
    id: str | None = None
    partner_id: str
    order_id: str | None = None
    raw_payload: dict[str, Any]
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    incident_type: str
    status: Literal["detected", "repaired", "processed", "escalated", "failed"] = "detected"
    created_at: str | None = None
    resolved_at: str | None = None


class EscalationRecord(BaseModel):
    id: str | None = None
    incident_id: str | None = None
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "acknowledged", "resolved"] = "open"
    created_at: str | None = None
