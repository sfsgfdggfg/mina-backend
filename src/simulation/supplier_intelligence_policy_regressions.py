from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.automation_planning import supplier_reminder_plan
from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.master_data import SupplierRelationshipSettings
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.models import Shipment
from src.core.pilot_access import route_allowed
from src.core.supplier_dispatch_control import record_supplier_acknowledgement
from src.core.supplier_dispatch_policy import SupplierDispatchPolicy
from src.core.supplier_intelligence_policy import build_supplier_operational_learning_policy
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.supplier_selection import select_suppliers_for_shipment

NOW = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)


def _supplier(repo, name, *, role="primary", relationship=None, reliability=0.7, price=0.7, speed=0.7):
    return create_supplier_master(
        repository=repo, entry_id=f"supplier:{name.lower().replace(' ', '-')}",
        supplier_name=name, role=role,
        reliability_score=reliability, price_score=price, speed_score=speed,
        relationship=relationship or SupplierRelationshipSettings(),
        updated_by="Regression Operator", created_at=NOW - timedelta(days=30),
    )


def _fact(repo, supplier, key, value, unit, confidence, *, age_days=10, status="confirmed"):
    reviewed = status == "confirmed"
    fact = LearningFact(
        entry_id=f"reg:{supplier.supplier_id}:{key}:{age_days}:{status}",
        subject_type="supplier", subject_id=supplier.supplier_id,
        subject_label=supplier.supplier_name, fact_key=key, value=value,
        value_unit=unit, confidence=confidence, source_type="minai_inference",
        evidence=[LearningEvidence(
            source_type="operation_history", source_reference=f"reg-evidence:{key}:{age_days}",
            observed_at=NOW - timedelta(days=age_days), summary="Synthetic bounded supplier history evidence.",
        )],
        status=status, created_at=NOW - timedelta(days=age_days),
        created_by="Regression", updated_at=NOW - timedelta(days=age_days),
        reviewed_at=(NOW - timedelta(days=age_days - 1)) if reviewed else None,
        reviewed_by="Regression Operator" if reviewed else None,
        review_note="Confirmed for policy regression." if reviewed else None,
    )
    repo.create(fact)
    return fact


def evaluate_supplier_intelligence_policy_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []
    def check(condition, label): (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository(); facts = InMemoryLearningFactRepository()
    learned = _supplier(masters, "Learned Primary")
    _fact(facts, learned, "response.median_minutes", 48, "minutes", 0.95)
    _fact(facts, learned, "response.after_ack_median_minutes", 150, "minutes", 0.95)
    _fact(facts, learned, "commercial.usable_quote_rate_percent", 92, "percent", 0.95)
    _fact(facts, learned, "commercial.negotiated_reduction_percent", 6.4, "percent", 0.90)
    policy = build_supplier_operational_learning_policy(
        supplier=learned, learning_repository=facts,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120, as_of=NOW,
    )
    check(
        0 < policy.ranking_adjustment <= 0.06
        and policy.effective_first_reminder_minutes == 50
        and policy.first_reminder_source == "confirmed_learning"
        and policy.effective_acknowledged_wait_minutes == 150
        and policy.acknowledged_wait_source == "confirmed_learning"
        and policy.negotiation_advisory_percent == 6.4
        and policy.contact_escalation_learning_applied is False,
        "confirmed recent structured supplier learning applies bounded ranking, patient timing and advisory negotiation",
    )

    proposed_repo = InMemoryLearningFactRepository(); proposed = _supplier(masters, "Proposed Only")
    _fact(proposed_repo, proposed, "response.median_minutes", 5, "minutes", 0.99, status="proposed")
    _fact(proposed_repo, proposed, "commercial.usable_quote_rate_percent", 100, "percent", 0.99, status="proposed")
    proposed_policy = build_supplier_operational_learning_policy(
        supplier=proposed, learning_repository=proposed_repo,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120, as_of=NOW,
    )
    check(
        proposed_policy.ranking_adjustment == 0
        and proposed_policy.effective_first_reminder_minutes == 30
        and proposed_policy.effective_acknowledged_wait_minutes == 120,
        "proposed learning facts never gain runtime authority regardless of confidence",
    )

    manual_repo = InMemoryLearningFactRepository()
    manual = _supplier(masters, "Manual Timing", relationship=SupplierRelationshipSettings(
        first_reminder_minutes=20, acknowledged_wait_minutes=75,
    ))
    _fact(manual_repo, manual, "response.median_minutes", 60, "minutes", 0.99)
    _fact(manual_repo, manual, "response.after_ack_median_minutes", 180, "minutes", 0.99)
    _fact(manual_repo, manual, "commercial.usable_quote_rate_percent", 100, "percent", 0.99)
    manual_policy = build_supplier_operational_learning_policy(
        supplier=manual, learning_repository=manual_repo,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120, as_of=NOW,
    )
    check(
        manual_policy.effective_first_reminder_minutes == 20
        and manual_policy.first_reminder_source == "supplier_master"
        and manual_policy.effective_acknowledged_wait_minutes == 75
        and manual_policy.acknowledged_wait_source == "supplier_master",
        "explicit supplier master timing overrides learned timing",
    )

    old_repo = InMemoryLearningFactRepository(); old = _supplier(masters, "Old Evidence")
    _fact(old_repo, old, "response.median_minutes", 10, "minutes", 1.0, age_days=500)
    _fact(old_repo, old, "commercial.usable_quote_rate_percent", 100, "percent", 1.0, age_days=500)
    old_policy = build_supplier_operational_learning_policy(
        supplier=old, learning_repository=old_repo,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120, as_of=NOW,
    )
    check(
        old_policy.ranking_adjustment == 0 and old_policy.first_reminder_source == "dispatch_default",
        "stale evidence decays below runtime authority instead of becoming permanent supplier behavior",
    )

    # Same base capability score: confirmed learning may reorder primaries, never dispatch tiers.
    backup = _supplier(masters, "Learned Backup", role="backup", reliability=1, price=1, speed=1)
    _fact(facts, backup, "response.median_minutes", 10, "minutes", 0.99)
    _fact(facts, backup, "commercial.usable_quote_rate_percent", 100, "percent", 0.99)
    plain = _supplier(masters, "Plain Primary")
    capabilities = [
        {"supplier_name": learned.supplier_name, "role":"primary", "countries":["Germany"], "route_regions":["international"], "service_types":["FTL"], "equipment_types":["Tenteli"], "reliability_score":.7, "price_score":.7, "speed_score":.7, "notes":"reg"},
        {"supplier_name": plain.supplier_name, "role":"primary", "countries":["Germany"], "route_regions":["international"], "service_types":["FTL"], "equipment_types":["Tenteli"], "reliability_score":.7, "price_score":.7, "speed_score":.7, "notes":"reg"},
        {"supplier_name": backup.supplier_name, "role":"backup", "countries":["Germany"], "route_regions":["international"], "service_types":["FTL"], "equipment_types":["Tenteli"], "reliability_score":1, "price_score":1, "speed_score":1, "notes":"reg"},
    ]
    selection = select_suppliers_for_shipment(
        Shipment(customer_name="Synthetic", transport_mode="road", pickup_country="Türkiye", delivery_country="Germany", service_type="FTL", equipment_type="Tenteli"),
        equipment_decision={"selected_equipment":"Tenteli"}, risk_assessment={"risk_level":"green"},
        supplier_capabilities=capabilities, master_data_repository=masters,
        learning_fact_repository=facts, policy_as_of=NOW,
    )
    selected = selection["selected_suppliers"]
    check(
        selected[0]["supplier_name"] == learned.supplier_name
        and selected[0]["learning_adjustment"] > 0
        and selected[-1]["dispatch_tier"] == "secondary",
        "confirmed learning can reorder eligible peers but cannot promote a secondary supplier over primaries",
    )

    rfqs = InMemorySupplierRFQRepository(); actions = InMemoryAutomationActionRepository()
    workflow = SupplierRFQWorkflow(
        workflow_id="learned-timing", shipment=Shipment(customer_name="Synthetic", transport_mode="road"),
        automation_timing_version=1, dispatch_policy=SupplierDispatchPolicy(),
    ); rfqs.save_workflow(workflow)
    draft = SupplierRFQDraft(
        rfq_id="learned-rfq", workflow_id=workflow.workflow_id, supplier_name=learned.supplier_name,
        priority=1, recipient_email="learned@example.invalid", supplier_role="primary", dispatch_tier="primary",
        subject="RFQ", body="RFQ", status="awaiting_response", sent_at=NOW,
    ); rfqs.save_drafts([draft])
    plan = supplier_reminder_plan(
        supplier_repository=rfqs, action_repository=actions, draft=draft, now=NOW + timedelta(minutes=40),
        master_data_repository=masters, learning_fact_repository=facts,
    )
    record_supplier_acknowledgement(
        repository=rfqs, rfq_id=draft.rfq_id, channel="whatsapp", recorded_by="Operator",
        acknowledged_at=NOW + timedelta(minutes=5),
    )
    ack_plan = supplier_reminder_plan(
        supplier_repository=rfqs, action_repository=actions, draft=draft, now=NOW + timedelta(minutes=100),
        master_data_repository=masters, learning_fact_repository=facts,
    )
    check(
        plan["state"] == "waiting"
        and plan["supplier_relationship"]["first_reminder_minutes"] == 50
        and plan["supplier_relationship"]["first_reminder_source"] == "confirmed_learning"
        and ack_plan["supplier_relationship"]["acknowledged_wait_minutes"] == 150
        and ack_plan["supplier_relationship"]["acknowledged_wait_source"] == "confirmed_learning",
        "scheduler planning exposes the same learned timing authority for silent and acknowledged supplier states",
    )

    check(
        route_allowed("GET", f"/master-data/suppliers/{learned.supplier_id}/operational-policy")
        and not route_allowed("POST", f"/master-data/suppliers/{learned.supplier_id}/operational-policy"),
        "supplier operational policy is exposed read-only through the controlled pilot browser boundary",
    )

    result = {"passes": passes, "failures": failures, "passed": not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier intelligence operational policy regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    outcome = evaluate_supplier_intelligence_policy_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
