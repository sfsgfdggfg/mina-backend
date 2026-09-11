from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from src.core.customer_loss_feedback import (
    LossFeedbackConflictError,
    build_loss_feedback_view,
    record_loss_feedback,
)
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import create_manual_mina_job, transition_mina_job_stage
from src.core.models import Shipment
from src.core.operation_execution_repository import InMemoryOperationExecutionRepository
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.reporting_read_model import build_reporting_read_model
from src.core.sqlite_repositories import SQLiteMinaJobRepository
from src.core.supplier_price_repository import InMemorySupplierPriceRepository
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository

NOW = datetime(2026, 9, 11, 16, 45, tzinfo=timezone.utc)


def _shipment(name: str = "Loss Customer") -> Shipment:
    return Shipment(
        customer_name=name, transport_mode="road", pickup_country="Türkiye",
        pickup_city="Adana", delivery_country="Germany", delivery_city="Munich",
        commodity="Textile", equipment_type="Tenteli", cargo_ready_date="2026-09-20",
    )


def _lost_job(repository, *, intake_id: str, reason: str = "Customer did not proceed."):
    job = create_manual_mina_job(
        repository=repository, manual_intake_id=intake_id, intake_channel="phone",
        job_kind="price_request", shipment=_shipment(), opened_by="Regression",
        opened_at=NOW - timedelta(days=2),
    )
    return transition_mina_job_stage(
        repository=repository, mina_code=job.mina_code, target_stage="lost",
        actor="Regression", reason=reason, occurred_at=NOW - timedelta(days=1),
    )


def evaluate_customer_loss_feedback_regressions():
    passes: list[str] = []
    failures: list[str] = []
    def check(condition, label): (passes if condition else failures).append(label)

    jobs = InMemoryMinaJobRepository()
    legacy = _lost_job(jobs, intake_id="legacy-loss", reason="Price may have been high.")
    legacy_view = build_loss_feedback_view(jobs, job_id=legacy.job_id)
    check(
        legacy_view["legacy_stage_reason"] == "Price may have been high."
        and legacy_view["current"] is None,
        "legacy free-text loss reason remains visible but is never auto-classified as structured evidence",
    )

    first = record_loss_feedback(
        repository=jobs, job_id=legacy.job_id, entry_id="loss-feedback-1",
        category="price", evidence_basis="operator_assessment", source_channel="phone",
        note="Operator assessment after follow-up call; customer did not state a target price.",
        recorded_by="Regression", occurred_at=NOW,
    )
    retry = record_loss_feedback(
        repository=jobs, job_id=legacy.job_id, entry_id="loss-feedback-1",
        category="price", evidence_basis="operator_assessment", source_channel="phone",
        note="Operator assessment after follow-up call; customer did not state a target price.",
        recorded_by="Regression", occurred_at=NOW + timedelta(minutes=1),
    )
    check(first.feedback_id == retry.feedback_id, "identical loss-feedback retry is idempotent by entry_id")

    try:
        record_loss_feedback(
            repository=jobs, job_id=legacy.job_id, entry_id="loss-feedback-1",
            category="transit_time", evidence_basis="operator_assessment", source_channel="phone",
            note="Conflicting retry.", recorded_by="Regression", occurred_at=NOW + timedelta(minutes=2),
        )
        conflicting_retry_blocked = False
    except LossFeedbackConflictError:
        conflicting_retry_blocked = True
    check(conflicting_retry_blocked, "conflicting retry with the same entry_id fails closed")

    try:
        record_loss_feedback(
            repository=jobs, job_id=legacy.job_id, entry_id="loss-feedback-2",
            category="competitor_selected", evidence_basis="customer_explicit", source_channel="email",
            note="Customer later confirmed a competitor was selected.", competitor_name="Carrier X",
            recorded_by="Regression", occurred_at=NOW + timedelta(minutes=3),
        )
        revision_without_supersede_blocked = False
    except LossFeedbackConflictError:
        revision_without_supersede_blocked = True
    revised = record_loss_feedback(
        repository=jobs, job_id=legacy.job_id, entry_id="loss-feedback-2",
        category="competitor_selected", evidence_basis="customer_explicit", source_channel="email",
        note="Customer later confirmed a competitor was selected.", competitor_name="Carrier X",
        customer_stated_target_price=2150, currency="eur",
        supersedes_feedback_id=first.feedback_id, recorded_by="Regression",
        occurred_at=NOW + timedelta(minutes=4),
    )
    revised_view = build_loss_feedback_view(jobs, job_id=legacy.job_id)
    check(
        revision_without_supersede_blocked
        and revised_view["structured_feedback_count"] == 2
        and revised_view["current"]["feedback_id"] == revised.feedback_id
        and revised_view["current"]["currency"] == "EUR",
        "later customer evidence explicitly supersedes rather than overwrites the prior audit record",
    )

    try:
        record_loss_feedback(
            repository=jobs, job_id=legacy.job_id, entry_id="loss-feedback-3",
            category="price", evidence_basis="operator_assessment", source_channel="internal",
            note="Operator guessed a target.", customer_stated_target_price=2000, currency="EUR",
            supersedes_feedback_id=revised.feedback_id, recorded_by="Regression",
            occurred_at=NOW + timedelta(minutes=5),
        )
        inferred_target_blocked = False
    except ValueError:
        inferred_target_blocked = True
    check(inferred_target_blocked, "target price evidence is accepted only when explicitly stated by the customer")

    open_job = create_manual_mina_job(
        repository=jobs, manual_intake_id="open-job", intake_channel="phone",
        job_kind="price_request", shipment=_shipment("Open Customer"), opened_by="Regression",
        opened_at=NOW,
    )
    try:
        record_loss_feedback(
            repository=jobs, job_id=open_job.job_id, entry_id="not-lost",
            category="unknown", evidence_basis="unknown", source_channel="unknown",
            note="Not a lost job.", recorded_by="Regression", occurred_at=NOW,
        )
        non_lost_blocked = False
    except LossFeedbackConflictError:
        non_lost_blocked = True
    check(non_lost_blocked, "structured loss feedback cannot be attached to a job that is not lost")

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "loss-feedback.sqlite3", retention_days=365)
        durable = SQLiteMinaJobRepository(store)
        durable_job = _lost_job(durable, intake_id="durable-loss")
        saved = record_loss_feedback(
            repository=durable, job_id=durable_job.job_id, entry_id="durable-feedback",
            category="customer_cancelled", evidence_basis="customer_explicit", source_channel="whatsapp",
            note="Customer explicitly cancelled the shipment.", recorded_by="Regression", occurred_at=NOW,
        )
        reopened = SQLiteMinaJobRepository(store)
        durable_view = build_loss_feedback_view(reopened, job_id=durable_job.job_id)
        check(
            durable_view["current"]["feedback_id"] == saved.feedback_id
            and durable_view["current"]["category"] == "customer_cancelled",
            "structured loss feedback survives durable SQLite repository reconstruction",
        )

    report = build_reporting_read_model(
        mina_repository=jobs,
        quote_case_repository=InMemoryQuoteCaseRepository(),
        supplier_rfq_repository=InMemorySupplierRFQRepository(),
        supplier_price_repository=InMemorySupplierPriceRepository(),
        operation_execution_repository=InMemoryOperationExecutionRepository(),
        master_data_repository=InMemoryMasterDataRepository(),
        learning_fact_repository=InMemoryLearningFactRepository(),
        as_of=NOW + timedelta(minutes=10),
    )
    loss_report = report["loss_feedback"]
    check(
        loss_report["summary"]["lost_job_count"] == 1
        and loss_report["summary"]["structured_feedback_count"] == 1
        and loss_report["categories"][0]["category"] == "competitor_selected",
        "reporting uses only the current structured feedback record and exposes coverage separately",
    )
    check(
        loss_report["summary"]["customer_explicit_feedback_count"] == 1
        and loss_report["summary"]["target_price_evidence_count"] == 1,
        "reporting preserves explicit customer evidence quality without creating pricing authority",
    )

    check(
        route_allowed("GET", "/mina-jobs/job-1/loss-feedback")
        and route_allowed("POST", "/mina-jobs/job-1/loss-feedback")
        and route_allowed("GET", "/reports/loss_feedback"),
        "controlled pilot explicitly admits loss-feedback capture and reporting readout",
    )
    ui = Path("ui/web_shell/app.js").read_text(encoding="utf-8")
    check(
        "Kayıp Nedeni / Müşteri Geri Bildirimi" in ui
        and "/loss-feedback" in ui and "/stage" not in ui,
        "browser captures loss evidence without inventing generic stage-transition authority",
    )
    quote_learning = Path("src/core/customer_quote_acceptance_learning.py").read_text(encoding="utf-8")
    check(
        "customer_loss_feedback" not in quote_learning,
        "loss feedback capture remains evidence-only and does not silently enter quote acceptance learning",
    )

    result = {"passed": not failures, "passes": passes, "failures": failures}
    for label in passes: print("PASS", label)
    for label in failures: print("FAIL", label)
    print("\nCustomer loss feedback regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    result = evaluate_customer_loss_feedback_regressions()
    raise SystemExit(0 if result["passed"] else 1)
