from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.mina_job import MinaJob
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import create_manual_mina_job, link_mina_job_workflow
from src.core.mina_job_view import build_mina_job_detail
from src.core.models import Shipment
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQWorkflow, SupplierSelectionExplanation
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.supplier_selection import select_suppliers_for_shipment
from src.core.supplier_selection_feedback import SupplierSelectionFeedbackEvidence
from src.core.supplier_selection_feedback_repository import (
    InMemorySupplierSelectionFeedbackRepository, SQLiteSupplierSelectionFeedbackRepository,
    SupplierSelectionFeedbackIdempotencyConflictError,
)
from src.core.supplier_selection_feedback_service import record_supplier_selection_feedback

NOW = datetime(2026, 9, 11, 11, 0, tzinfo=timezone.utc)


def _shipment(country: str = "Germany") -> Shipment:
    return Shipment(
        customer_name="Synthetic", transport_mode="road", pickup_country="Türkiye",
        delivery_country=country, service_type="FTL", equipment_type="Tenteli",
    )


def _explanation(rank: int = 1) -> SupplierSelectionExplanation:
    return SupplierSelectionExplanation(
        selection_rank=rank, base_total_score=0.75, total_score=0.78,
        route_score=1, equipment_score=1, risk_score=0.7, price_score=0.6, speed_score=0.6,
        global_learning_adjustment=0.03, context_learning_adjustment=0,
        combined_learning_adjustment=0.03, learning_adjustment_capped=False,
        global_learning_fact_ids=["fact-global"], reason="Synthetic selection explanation.",
        selection_strategy="strict eligibility then bounded scoring", data_source="synthetic",
    )


def _job_with_rfq(mina, rfqs, *, intake: str, supplier: str, rank: int = 1):
    job = create_manual_mina_job(
        repository=mina, manual_intake_id=intake, intake_channel="other", job_kind="price_request",
        shipment=_shipment(), opened_by="Regression Operator", opened_at=NOW,
    )
    workflow = SupplierRFQWorkflow(
        workflow_id=f"wf-{intake}", shipment=job.shipment, mina_job_id=job.job_id, mina_code=job.mina_code,
    )
    draft = SupplierRFQDraft(
        rfq_id=f"rfq-{intake}", workflow_id=workflow.workflow_id, supplier_name=supplier, priority=rank,
        recipient_email="supplier@example.invalid", supplier_role="primary", dispatch_tier="primary",
        selection_explanation=_explanation(rank), subject="RFQ", body="RFQ",
    )
    rfqs.save_workflow(workflow); rfqs.save_drafts([draft])
    link_mina_job_workflow(
        repository=mina, job_id=job.job_id, workflow_id=workflow.workflow_id,
        result_type="supplier_rfq_approval_required", occurred_at=NOW + timedelta(seconds=1),
    )
    return mina.get(job.job_id), draft


def evaluate_supplier_selection_feedback_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    mina = InMemoryMinaJobRepository(); rfqs = InMemorySupplierRFQRepository()
    feedback = InMemorySupplierSelectionFeedbackRepository()
    job, draft = _job_with_rfq(mina, rfqs, intake="feedback-main", supplier="Context Primary")
    saved = record_supplier_selection_feedback(
        feedback_repository=feedback, mina_repository=mina, supplier_repository=rfqs,
        job_id=job.job_id, rfq_id=draft.rfq_id, entry_id="feedback:1", verdict="disagree",
        reason_code="relationship_context_missing", note="Operator knows a temporary relationship issue.",
        recorded_by="Regression Operator", recorded_at=NOW + timedelta(minutes=1),
    )
    events = [e for e in mina.list_events(job.job_id) if e.event_type == "supplier_selection_feedback_recorded"]
    check(
        saved.supplier_name == draft.supplier_name and saved.selection_priority == 1
        and len(saved.selection_snapshot_sha256) == 64 and len(events) == 1
        and events[0].metadata["reason_code"] == "relationship_context_missing",
        "operator disagreement is durable evidence tied to the exact supplier selection snapshot and MINA timeline",
    )

    retry = record_supplier_selection_feedback(
        feedback_repository=feedback, mina_repository=mina, supplier_repository=rfqs,
        job_id=job.job_id, rfq_id=draft.rfq_id, entry_id="feedback:1", verdict="disagree",
        reason_code="relationship_context_missing", note="Operator knows a temporary relationship issue.",
        recorded_by="Regression Operator", recorded_at=NOW + timedelta(minutes=2),
    )
    retry_events = [e for e in mina.list_events(job.job_id) if e.event_type == "supplier_selection_feedback_recorded"]
    check(
        retry.feedback_id == saved.feedback_id and len(retry_events) == 1,
        "selection feedback retries are idempotent and do not duplicate timeline evidence",
    )

    conflict = False
    try:
        record_supplier_selection_feedback(
            feedback_repository=feedback, mina_repository=mina, supplier_repository=rfqs,
            job_id=job.job_id, rfq_id=draft.rfq_id, entry_id="feedback:1", verdict="agree",
            reason_code="selection_looks_right", note=None, recorded_by="Regression Operator",
            recorded_at=NOW + timedelta(minutes=3),
        )
    except SupplierSelectionFeedbackIdempotencyConflictError:
        conflict = True
    check(conflict, "reusing a feedback entry id with different evidence fails closed")

    invalid_other = False
    try:
        record_supplier_selection_feedback(
            feedback_repository=feedback, mina_repository=mina, supplier_repository=rfqs,
            job_id=job.job_id, rfq_id=draft.rfq_id, entry_id="feedback:other", verdict="disagree",
            reason_code="other", note=None, recorded_by="Regression Operator", recorded_at=NOW,
        )
    except ValueError:
        invalid_other = True
    check(invalid_other, "unstructured other feedback requires an explanatory note")

    job2, draft2 = _job_with_rfq(mina, rfqs, intake="feedback-other-job", supplier="Other Primary")
    cross_job = False
    try:
        record_supplier_selection_feedback(
            feedback_repository=feedback, mina_repository=mina, supplier_repository=rfqs,
            job_id=job.job_id, rfq_id=draft2.rfq_id, entry_id="feedback:cross", verdict="agree",
            reason_code="selection_looks_right", note=None, recorded_by="Regression Operator", recorded_at=NOW,
        )
    except ValueError:
        cross_job = True
    check(cross_job, "feedback cannot be attached to an RFQ from another MINA job workflow")

    closed = MinaJob.model_validate(job.model_copy(update={
        "stage": "cancelled", "closed_at": NOW + timedelta(minutes=5),
        "updated_at": NOW + timedelta(minutes=5),
    }).model_dump())
    mina.save(closed)
    closed_blocked = False
    try:
        record_supplier_selection_feedback(
            feedback_repository=feedback, mina_repository=mina, supplier_repository=rfqs,
            job_id=job.job_id, rfq_id=draft.rfq_id, entry_id="feedback:closed", verdict="agree",
            reason_code="selection_looks_right", note=None, recorded_by="Regression Operator", recorded_at=NOW + timedelta(minutes=6),
        )
    except ValueError:
        closed_blocked = True
    check(closed_blocked, "closed MINA jobs reject new supplier selection feedback mutations")

    capabilities = [
        {"supplier_name":"Alpha","role":"primary","countries":["Germany"],"route_regions":["international"],"service_types":["FTL"],"equipment_types":["Tenteli"],"reliability_score":.8,"price_score":.8,"speed_score":.8,"notes":"reg"},
        {"supplier_name":"Beta","role":"primary","countries":["Germany"],"route_regions":["international"],"service_types":["FTL"],"equipment_types":["Tenteli"],"reliability_score":.7,"price_score":.7,"speed_score":.7,"notes":"reg"},
    ]
    before = select_suppliers_for_shipment(
        _shipment(), equipment_decision={"selected_equipment":"Tenteli"}, risk_assessment={"risk_level":"green"},
        supplier_capabilities=capabilities, max_suppliers=2,
    )
    after = select_suppliers_for_shipment(
        _shipment(), equipment_decision={"selected_equipment":"Tenteli"}, risk_assessment={"risk_level":"green"},
        supplier_capabilities=capabilities, max_suppliers=2,
    )
    check(
        before["selected_suppliers"] == after["selected_suppliers"],
        "selection feedback is evidence-only and has zero direct ranking or eligibility authority",
    )

    open_job, open_draft = _job_with_rfq(mina, rfqs, intake="feedback-view", supplier="View Primary")
    record_supplier_selection_feedback(
        feedback_repository=feedback, mina_repository=mina, supplier_repository=rfqs,
        job_id=open_job.job_id, rfq_id=open_draft.rfq_id, entry_id="feedback:view", verdict="agree",
        reason_code="selection_looks_right", note=None, recorded_by="Regression Operator", recorded_at=NOW + timedelta(minutes=7),
    )
    view = build_mina_job_detail(
        repository=mina, supplier_repository=rfqs, quote_case_repository=InMemoryQuoteCaseRepository(),
        action_repository=InMemoryAutomationActionRepository(), selection_feedback_repository=feedback,
        job_id=open_job.job_id, now=NOW + timedelta(minutes=8),
    )
    row = view["suppliers"][0]
    check(
        row["selection_feedback_allowed"] is True and len(row["selection_feedback"]) == 1
        and row["selection_feedback"][0]["verdict"] == "agree",
        "MINA job read model exposes durable selection feedback beside the original explanation snapshot",
    )

    with tempfile.TemporaryDirectory() as td:
        store = SQLitePilotStore(Path(td) / "feedback.sqlite3")
        durable = SQLiteSupplierSelectionFeedbackRepository(store)
        direct = SupplierSelectionFeedbackEvidence(
            entry_id="durable-feedback", mina_job_id=open_job.job_id, mina_code=open_job.mina_code,
            workflow_id=open_draft.workflow_id, rfq_id=open_draft.rfq_id, supplier_name=open_draft.supplier_name,
            selection_priority=1, verdict="disagree", reason_code="temporary_supplier_issue",
            note="Temporary issue", selection_snapshot_sha256="a" * 64,
            recorded_by="Regression Operator", recorded_at=NOW,
        )
        durable.create(direct)
        reconstructed = SQLiteSupplierSelectionFeedbackRepository(SQLitePilotStore(Path(td) / "feedback.sqlite3"))
        recovered = reconstructed.find_by_entry_id("durable-feedback")
    check(
        recovered is not None and recovered.feedback_id == direct.feedback_id and recovered.reason_code == "temporary_supplier_issue",
        "supplier selection feedback survives durable SQLite repository reconstruction",
    )

    check(
        route_allowed("POST", f"/mina-jobs/{open_job.job_id}/supplier-rfqs/{open_draft.rfq_id}/selection-feedback"),
        "controlled pilot admits the authenticated selection feedback endpoint",
    )

    ui = Path("ui/web_shell/app.js").read_text()
    check(
        "Sıralamaya Katılıyorum" in ui and "Sıralamaya Katılmıyorum" in ui
        and "selection-feedback" in ui,
        "browser exposes explicit agree/disagree selection review without hidden automatic learning",
    )

    result={"passes":passes,"failures":failures,"passed":not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier selection feedback regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    outcome=evaluate_supplier_selection_feedback_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
