from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.mail import InboundMailEnvelope
from src.core.models import Package
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.sqlite_repositories import (
    SQLiteExtractionProposalRepository,
    SQLiteMinaJobRepository,
    SQLiteSupplierRFQRepository,
)
from src.workflow.customer_clarification import apply_customer_clarification
from src.workflow.extraction_confirmation import (
    confirm_extraction_proposal,
    create_extraction_proposal,
    resume_confirmed_extraction,
)


def _snapshot() -> ShipmentProposalSnapshot:
    return ShipmentProposalSnapshot(
        customer_name="Synthetic Clarification Customer",
        pickup_country="Türkiye", pickup_city="Adana",
        delivery_country="Almanya", delivery_city="Hamburg",
        delivery_postcode=None, commodity="Tekstil", gross_weight_kg=20000,
        service_type="FTL", transport_mode="road", equipment_type="Tenteli",
        cargo_ready_date=None, is_adr=False, is_temperature_controlled=False,
        is_high_value=False,
        packages=[Package(package_type="pallet", quantity=20, length_cm=120,
                          width_cm=80, height_cm=150, weight_kg=1000)],
    )


def evaluate_customer_clarification_progression_regressions() -> dict:
    failures: list[str] = []
    with TemporaryDirectory(prefix="minai-customer-clarification-") as temp_dir:
        db_path = Path(temp_dir) / "pilot.db"
        store = SQLitePilotStore(db_path, run_id="customer-clarification-a")
        proposals = SQLiteExtractionProposalRepository(store)
        jobs = SQLiteMinaJobRepository(store)
        rfqs = SQLiteSupplierRFQRepository(store)
        approvals = InMemoryQuoteApprovalRepository()
        cases = InMemoryQuoteCaseRepository()
        proposal = create_extraction_proposal(
            mail=InboundMailEnvelope(
                external_message_id="clarification-inquiry-1",
                provider_name="regression-mail", mailbox_id="ops@example.invalid",
                sender_address="customer@example.invalid",
                recipient_addresses=["ops@example.invalid"],
                subject="Adana Hamburg fiyat talebi",
                body_text="20 palet tekstil için fiyat rica ederiz.",
                received_at=datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc),
                source="email",
            ),
            proposed_shipment=_snapshot(), repository=proposals,
        )
        confirmed = confirm_extraction_proposal(
            repository=proposals, proposal_id=proposal.proposal_id,
            operator_identity="Regression Operator", mina_job_repository=jobs,
            confirmed_at=datetime(2026, 9, 17, 8, 5, tzinfo=timezone.utc),
        )
        initial = resume_confirmed_extraction(
            repository=proposals, proposal_id=proposal.proposal_id,
            rfq_repository=rfqs, approval_repository=approvals,
            quote_case_repository=cases, mina_job_repository=jobs,
        )
        job = jobs.get(confirmed.mina_job_id)
        if initial.get("result_type") != "clarification" or job is None:
            failures.append("initial incomplete inquiry did not stop at clarification")
        else:
            original_code = job.mina_code
            extraction_history_before_clarification = proposals.get(proposal.proposal_id)
            partial = apply_customer_clarification(
                mina_repository=jobs, proposal_repository=proposals,
                rfq_repository=rfqs, approval_repository=approvals,
                quote_case_repository=cases, job_id=job.job_id,
                actor="Regression Operator",
                updates={"cargo_ready_date": "2026-09-20"},
                source_channel="email", source_reference="customer-reply-1",
                note="Customer supplied the loading date.",
            )
            partial_job = jobs.get(job.job_id)
            if (
                partial.get("result_type") != "clarification"
                or partial_job is None or partial_job.mina_code != original_code
                or partial_job.stage != "inquiry_confirmed"
                or rfqs.list_drafts()
            ):
                failures.append("partial clarification did not stay safely blocked on the same MINA job")

            before_forbidden = partial_job
            protected_updates = [
                {"is_adr": True},
                {"adr_class": "3"},
                {"temperature_requirement": "+4C"},
                {"commodity_attributes": {"adr status": True}},
                {"customer_name": "Different Customer"},
            ]
            for index, protected_update in enumerate(protected_updates, start=1):
                try:
                    apply_customer_clarification(
                        mina_repository=jobs, proposal_repository=proposals,
                        rfq_repository=rfqs, approval_repository=approvals,
                        quote_case_repository=cases, job_id=job.job_id,
                        actor="Regression Operator", updates=protected_update,
                        source_channel="email",
                        source_reference=f"unsafe-reply-{index}",
                    )
                except ValueError:
                    pass
                else:
                    failures.append(
                        "customer clarification changed protected safety or identity authority"
                    )
            if jobs.get(job.job_id) != before_forbidden:
                failures.append("rejected clarification mutated the MINA job")

            ready = apply_customer_clarification(
                mina_repository=jobs, proposal_repository=proposals,
                rfq_repository=rfqs, approval_repository=approvals,
                quote_case_repository=cases, job_id=job.job_id,
                actor="Regression Operator", updates={"delivery_postcode": "20095"},
                source_channel="email", source_reference="customer-reply-2",
                note="Customer supplied the delivery postcode.",
            )
            ready_job = jobs.get(job.job_id)
            if (
                ready.get("result_type") != "supplier_rfq_approval_required"
                or ready_job is None or ready_job.mina_code != original_code
                or ready_job.stage != "pricing"
                or not ready_job.supplier_rfq_workflow_id
                or not rfqs.list_drafts()
            ):
                failures.append("complete clarification did not progress the same MINA job to RFQ approval")

            extraction_history_after_clarification = proposals.get(proposal.proposal_id)
            if extraction_history_before_clarification is None:
                failures.append("confirmed extraction history was missing before clarification")
            elif extraction_history_after_clarification != extraction_history_before_clarification:
                failures.append("customer clarification rewrote confirmed extraction history")

            clarification_events = [
                item for item in jobs.list_events(job.job_id)
                if item.event_type == "customer_clarification_applied"
            ]
            if len(clarification_events) != 2:
                failures.append("customer clarification audit events were not preserved")

            rebuilt_store = SQLitePilotStore(db_path, run_id="customer-clarification-b")
            rebuilt_jobs = SQLiteMinaJobRepository(rebuilt_store)
            rebuilt_rfqs = SQLiteSupplierRFQRepository(rebuilt_store)
            rebuilt = rebuilt_jobs.get(job.job_id)
            if (
                rebuilt is None or rebuilt.mina_code != original_code
                or rebuilt.stage != "pricing" or not rebuilt.supplier_rfq_workflow_id
                or rebuilt_rfqs.get_workflow(rebuilt.supplier_rfq_workflow_id) is None
            ):
                failures.append("clarification progression did not survive repository restart")

    root = Path(__file__).resolve().parents[2]
    api_text = (root / "src" / "api.py").read_text(encoding="utf-8")
    ui_text = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    if not route_allowed("POST", "/mina-jobs/job-1/customer-clarification"):
        failures.append("customer clarification route is not pilot-allowlisted")
    if "/customer-clarification" not in api_text or "/customer-clarification" not in ui_text:
        failures.append("customer clarification API/UI contract is not wired")
    return {
        "name": "Customer clarification progression",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_customer_clarification_progression_regressions()
    print("PASS" if result["passed"] else "FAIL")
    for failure in result["failures"]:
        print("FAIL", failure)
    raise SystemExit(0 if result["passed"] else 1)
