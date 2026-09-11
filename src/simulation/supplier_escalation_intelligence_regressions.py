from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from src.core.automation_action import ScheduledAutomationAction
from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.automation_planning import supplier_action_key
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
    SupplierEscalationEvidenceError,
    record_supplier_escalation_evidence,
    secondary_dispatch_gate,
)
from src.core.supplier_dispatch_policy import SupplierDispatchPolicy
from src.core.supplier_intelligence_policy import build_supplier_operational_learning_policy
from src.core.supplier_learning_service import derive_supplier_history_learning
from src.core.supplier_next_best_action import build_supplier_next_best_action
from src.core.supplier_rfq import SupplierEscalationEvidence, SupplierRFQDraft, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository

NOW = datetime(2026, 9, 11, 7, 0, tzinfo=timezone.utc)


def _supplier(repo, name="Escalation Trans", *, management=None):
    return create_supplier_master(
        repository=repo, entry_id=f"supplier:{name.lower().replace(' ', '-')}",
        supplier_name=name, role="primary", reliability_score=.8, price_score=.7, speed_score=.7,
        relationship=SupplierRelationshipSettings(
            preferred_contact_channels=["phone", "whatsapp"],
            management_escalation_allowed=management,
        ),
        updated_by="Regression Operator", created_at=NOW - timedelta(days=60),
    )


def _rfq_fixture():
    repo = InMemorySupplierRFQRepository()
    workflow = SupplierRFQWorkflow(
        workflow_id="esc-workflow", shipment=Shipment(customer_name="Synthetic", transport_mode="road"),
        dispatch_policy=SupplierDispatchPolicy(), automation_timing_version=1,
    )
    draft = SupplierRFQDraft(
        rfq_id="esc-rfq", workflow_id=workflow.workflow_id, supplier_name="Escalation Trans",
        priority=1, recipient_email="pricing@escalation.invalid", supplier_role="primary",
        dispatch_tier="primary", subject="RFQ", body="RFQ", status="awaiting_response",
        sent_at=NOW - timedelta(hours=2),
    )
    repo.save_workflow(workflow.model_copy(update={"rfq_ids":[draft.rfq_id]}))
    repo.save_drafts([draft])
    return repo, workflow, draft




def _sent_reminder(actions, draft, *, completed_at=NOW - timedelta(minutes=10)):
    key = supplier_action_key(draft.rfq_id, "supplier_no_response_reminder")
    action = ScheduledAutomationAction(
        action_key=key, action_type="supplier_no_response_reminder",
        workflow_id=draft.workflow_id, resource_id=draft.rfq_id,
        due_at=draft.sent_at + timedelta(minutes=30),
        status="sent", reserved_at=draft.sent_at + timedelta(minutes=30),
        completed_at=completed_at, provider_name="regression",
        provider_message_id=f"msg:{draft.rfq_id}",
    )
    actions.save(action)
    return action

def evaluate_supplier_escalation_intelligence_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository(); supplier = _supplier(masters)
    rfqs, workflow, draft = _rfq_fixture(); actions = InMemoryAutomationActionRepository()
    _sent_reminder(actions, draft)
    result = record_supplier_escalation_evidence(
        repository=rfqs, action_repository=actions, rfq_id=draft.rfq_id,
        level="operator", channel="phone", outcome="no_response",
        recorded_by="Regression Operator", escalated_at=NOW,
        master_data_repository=masters,
    )
    gate = secondary_dispatch_gate(rfqs, workflow.workflow_id)
    check(
        len(rfqs.list_escalation_evidence(draft.rfq_id)) == 1
        and len(rfqs.list_contact_attempts(draft.rfq_id)) == 1
        and not gate["allowed"] and not result["capacity_failure_recorded"]
        and not result["secondary_release_recorded"],
        "operator escalation evidence preserves silence without inventing capacity failure or secondary release",
    )

    management_result = record_supplier_escalation_evidence(
        repository=rfqs, action_repository=actions, rfq_id=draft.rfq_id,
        level="management", channel="phone", outcome="acknowledged_working",
        recorded_by="Regression Manager", escalated_at=NOW + timedelta(minutes=5),
        master_data_repository=masters,
    )
    check(
        management_result["acknowledgement"] is not None
        and management_result["contact_attempt"] is None
        and len(rfqs.list_acknowledgements(draft.rfq_id)) == 1,
        "management acknowledgement starts the existing non-commercial grace evidence without polluting operator contact attempts",
    )

    blocked_masters = InMemoryMasterDataRepository(); _supplier(blocked_masters, "Blocked Mgmt", management=False)
    blocked_repo = InMemorySupplierRFQRepository()
    blocked_workflow = workflow.model_copy(update={"workflow_id":"blocked-workflow", "rfq_ids":["blocked-rfq"]})
    blocked_draft = draft.model_copy(update={"rfq_id":"blocked-rfq", "workflow_id":"blocked-workflow", "supplier_name":"Blocked Mgmt"})
    blocked_repo.save_workflow(blocked_workflow); blocked_repo.save_drafts([blocked_draft])
    blocked_actions = InMemoryAutomationActionRepository(); _sent_reminder(blocked_actions, blocked_draft)
    blocked = False
    try:
        record_supplier_escalation_evidence(
            repository=blocked_repo, action_repository=blocked_actions, rfq_id=blocked_draft.rfq_id,
            level="management", channel="phone", outcome="no_response",
            recorded_by="Regression Operator", escalated_at=NOW,
            master_data_repository=blocked_masters,
        )
    except SupplierEscalationEvidenceError:
        blocked = True
    check(blocked, "explicit supplier-master management prohibition overrides escalation recording")

    early_repo, _, early_draft = _rfq_fixture(); early_actions = InMemoryAutomationActionRepository()
    early_draft = early_draft.model_copy(update={"sent_at": NOW - timedelta(minutes=5)})
    early_repo.save_drafts([early_draft])
    early_blocked = False
    try:
        record_supplier_escalation_evidence(
            repository=early_repo, action_repository=early_actions, rfq_id=early_draft.rfq_id,
            level="operator", channel="phone", outcome="no_response",
            recorded_by="Regression Operator", escalated_at=NOW,
            master_data_repository=masters,
        )
    except SupplierEscalationEvidenceError:
        early_blocked = True
    check(
        early_blocked and not early_repo.list_escalation_evidence(early_draft.rfq_id),
        "ordinary contact before human-contact stage cannot be mislabeled as escalation evidence",
    )

    # Build explicit historical escalation denominators: phone 5/6, WhatsApp 2/6, management 4/6.
    for index in range(5):
        rfqs.save_escalation_evidence(SupplierEscalationEvidence(
            escalation_id=f"phone-{index}", rfq_id=draft.rfq_id,
            escalated_at=NOW - timedelta(days=20-index), level="operator", channel="phone",
            outcome="acknowledged_working", recorded_by="History Operator",
            trigger_state="human_contact_required",
        ))
    for index in range(6):
        rfqs.save_escalation_evidence(SupplierEscalationEvidence(
            escalation_id=f"wa-{index}", rfq_id=draft.rfq_id,
            escalated_at=NOW - timedelta(days=18-index), level="operator", channel="whatsapp",
            outcome="acknowledged_working" if index < 2 else "no_response",
            recorded_by="History Operator", trigger_state="human_contact_required",
        ))
    for index in range(5):
        rfqs.save_escalation_evidence(SupplierEscalationEvidence(
            escalation_id=f"mgmt-{index}", rfq_id=draft.rfq_id,
            escalated_at=NOW - timedelta(days=15-index), level="management", channel="phone",
            outcome="acknowledged_working" if index < 3 else "unreachable",
            recorded_by="History Manager", trigger_state="human_contact_required",
        ))

    facts = InMemoryLearningFactRepository()
    derived = derive_supplier_history_learning(
        supplier_id=supplier.supplier_id, master_repository=masters,
        supplier_repository=rfqs, learning_repository=facts,
        created_by="Regression", occurred_at=NOW + timedelta(minutes=10),
    )
    proposed = {item.fact_key: item for item in facts.list_all()}
    check(
        derived["escalation_evidence_count"] == 18
        and round(float(proposed["escalation.phone.ack_rate_percent"].value), 1) == 83.3
        and round(float(proposed["escalation.whatsapp.ack_rate_percent"].value), 1) == 33.3
        and round(float(proposed["escalation.management.ack_rate_percent"].value), 1) == 66.7
        and all(proposed[key].status == "proposed" for key in (
            "escalation.phone.ack_rate_percent", "escalation.whatsapp.ack_rate_percent",
            "escalation.management.ack_rate_percent",
        )),
        "explicit escalation history derives structured proposed success metrics with real denominators",
    )

    for key in (
        "escalation.phone.ack_rate_percent", "escalation.whatsapp.ack_rate_percent",
        "escalation.management.ack_rate_percent",
    ):
        confirm_learning_fact(
            repository=facts, fact_id=proposed[key].fact_id,
            reviewed_by="Regression Reviewer", review_note="Confirmed escalation history.",
            occurred_at=NOW + timedelta(minutes=11),
        )

    policy = build_supplier_operational_learning_policy(
        supplier=supplier, learning_repository=facts,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120,
        as_of=NOW + timedelta(minutes=12),
    )
    check(
        policy.preferred_escalation_channel_advisory == "phone"
        and policy.management_escalation_advisory
        and policy.contact_escalation_learning_applied,
        "confirmed escalation metrics create bounded phone and management advisories only",
    )

    nba_repo, nba_workflow, nba_draft = _rfq_fixture()
    human_plan = {"state":"human_contact_required", "reason":"no_response_after_reminder"}
    nba = build_supplier_next_best_action(
        draft=nba_draft, workflow=nba_workflow, reminder_plan=human_plan,
        supplier_repository=nba_repo, master_data_repository=masters,
        learning_fact_repository=facts, as_of=NOW + timedelta(minutes=15),
    )
    check(
        nba.action == "contact_supplier" and nba.channel == "phone"
        and nba.source == "confirmed_learning" and not nba.automatic_action_allowed,
        "next best action uses confirmed escalation history as an operator-only phone advisory",
    )

    nba_repo.save_escalation_evidence(SupplierEscalationEvidence(
        escalation_id="current-phone-fail", rfq_id=nba_draft.rfq_id,
        escalated_at=NOW + timedelta(minutes=16), level="operator", channel="phone",
        outcome="no_response", recorded_by="Current Operator", trigger_state="human_contact_required",
    ))
    alternate = build_supplier_next_best_action(
        draft=nba_draft, workflow=nba_workflow, reminder_plan=human_plan,
        supplier_repository=nba_repo, master_data_repository=masters,
        learning_fact_repository=facts, as_of=NOW + timedelta(minutes=17),
    )
    check(
        alternate.action == "contact_supplier" and alternate.channel == "whatsapp"
        and alternate.source == "current_evidence",
        "failed learned channel moves next best action to the remaining operator channel",
    )

    nba_repo.save_escalation_evidence(SupplierEscalationEvidence(
        escalation_id="current-wa-fail", rfq_id=nba_draft.rfq_id,
        escalated_at=NOW + timedelta(minutes=18), level="operator", channel="whatsapp",
        outcome="unreachable", recorded_by="Current Operator", trigger_state="human_contact_required",
    ))
    management = build_supplier_next_best_action(
        draft=nba_draft, workflow=nba_workflow, reminder_plan=human_plan,
        supplier_repository=nba_repo, master_data_repository=masters,
        learning_fact_repository=facts, as_of=NOW + timedelta(minutes=19),
    )
    check(
        management.action == "management_contact" and management.level == "management"
        and management.source == "confirmed_learning" and not management.secondary_release_allowed,
        "exhausted operator channels may recommend management contact but never secondary release",
    )

    nba_repo.save_escalation_evidence(SupplierEscalationEvidence(
        escalation_id="current-management-fail", rfq_id=nba_draft.rfq_id,
        escalated_at=NOW + timedelta(minutes=20), level="management", channel="phone",
        outcome="unreachable", recorded_by="Current Manager", trigger_state="human_contact_required",
    ))
    manual_review = build_supplier_next_best_action(
        draft=nba_draft, workflow=nba_workflow, reminder_plan=human_plan,
        supplier_repository=nba_repo, master_data_repository=masters,
        learning_fact_repository=facts, as_of=NOW + timedelta(minutes=21),
    )
    check(
        manual_review.action == "manual_relationship_review"
        and manual_review.source == "current_evidence",
        "failed management escalation ends in manual relationship review instead of automatic fallback",
    )

    with tempfile.TemporaryDirectory(prefix="minai-escalation-reg-") as directory:
        store = SQLitePilotStore(Path(directory) / "pilot.sqlite3", run_id="esc-reg", retention_days=365)
        sqlite_repo = SQLiteSupplierRFQRepository(store)
        sqlite_repo.save_escalation_evidence(SupplierEscalationEvidence(
            escalation_id="durable-esc", rfq_id="durable-rfq", escalated_at=NOW,
            level="operator", channel="phone", outcome="no_response",
            recorded_by="Regression Operator", trigger_state="human_contact_required",
        ))
        rebuilt = SQLiteSupplierRFQRepository(store)
        check(
            len(rebuilt.list_escalation_evidence("durable-rfq")) == 1,
            "supplier escalation evidence is durable in SQLite and survives repository reconstruction",
        )

    app_js = (Path(__file__).resolve().parents[2] / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        route_allowed("POST", "/supplier-rfqs/example/escalations")
        and not route_allowed("GET", "/supplier-rfqs/example/escalations")
        and "Sıradaki öneri:" in app_js and "/escalations`" in app_js
        and "management_supplier_contact" in app_js,
        "controlled pilot and browser expose explicit escalation evidence and next-best-action guidance only",
    )

    result = {"passes": passes, "failures": failures, "passed": not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier escalation intelligence regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    outcome = evaluate_supplier_escalation_intelligence_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
