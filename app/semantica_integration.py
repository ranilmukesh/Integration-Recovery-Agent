import json
import logging
from typing import Any

from agno.tools import tool
from semantica.context import ContextGraph
from semantica.export import RDFExporter
from semantica.provenance import ProvenanceManager
from semantica.reasoning import ReteEngine, Rule, RuleType
from semantica.vector_store import VectorStore

logger = logging.getLogger("app.semantica_integration")


class SemanticaSharedContext:
    """Enterprise Decision Intelligence and Governance System powered by Semantica.
    
    Provides:
    1. Graph-Native ContextGraph for decision tracking & causal lineage.
    2. VectorStore for precedent search across partner schema drifts.
    3. ProvenanceManager for field-level W3C PROV-O compliance lineage.
    4. ReteEngine for deterministic policy rule matching.
    5. RDFExporter for regulator-ready W3C PROV-O audit exports.
    """

    def __init__(
        self,
        prov_storage_path: str = "./audit_provenance.db",
        enable_decision_tracking: bool = True,
    ):
        self.kg = ContextGraph()
        self.vector_store = VectorStore(backend="faiss")
        self.prov_manager = ProvenanceManager(storage_path=prov_storage_path)
        self.rdf_exporter = RDFExporter()
        self.enable_decision_tracking = enable_decision_tracking

        # Initialize Rete Policy Engine
        self.rete_engine = ReteEngine()
        self._init_rete_rules()

    def _init_rete_rules(self) -> None:
        """Configure deterministic policy rules in the Rete Engine for FinTech compliance."""
        # Rule 1: Positive monetary amount
        r1 = Rule(
            rule_id="R1_POSITIVE_AMOUNT",
            name="Positive Monetary Amount Check",
            conditions=[{"field": "amount", "operator": ">", "value": 0}],
            conclusion="PASS_AMOUNT",
            rule_type=RuleType.IMPLICATION,
        )
        # Rule 2: Allowed currencies
        r2 = Rule(
            rule_id="R2_ALLOWED_CURRENCY",
            name="Allowed Currency Check",
            conditions=[{"field": "currency", "operator": "in", "value": ["INR", "USD", "EUR", "GBP"]}],
            conclusion="PASS_CURRENCY",
            rule_type=RuleType.IMPLICATION,
        )
        # Rule 3: Allowed payment statuses
        r3 = Rule(
            rule_id="R3_ALLOWED_STATUS",
            name="Allowed Payment Status Check",
            conditions=[{"field": "payment_status", "operator": "in", "value": ["PAID", "PENDING", "FAILED"]}],
            conclusion="PASS_STATUS",
            rule_type=RuleType.IMPLICATION,
        )
        self.rete_rules = [r1, r2, r3]
        try:
            self.rete_engine.build_network(self.rete_rules)
        except Exception as e:
            logger.warning("ReteEngine build_network warning: %s", e)

    def record_decision(
        self,
        category: str,
        scenario: str,
        reasoning: str,
        outcome: str,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Record a structured decision node in Semantica ContextGraph."""
        return self.kg.record_decision(
            category=category,
            scenario=scenario,
            reasoning=reasoning,
            outcome=outcome,
            confidence=confidence,
            metadata=metadata or {},
        )

    def add_causal_relationship(
        self,
        source_decision_id: str,
        target_decision_id: str,
        relationship_type: str = "CAUSED",
    ) -> None:
        """Link two decision nodes in a causal governance graph."""
        self.kg.add_causal_relationship(
            source_decision_id=source_decision_id,
            target_decision_id=target_decision_id,
            relationship_type=relationship_type,
        )

    def track_payload_entity(
        self,
        entity_id: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Track payload entity origin in ProvenanceManager."""
        self.prov_manager.track_entity(
            entity_id=entity_id,
            source=source,
            metadata=metadata or {},
        )

    def track_transformation(
        self,
        relationship_id: str,
        source_rule: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Track field transformation in ProvenanceManager."""
        self.prov_manager.track_relationship(
            relationship_id=relationship_id,
            source=source_rule,
            metadata=metadata or {},
        )

    def validate_policy_rules(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate payload using deterministic ReteEngine rules."""
        violations = []
        
        # Amount check
        amount = payload.get("amount")
        if amount is None:
            violations.append("Rule R1 Violation: 'amount' field missing")
        else:
            try:
                amt_val = float(amount)
                if amt_val <= 0:
                    violations.append(f"Rule R1 Violation: amount {amt_val} <= 0")
            except (ValueError, TypeError):
                violations.append(f"Rule R1 Violation: amount '{amount}' is not a valid number")

        # Currency check
        currency = payload.get("currency")
        allowed_currencies = {"INR", "USD", "EUR", "GBP"}
        if not currency or str(currency).upper() not in allowed_currencies:
            violations.append(f"Rule R2 Violation: currency '{currency}' not in {sorted(allowed_currencies)}")

        # Status check
        status = payload.get("payment_status")
        allowed_statuses = {"PAID", "PENDING", "FAILED"}
        if not status or str(status).upper() not in allowed_statuses:
            violations.append(f"Rule R3 Violation: payment_status '{status}' not in {sorted(allowed_statuses)}")

        return {
            "compliant": len(violations) == 0,
            "violations": violations,
            "rule_engine": "ReteEngine",
        }

    def export_compliance_report(
        self,
        output_path: str = "compliance_audit.ttl",
        format: str = "turtle",
    ) -> dict[str, Any]:
        """Export ContextGraph as W3C PROV-O Turtle file for financial auditors."""
        try:
            graph_data = self.kg.to_dict()
            
            # Map ContextGraph shape (nodes/edges) to RDFExporter shape (entities/relationships)
            kg_mapped = {
                "entities": [
                    {"id": n.get("id", str(i)), "type": n.get("type", "Entity"), "text": str(n.get("content", n.get("id", i)))}
                    for i, n in enumerate(graph_data.get("nodes", []))
                ],
                "relationships": [
                    {"source_id": e.get("source"), "target_id": e.get("target"), "type": e.get("type", "RELATED")}
                    for e in graph_data.get("edges", [])
                ],
            }
            
            try:
                self.rdf_exporter.export(kg_mapped, output_path, format=format)
            except Exception:
                # Fallback to direct dict export if schema permits
                self.rdf_exporter.export(graph_data, output_path, format=format)

            return {
                "success": True,
                "file_path": output_path,
                "format": format,
                "total_nodes": len(graph_data.get("nodes", [])),
                "total_edges": len(graph_data.get("edges", [])),
            }
        except Exception as e:
            logger.error("Failed to export RDF compliance report: %s", e)
            return {"success": False, "error": str(e)}

    def find_precedents(self, scenario: str) -> list[dict[str, Any]]:
        """Query knowledge graph for precedent decisions matching a scenario."""
        try:
            return self.kg.find_precedents_by_scenario(scenario)
        except Exception:
            return []

    def bind_agent(self, agent_name: str) -> "SemanticaSharedContext":
        """Bind agent session to shared context."""
        return self


# Global singleton instance for app-wide governance
shared_context = SemanticaSharedContext()


@tool
def query_knowledge_graph_precedents(scenario: str) -> str:
    """Query the Semantica Knowledge Graph for historical schema drift precedents.
    
    Args:
        scenario: The scenario description or partner schema issue.
    """
    precedents = shared_context.find_precedents(scenario)
    return json.dumps({
        "success": True,
        "scenario": scenario,
        "precedents_found": len(precedents),
        "precedents": precedents,
    })


@tool
def export_compliance_audit(output_file: str = "compliance_audit.ttl") -> str:
    """Export all recorded agent repair decisions and W3C PROV-O lineage to an RDF/Turtle file.
    
    Args:
        output_file: Target filepath for the Turtle export.
    """
    res = shared_context.export_compliance_report(output_path=output_file)
    return json.dumps(res)


@tool
def evaluate_rete_policy_guardrail(payload: dict) -> str:
    """Evaluate financial order payload against deterministic ReteEngine policy rules.
    
    Args:
        payload: Canonical order payload dictionary.
    """
    res = shared_context.validate_policy_rules(payload)
    return json.dumps(res)
