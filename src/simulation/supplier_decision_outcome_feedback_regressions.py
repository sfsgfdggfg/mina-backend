from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.core.mina_job import MinaJob
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.models import Shipment, SupplierQuote
from src.core.operation_execution import OperationException, OperationExecutionSnapshot
from src.core.operation_execution_repository import InMemoryOperationExecutionRepository
from src.core.pilot_access import route_allowed
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_decision_outcome_service import (
    SupplierDecisionOutcomeConflictError,
    record_supplier_decision_outcome,
)
from src.core.supplier_quote_selection import SupplierQuoteSelectionDecision
from src.core.mina_job_service import MinaJobTransitionError

UTC=timezone.utc


def _fixture():
    mina=InMemoryMinaJobRepository(); cases=InMemoryQuoteCaseRepository(); ops=InMemoryOperationExecutionRepository()
    shipment=Shipment(customer_name="ACME", pickup_country="Türkiye", delivery_country="Germany", transport_mode="road", required_delivery_date="2026-09-10")
    decision=SupplierQuoteSelectionDecision(selected_supplier="Beta",engine_recommended_supplier="Alpha",override_applied=True,override_reason="Customer requested Beta.",override_reason_category="customer_preference",overridden_by="ops@example.com",selected_total_score=0.82,selection_reason="Override",rejected_alternatives=[])
    case=QuoteCase(shipment=shipment,mina_job_id="job-1",mina_code="MINA2026/1",supplier_quote_selection_decision=decision,supplier_quote=SupplierQuote(supplier_name="Beta",cost=2400,currency="EUR"))
    cases.save(case)
    job=MinaJob(job_id="job-1",mina_code="MINA2026/1",sequence_year=2026,sequence_number=1,lifecycle_version=2,job_kind="price_request",intake_channel="phone",manual_intake_id="manual-1",shipment=shipment,stage="completed",quote_case_id=case.case_id,opened_by="ops@example.com",opened_at=datetime(2026,9,1,tzinfo=UTC),updated_at=datetime(2026,9,11,tzinfo=UTC),closed_at=datetime(2026,9,11,tzinfo=UTC))
    mina.save(job)
    ops.save_snapshot(OperationExecutionSnapshot(job_id=job.job_id,mina_code=job.mina_code,delivered_at=datetime(2026,9,11,10,tzinfo=UTC),updated_at=datetime(2026,9,11,11,tzinfo=UTC),updated_by="ops@example.com"))
    for i,(kind,impact) in enumerate((("delivery","actual_delay"),("damage","deviation")),start=1):
        incident=OperationException(entry_id=f"inc-{i}",job_id=job.job_id,mina_code=job.mina_code,stage_at_report="delivery",exception_type=kind,impact_level=impact,status="resolved",cause="test",source_type="operator",reported_at=datetime(2026,9,10,tzinfo=UTC),created_at=datetime(2026,9,10,tzinfo=UTC),created_by="ops@example.com",updated_at=datetime(2026,9,11,tzinfo=UTC),updated_by="ops@example.com",resolved_at=datetime(2026,9,11,tzinfo=UTC),resolved_by="ops@example.com",resolution_note="resolved")
        ops.create_exception(incident)
    return mina,cases,ops,job,case


def evaluate_supplier_decision_outcome_feedback_regressions() -> dict:
    passes=[]; failures=[]
    def check(cond,label):(passes if cond else failures).append(label)
    mina,cases,ops,job,case=_fixture()
    feedback=record_supplier_decision_outcome(mina_repository=mina,quote_case_repository=cases,execution_repository=ops,job_id=job.job_id,entry_id="outcome-1",overall_outcome="problematic",communication_quality="poor",would_choose_again="no",recorded_by="ops@example.com",note="Late delivery and damage.")
    check(feedback.supplier_name=="Beta" and feedback.engine_recommended_supplier=="Alpha" and feedback.override_applied and feedback.override_reason_category=="customer_preference","final outcome preserves selected supplier, MINAI recommendation and override category")
    check(feedback.on_time_delivery is False and feedback.actual_delay_count==1 and feedback.damage_exception_count==1 and feedback.operation_exception_count==2,"objective delivery delay and damage evidence is derived from completed operation records")
    check(cases.get(case.case_id).supplier_decision_outcome_feedback.feedback_id==feedback.feedback_id,"outcome feedback is durable on the quote case")
    replay=record_supplier_decision_outcome(mina_repository=mina,quote_case_repository=cases,execution_repository=ops,job_id=job.job_id,entry_id="outcome-1",overall_outcome="problematic",communication_quality="poor",would_choose_again="no",recorded_by="ops@example.com",note="Late delivery and damage.")
    check(replay.feedback_id==feedback.feedback_id,"same outcome entry is idempotent")
    try:
        record_supplier_decision_outcome(mina_repository=mina,quote_case_repository=cases,execution_repository=ops,job_id=job.job_id,entry_id="outcome-2",overall_outcome="successful",communication_quality="good",would_choose_again="yes",recorded_by="ops@example.com")
        conflict=False
    except SupplierDecisionOutcomeConflictError: conflict=True
    check(conflict,"second conflicting final outcome is rejected")
    mina2,cases2,ops2,job2,_=_fixture(); mina2.save(job2.model_copy(update={"stage":"closing_review","closed_at":None}))
    try:
        record_supplier_decision_outcome(mina_repository=mina2,quote_case_repository=cases2,execution_repository=ops2,job_id=job2.job_id,entry_id="early",overall_outcome="acceptable",communication_quality="acceptable",would_choose_again="unsure",recorded_by="ops@example.com")
        early=False
    except MinaJobTransitionError: early=True
    check(early,"outcome feedback cannot be recorded before lifecycle-v2 completion")
    check(route_allowed("POST","/mina-jobs/job-1/supplier-decision-outcome"),"controlled pilot explicitly admits final supplier outcome recording")
    ui=Path("ui/web_shell/app.js").read_text(encoding="utf-8"); report=Path("src/core/reporting_read_model.py").read_text(encoding="utf-8")
    check("Supplier Karar Sonucunu Kaydet" in ui and "successful_outcome_percent" in report and "choose_again_yes_percent" in report,"browser and supplier reporting expose outcome feedback without creating learning authority")
    result={"passes":passes,"failures":failures,"passed":not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier decision outcome feedback regressions:","PASS" if not failures else "FAIL")
    return result

if __name__=="__main__":
    outcome=evaluate_supplier_decision_outcome_feedback_regressions(); raise SystemExit(0 if outcome["passed"] else 1)
