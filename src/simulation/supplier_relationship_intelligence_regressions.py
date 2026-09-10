from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact
from src.core.master_data import SupplierRelationshipSettings
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.models import Shipment
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteSupplierRFQRepository
from src.core.supplier_dispatch_control import (
    record_supplier_contact_attempt, secondary_dispatch_gate,
)
from src.core.supplier_intelligence_policy import build_supplier_operational_learning_policy
from src.core.supplier_learning_service import derive_supplier_history_learning
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQResponse, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _draft(workflow_id: str, rfq_id: str, supplier_name: str, sent_at: datetime) -> SupplierRFQDraft:
    return SupplierRFQDraft(
        rfq_id=rfq_id, workflow_id=workflow_id, supplier_name=supplier_name,
        priority=1, recipient_email=f"{rfq_id}@example.invalid", supplier_role="primary",
        dispatch_tier="primary", subject="RFQ", body="RFQ", status="awaiting_response",
        sent_at=sent_at,
    )


def _quote(draft: SupplierRFQDraft, received_at: datetime) -> SupplierRFQResponse:
    return SupplierRFQResponse(
        rfq_id=draft.rfq_id, supplier_name=draft.supplier_name, rfq_priority=draft.priority,
        status="quoted", cost=2400, currency="EUR", transit_time="4 gün",
        equipment_type="Tenteli", pricing_basis="all_in", received_at=received_at,
    )


def evaluate_supplier_relationship_intelligence_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []
    def check(condition, label):
        (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository()
    supplier = create_supplier_master(
        repository=masters, entry_id="relationship-intel-supplier",
        supplier_name="Relationship Intelligence Supplier", updated_by="Regression Operator",
        role="primary", service_types=["FTL"], equipment_types=["Tenteli"],
        relationship=SupplierRelationshipSettings(
            preferred_contact_channels=["email", "phone", "whatsapp"],
            phone_escalation_after_minutes=60, whatsapp_escalation_after_minutes=60,
        ), created_at=NOW - timedelta(days=30),
    )
    rfqs = InMemorySupplierRFQRepository()
    workflow = SupplierRFQWorkflow(
        workflow_id="relationship-intel-workflow", shipment=Shipment(
            customer_name="Synthetic", transport_mode="road", service_type="FTL",
            pickup_country="Türkiye", delivery_country="Almanya", equipment_type="Tenteli",
        ), automation_timing_version=1,
    )
    rfqs.save_workflow(workflow)
    guard_draft = _draft(workflow.workflow_id, "relationship-guard", supplier.supplier_name, NOW - timedelta(hours=3))
    rfqs.save_drafts([guard_draft])
    unreachable = record_supplier_contact_attempt(
        repository=rfqs, rfq_id=guard_draft.rfq_id, channel="phone",
        outcome="unreachable", recorded_by="Regression Operator", attempted_at=NOW - timedelta(hours=2),
    )
    gate = secondary_dispatch_gate(rfqs, workflow.workflow_id)
    check(
        unreachable["capacity_failure_recorded"] is False
        and unreachable["secondary_release_recorded"] is False
        and not rfqs.list_acknowledgements(guard_draft.rfq_id)
        and gate["allowed"] is False,
        "unsuccessful phone or WhatsApp contact evidence never becomes capacity failure or secondary release",
    )
    working = record_supplier_contact_attempt(
        repository=rfqs, rfq_id=guard_draft.rfq_id, channel="whatsapp",
        outcome="acknowledged_working", recorded_by="Regression Operator",
        attempted_at=NOW - timedelta(minutes=90),
    )
    check(
        working["commercial_response_recorded"] is False
        and working["acknowledgement"] is not None
        and rfqs.list_acknowledgements(guard_draft.rfq_id)[0].channel == "whatsapp",
        "successful manual contact records non-commercial acknowledgement and starts the existing grace evidence path",
    )

    # Six successful phone contacts and six WhatsApp attempts create enough evidence
    # for a channel recommendation, while only one WhatsApp attempt is acknowledged.
    for index in range(12):
        sent_at = NOW - timedelta(days=20-index, hours=4)
        draft = _draft(workflow.workflow_id, f"history-{index}", supplier.supplier_name, sent_at)
        rfqs.save_drafts([draft])
        channel = "phone" if index < 6 else "whatsapp"
        outcome = "acknowledged_working" if index < 6 or index == 6 else "no_response"
        attempt_at = sent_at + timedelta(minutes=30)
        record_supplier_contact_attempt(
            repository=rfqs, rfq_id=draft.rfq_id, channel=channel, outcome=outcome,
            recorded_by="Regression Operator", attempted_at=attempt_at,
        )
        rfqs.save_responses([_quote(draft, attempt_at + timedelta(minutes=150))])

    learning = InMemoryLearningFactRepository()
    derived = derive_supplier_history_learning(
        supplier_id=supplier.supplier_id, master_repository=masters,
        supplier_repository=rfqs, learning_repository=learning,
        created_by="Regression Operator", occurred_at=NOW,
    )
    proposed = {item["fact_key"]: item for item in derived["proposed_facts"]}
    required = {
        "commercial.usable_quote_rate_percent",
        "contact.phone.ack_rate_percent",
        "contact.whatsapp.ack_rate_percent",
        "contact.phone.after_ack_quote_median_minutes",
    }
    check(
        required.issubset(proposed)
        and proposed["contact.phone.ack_rate_percent"]["status"] == "proposed"
        and proposed["contact.phone.ack_rate_percent"]["evidence"][0]["observed_at"] < NOW,
        "contact-attempt history derives proposed channel metrics whose recency is anchored to source evidence, not derivation time",
    )
    for key in required:
        confirm_learning_fact(
            repository=learning, fact_id=proposed[key]["fact_id"], reviewed_by="Regression Operator",
            review_note="Regression confirms structured contact-history evidence.", occurred_at=NOW,
        )
    policy = build_supplier_operational_learning_policy(
        supplier=supplier, learning_repository=learning, base_first_reminder_minutes=30,
        base_acknowledged_wait_minutes=120, acknowledgement_channel="phone", as_of=NOW,
    )
    check(
        policy.preferred_contact_channel_advisory == "phone"
        and policy.contact_escalation_learning_applied is False
        and policy.effective_acknowledged_wait_minutes == 150
        and policy.acknowledged_wait_source == "confirmed_learning",
        "confirmed contact metrics may recommend a channel and extend matching-channel wait without authorizing automatic escalation",
    )

    manual_supplier = supplier.model_copy(update={
        "relationship": supplier.relationship.model_copy(update={"acknowledged_wait_minutes": 135})
    })
    manual_policy = build_supplier_operational_learning_policy(
        supplier=manual_supplier, learning_repository=learning, base_first_reminder_minutes=30,
        base_acknowledged_wait_minutes=120, acknowledgement_channel="phone", as_of=NOW,
    )
    check(
        manual_policy.effective_acknowledged_wait_minutes == 135
        and manual_policy.acknowledged_wait_source == "supplier_master",
        "explicit supplier-master acknowledgement timing remains above channel-specific learned timing",
    )

    with TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "relationship.sqlite3", retention_days=365)
        durable = SQLiteSupplierRFQRepository(store)
        durable.save_workflow(workflow)
        durable_draft = _draft(workflow.workflow_id, "durable-contact", supplier.supplier_name, NOW - timedelta(hours=2))
        durable.save_drafts([durable_draft])
        saved = record_supplier_contact_attempt(
            repository=durable, rfq_id=durable_draft.rfq_id, channel="phone",
            outcome="no_response", recorded_by="Regression Operator", attempted_at=NOW - timedelta(hours=1),
        )
        reopened = SQLiteSupplierRFQRepository(store)
        durable_items = reopened.list_contact_attempts(durable_draft.rfq_id)
    check(
        len(durable_items) == 1 and durable_items[0].attempt_id == saved["contact_attempt"]["attempt_id"],
        "supplier contact-attempt evidence is durable in SQLite and survives repository reconstruction",
    )

    check(
        route_allowed("POST", "/supplier-rfqs/rfq-1/contact-attempts")
        and not route_allowed("GET", "/supplier-rfqs/rfq-1/contact-attempts"),
        "controlled pilot admits only the explicit contact-attempt evidence mutation surface",
    )

    web = Path("ui/web_shell/app.js").read_text(encoding="utf-8")
    check(
        "/contact-attempts" in web and "Telefon · Ulaşılamadı" in web
        and "kapasite başarısızlığı sayılmaz" in web,
        "browser captures phone and WhatsApp contact outcomes without presenting silence as supplier unavailability",
    )

    for label in passes:
        print(f"PASS {label}")
    for label in failures:
        print(f"FAIL {label}")
    print("\nSupplier relationship intelligence regressions: " + ("PASS" if not failures else "FAIL"))
    return {"passes": passes, "failures": failures, "passed": not failures}


if __name__ == "__main__":
    outcome = evaluate_supplier_relationship_intelligence_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
