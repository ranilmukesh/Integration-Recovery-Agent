import json
import uuid
from typing import Any

from app.db import get_db_connection, is_postgres


class Repository:
    def __init__(self, db_url: str | None = None):
        self.db_url = db_url

    def _get_conn(self):
        return get_db_connection(self.db_url)

    def _sql(self, query: str) -> str:
        if not is_postgres(self.db_url):
            return query.replace("%s", "?")
        return query

    def _json(self, val: Any) -> str:
        if isinstance(val, str):
            return val
        return json.dumps(val)

    def _parse_json(self, val: Any) -> Any:
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return val
        return val

    def lookup_repair_rules(self, partner_id: str, status: str = "approved") -> list[dict[str, Any]]:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            query = self._sql(
                "SELECT id, partner_id, source_field, target_field, operation, confidence, status, hit_count "
                "FROM repair_rules WHERE partner_id = %s AND status = %s ORDER BY hit_count DESC"
            )
            cur.execute(query, (partner_id, status))
            rows = cur.fetchall()
            results = []
            for r in rows:
                r_dict = dict(r) if hasattr(r, "keys") else {
                    "id": str(r[0]), "partner_id": r[1], "source_field": r[2],
                    "target_field": r[3], "operation": r[4], "confidence": float(r[5]),
                    "status": r[6], "hit_count": r[7]
                }
                r_dict["id"] = str(r_dict["id"])
                if "confidence" in r_dict and r_dict["confidence"] is not None:
                    r_dict["confidence"] = float(r_dict["confidence"])
                results.append(r_dict)
            return results
        finally:
            cur.close()
            conn.close()

    def save_approved_repair_rule(
        self,
        partner_id: str,
        source_field: str,
        target_field: str,
        operation: str,
        confidence: float = 1.0
    ) -> dict[str, Any]:
        conn = self._get_conn()
        cur = conn.cursor()
        rule_id = str(uuid.uuid4())
        try:
            if is_postgres(self.db_url):
                cur.execute(
                    """
                    INSERT INTO repair_rules (id, partner_id, source_field, target_field, operation, confidence, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'approved')
                    ON CONFLICT (partner_id, source_field, target_field, operation)
                    DO UPDATE SET status = 'approved', last_used_at = now()
                    RETURNING id, partner_id, source_field, target_field, operation, status, hit_count
                    """,
                    (rule_id, partner_id, source_field, target_field, operation, confidence)
                )
                row = cur.fetchone()
                result = dict(row)
                if "id" in result:
                    result["id"] = str(result["id"])
            else:
                query = self._sql(
                    """
                    INSERT OR REPLACE INTO repair_rules (id, partner_id, source_field, target_field, operation, confidence, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'approved')
                    """
                )
                cur.execute(query, (rule_id, partner_id, source_field, target_field, operation, confidence))
                result = {
                    "id": str(rule_id),
                    "partner_id": partner_id,
                    "source_field": source_field,
                    "target_field": target_field,
                    "operation": operation,
                    "status": "approved",
                    "hit_count": 0
                }
            conn.commit()
            return result
        finally:
            cur.close()
            conn.close()

    def increment_rule_hit_count(self, partner_id: str, source_field: str, target_field: str, operation: str) -> None:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            if is_postgres(self.db_url):
                cur.execute(
                    """
                    UPDATE repair_rules
                    SET hit_count = hit_count + 1, last_used_at = now()
                    WHERE partner_id = %s AND source_field = %s AND target_field = %s AND operation = %s
                    """,
                    (partner_id, source_field, target_field, operation)
                )
            else:
                query = self._sql(
                    """
                    UPDATE repair_rules
                    SET hit_count = hit_count + 1, last_used_at = CURRENT_TIMESTAMP
                    WHERE partner_id = %s AND source_field = %s AND target_field = %s AND operation = %s
                    """
                )
                cur.execute(query, (partner_id, source_field, target_field, operation))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def record_incident(
        self,
        partner_id: str,
        order_id: str | None,
        raw_payload: dict[str, Any],
        validation_errors: list[dict[str, Any]],
        incident_type: str,
        status: str = "detected"
    ) -> str:
        import hashlib

        def mask_sensitive_payload(payload: dict | Any) -> dict | Any:
            if not isinstance(payload, dict):
                return payload
            masked = payload.copy()
            for field in ["customer_id", "client_id"]:
                if field in masked:
                    masked[field] = hashlib.sha256(str(masked[field]).encode()).hexdigest()
            return masked

        conn = self._get_conn()
        cur = conn.cursor()
        incident_id = str(uuid.uuid4())
        try:
            query = self._sql(
                """
                INSERT INTO integration_incidents (id, partner_id, order_id, raw_payload, validation_errors, incident_type, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
            )

            safe_payload = mask_sensitive_payload(raw_payload) if isinstance(raw_payload, dict) else raw_payload

            cur.execute(
                query,
                (
                    incident_id, partner_id, order_id,
                    self._json(safe_payload), self._json(validation_errors),
                    incident_type, status
                )
            )
            conn.commit()
            return incident_id
        finally:
            cur.close()
            conn.close()

    def update_incident_status(self, incident_id: str, status: str) -> None:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            if is_postgres(self.db_url):
                cur.execute(
                    "UPDATE integration_incidents SET status = %s, resolved_at = now() WHERE id = %s",
                    (status, incident_id)
                )
            else:
                query = self._sql("UPDATE integration_incidents SET status = %s, resolved_at = CURRENT_TIMESTAMP WHERE id = %s")
                cur.execute(query, (status, incident_id))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def record_repair_attempt(
        self,
        incident_id: str,
        repair_plan: dict[str, Any],
        before_payload: dict[str, Any],
        after_payload: dict[str, Any] | None = None,
        validation_result: dict[str, Any] | None = None,
        business_result: dict[str, Any] | None = None,
        processing_result: dict[str, Any] | None = None,
        outcome: str = "processed"
    ) -> str:
        conn = self._get_conn()
        cur = conn.cursor()
        attempt_id = str(uuid.uuid4())
        try:
            query = self._sql(
                """
                INSERT INTO repair_attempts (id, incident_id, repair_plan, before_payload, after_payload, validation_result, business_result, processing_result, outcome)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
            )
            cur.execute(
                query,
                (
                    attempt_id, incident_id,
                    self._json(repair_plan), self._json(before_payload),
                    self._json(after_payload) if after_payload else None,
                    self._json(validation_result) if validation_result else None,
                    self._json(business_result) if business_result else None,
                    self._json(processing_result) if processing_result else None,
                    outcome
                )
            )
            conn.commit()
            return attempt_id
        finally:
            cur.close()
            conn.close()

    def process_order_idempotent(
        self,
        idempotency_key: str,
        order_id: str,
        payload: dict[str, Any],
        result: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            query_check = self._sql("SELECT result FROM processed_orders WHERE idempotency_key = %s")
            cur.execute(query_check, (idempotency_key,))
            row = cur.fetchone()
            if row:
                existing_res = dict(row)["result"] if hasattr(row, "keys") else row[0]
                return self._parse_json(existing_res), False

            query_ins = self._sql(
                """
                INSERT INTO processed_orders (idempotency_key, order_id, payload, result)
                VALUES (%s, %s, %s, %s)
                """
            )
            cur.execute(query_ins, (idempotency_key, order_id, self._json(payload), self._json(result)))
            conn.commit()
            return result, True
        finally:
            cur.close()
            conn.close()

    def escalate_incident(self, incident_id: str | None, reason: str, evidence: dict[str, Any]) -> str:
        conn = self._get_conn()
        cur = conn.cursor()
        escalation_id = str(uuid.uuid4())
        try:
            query_esc = self._sql(
                """
                INSERT INTO escalations (id, incident_id, reason, evidence, status)
                VALUES (%s, %s, %s, %s, 'open')
                """
            )
            cur.execute(query_esc, (escalation_id, incident_id, reason, self._json(evidence)))
            if incident_id:
                if is_postgres(self.db_url):
                    cur.execute("UPDATE integration_incidents SET status = 'escalated', resolved_at = now() WHERE id = %s", (incident_id,))
                else:
                    query_upd = self._sql("UPDATE integration_incidents SET status = 'escalated', resolved_at = CURRENT_TIMESTAMP WHERE id = %s")
                    cur.execute(query_upd, (incident_id,))
            conn.commit()
            return escalation_id
        finally:
            cur.close()
            conn.close()

    def get_incident_audit(self, incident_id: str) -> dict[str, Any]:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            query_inc = self._sql("SELECT * FROM integration_incidents WHERE id = %s")
            cur.execute(query_inc, (incident_id,))
            row = cur.fetchone()
            if not row:
                return {"error": f"Incident {incident_id} not found"}
            incident = dict(row)
            incident["id"] = str(incident["id"])
            incident["raw_payload"] = self._parse_json(incident.get("raw_payload"))
            incident["validation_errors"] = self._parse_json(incident.get("validation_errors"))
            if incident.get("created_at"):
                incident["created_at"] = str(incident["created_at"])
            if incident.get("resolved_at"):
                incident["resolved_at"] = str(incident["resolved_at"])

            query_att = self._sql("SELECT * FROM repair_attempts WHERE incident_id = %s")
            cur.execute(query_att, (incident_id,))
            attempts_rows = cur.fetchall()
            attempts = []
            for a in attempts_rows:
                att = dict(a)
                att["id"] = str(att["id"])
                att["incident_id"] = str(att["incident_id"])
                att["repair_plan"] = self._parse_json(att.get("repair_plan"))
                att["before_payload"] = self._parse_json(att.get("before_payload"))
                att["after_payload"] = self._parse_json(att.get("after_payload"))
                att["validation_result"] = self._parse_json(att.get("validation_result"))
                att["business_result"] = self._parse_json(att.get("business_result"))
                att["processing_result"] = self._parse_json(att.get("processing_result"))
                if att.get("created_at"):
                    att["created_at"] = str(att["created_at"])
                attempts.append(att)

            query_esc = self._sql("SELECT * FROM escalations WHERE incident_id = %s")
            cur.execute(query_esc, (incident_id,))
            escalation_rows = cur.fetchall()
            escalations = []
            for e in escalation_rows:
                esc = dict(e)
                esc["id"] = str(esc["id"])
                if esc.get("incident_id"):
                    esc["incident_id"] = str(esc["incident_id"])
                esc["evidence"] = self._parse_json(esc.get("evidence"))
                if esc.get("created_at"):
                    esc["created_at"] = str(esc["created_at"])
                escalations.append(esc)

            return {
                "incident": incident,
                "attempts": attempts,
                "escalations": escalations
            }
        finally:
            cur.close()
            conn.close()
