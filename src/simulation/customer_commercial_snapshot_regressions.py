from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.customer_commercial_context import build_customer_commercial_context
from src.core.customer_quote_acceptance_policy import ACCEPTED_FINAL_PRICE_MEDIAN_KEY, QUOTE_ACCEPTANCE_RATE_KEY
from src.core.customer_quote_context import customer_quote_context_key
from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact, create_learning_fact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_view import build_mina_job_detail
from src.core.models import CustomerQuote, QuoteDraft, Shipment, SupplierQuote
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteQuoteApprovalRepository
from src.core.quote_revision_service import revise_quote_case
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository

NOW = datetime(2026, 9, 11, 19, 10, tzinfo=timezone.utc)


def _shipment() -> Shipment:
    return Shipment(
        customer_name="Snapshot Customer",
        transport_mode="road",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Germany",
        delivery_city="Munich",
        equipment_type="Tenteli",
        commodity="Textile",
    )


def _confirmed_fact(*, facts, masters, customer, key, value, unit, context=None, suffix, at=NOW, supersedes=None):
    fact = create_learning_fact(
        repository=facts,
        entry_id=f"commercial-snapshot-{suffix}",
        subject_type="customer",
        subject_id=customer.customer_id,
        subject_label=customer.customer_name,
        fact_key=key,
        context_key=context,
        value=value,
        value_unit=unit,
        confidence=0.95,
        source_type="manual",
        evidence=[LearningEvidence(
            source_type="manual",
            source_reference=f"commercial-snapshot-evidence-{suffix}",
            observed_at=at - timedelta(minutes=1),
            summary="Bounded historical commercial observation for snapshot regression.",
        )],
        supersedes_fact_id=supersedes,
        created_by="Regression",
        occurred_at=at,
        master_repository=masters,
    )
    return confirm_learning_fact(
        repository=facts,
        fact_id=fact.fact_id,
        reviewed_by="Reviewer",
        review_note="Confirm advisory snapshot evidence only.",
        occurred_at=at + timedelta(seconds=1),
    )


def evaluate_customer_commercial_snapshot_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository()
    facts = InMemoryLearningFactRepository()
    approvals = InMemoryQuoteApprovalRepository()
    cases = InMemoryQuoteCaseRepository()
    customer = create_customer_master(
        repository=masters,
        entry_id="commercial-snapshot-customer",
        customer_name="Snapshot Customer",
        updated_by="Regression",
        created_at=NOW - timedelta(days=100),
    )
    shipment = _shipment()
    supplier_quote = SupplierQuote(
        supplier_name="Snapshot Carrier", cost=2000, currency="EUR",
        transit_time="5-7 days", equipment_type="Tenteli",
    )
    customer_quote = CustomerQuote(
        supplier_cost=2000, markup_type="percentage", markup_value=15,
        final_price=2300, currency="EUR",
    )
    quote_draft = QuoteDraft(subject="Munich quote", body="Offer: 2300 EUR. Transit 5-7 days.")
    context_key = customer_quote_context_key(shipment, currency="EUR")

    _confirmed_fact(
        facts=facts, masters=masters, customer=customer,
        key=QUOTE_ACCEPTANCE_RATE_KEY, value=60, unit="percent", suffix="rate-v1",
    )
    old_price = _confirmed_fact(
        facts=facts, masters=masters, customer=customer,
        key=ACCEPTED_FINAL_PRICE_MEDIAN_KEY, value=2200, unit="EUR",
        context=context_key, suffix="price-v1",
    )

    base_case = QuoteCase(
        shipment=shipment, supplier_quote=supplier_quote,
        customer_quote=customer_quote, quote_draft=quote_draft,
    )
    first_context = build_customer_commercial_context(
        quote_case=base_case, master_data_repository=masters,
        learning_fact_repository=facts, as_of=NOW + timedelta(minutes=1),
    )
    first_approval = QuoteApproval(
        quote_snapshot=QuoteApprovalSnapshot.from_quote(
            supplier_quote=supplier_quote, customer_quote=customer_quote, quote_draft=quote_draft,
        ),
        customer_commercial_context_snapshot=first_context,
    )
    quote_case = base_case.model_copy(update={"quote_approval": first_approval})
    approvals.save(first_approval)
    cases.save(quote_case)

    check(
        first_approval.customer_commercial_context_snapshot is not None
        and first_approval.customer_commercial_context_snapshot.accepted_final_price_median.value == 2200
        and first_approval.customer_commercial_context_snapshot.observed_acceptance_rate.value == 60,
        "quote approval freezes the customer commercial advisory visible at creation time",
    )

    replacement = _confirmed_fact(
        facts=facts, masters=masters, customer=customer,
        key=ACCEPTED_FINAL_PRICE_MEDIAN_KEY, value=2400, unit="EUR",
        context=context_key, suffix="price-v2", at=NOW + timedelta(minutes=2),
        supersedes=old_price.fact_id,
    )
    current_context = build_customer_commercial_context(
        quote_case=quote_case, master_data_repository=masters,
        learning_fact_repository=facts, as_of=NOW + timedelta(minutes=3),
    )
    durable_first = approvals.get(first_approval.approval_id)
    check(
        current_context.accepted_final_price_median.value == 2400
        and current_context.accepted_final_price_median.fact_id == replacement.fact_id
        and durable_first.customer_commercial_context_snapshot.accepted_final_price_median.value == 2200
        and durable_first.customer_commercial_context_snapshot.accepted_final_price_median.fact_id == old_price.fact_id,
        "later reviewed learning cannot rewrite an existing quote approval commercial snapshot",
    )

    revised = revise_quote_case(
        quote_case_repository=cases,
        approval_repository=approvals,
        case_id=quote_case.case_id,
        expected_approval_id=first_approval.approval_id,
        subject="Munich quote - revised wording",
        body="Updated wording only. Offer: 2300 EUR. Transit 5-7 days.",
        edited_by="Pilot Operator",
        edited_at=NOW + timedelta(minutes=4),
        master_data_repository=masters,
        learning_fact_repository=facts,
    )
    check(
        revised.previous_approval.customer_commercial_context_snapshot.accepted_final_price_median.value == 2200
        and revised.new_approval.customer_commercial_context_snapshot.accepted_final_price_median.value == 2400
        and revised.new_approval.customer_commercial_context_snapshot.accepted_final_price_median.fact_id == replacement.fact_id,
        "each quote revision gets a fresh commercial snapshot while preserving the prior approval snapshot",
    )

    jobs = InMemoryMinaJobRepository()
    job, _ = jobs.create_manual(
        manual_intake_id="commercial-snapshot-history-job", intake_channel="phone", job_kind="price_request",
        shipment=shipment, opened_by="Regression", opened_at=NOW - timedelta(hours=1),
        sequence_year=2026, lifecycle_version=2,
    )
    linked_case = revised.quote_case.model_copy(update={"mina_job_id": job.job_id, "mina_code": job.mina_code})
    cases.save(linked_case)
    jobs.save(job.model_copy(update={"quote_case_id": linked_case.case_id, "updated_at": NOW + timedelta(minutes=5)}))
    history_detail = build_mina_job_detail(
        repository=jobs, supplier_repository=InMemorySupplierRFQRepository(),
        quote_case_repository=cases, action_repository=InMemoryAutomationActionRepository(),
        quote_approval_repository=approvals, master_data_repository=masters,
        learning_fact_repository=facts, job_id=job.job_id, now=NOW + timedelta(minutes=5),
    )
    history = history_detail["quote"]["approval_commercial_history"]
    check(
        [item["revision_number"] for item in history] == [0, 1]
        and history[0]["approval_id"] == first_approval.approval_id
        and history[1]["approval_id"] == revised.new_approval.approval_id
        and history[0]["customer_commercial_context_snapshot"]["accepted_final_price_median"]["value"] == 2200
        and history[1]["customer_commercial_context_snapshot"]["accepted_final_price_median"]["value"] == 2400
        and history[0]["is_current"] is False and history[1]["is_current"] is True,
        "job detail exposes ordered frozen commercial snapshots for each quote approval revision",
    )
    check(
        "quote_snapshot" not in str(history) and "quote_body" not in str(history)
        and "supplier_cost" not in str(history) and "evidence" not in str(history).casefold(),
        "approval commercial history remains privacy-minimal and excludes full quote and raw learning evidence",
    )

    legacy = QuoteApproval.model_validate({
        "quote_snapshot": first_approval.quote_snapshot.model_dump(mode="json"),
    })
    legacy_approvals = InMemoryQuoteApprovalRepository()
    legacy_approvals.save(legacy)
    legacy_case = QuoteCase(
        shipment=shipment, supplier_quote=supplier_quote, customer_quote=customer_quote,
        quote_draft=quote_draft, quote_approval=legacy,
    )
    legacy_cases = InMemoryQuoteCaseRepository(); legacy_cases.save(legacy_case)
    legacy_jobs = InMemoryMinaJobRepository()
    legacy_job, _ = legacy_jobs.create_manual(
        manual_intake_id="commercial-snapshot-legacy-job", intake_channel="phone", job_kind="price_request",
        shipment=shipment, opened_by="Regression", opened_at=NOW - timedelta(hours=1),
        sequence_year=2026, lifecycle_version=2,
    )
    legacy_cases.save(legacy_case.model_copy(update={"mina_job_id": legacy_job.job_id, "mina_code": legacy_job.mina_code}))
    legacy_jobs.save(legacy_job.model_copy(update={"quote_case_id": legacy_case.case_id, "updated_at": NOW}))
    legacy_detail = build_mina_job_detail(
        repository=legacy_jobs, supplier_repository=InMemorySupplierRFQRepository(),
        quote_case_repository=legacy_cases, action_repository=InMemoryAutomationActionRepository(),
        quote_approval_repository=legacy_approvals, job_id=legacy_job.job_id, now=NOW,
    )
    check(
        legacy_detail["quote"]["approval_commercial_history"][0]["record_state"] == "legacy_snapshot_missing"
        and legacy_detail["quote"]["approval_commercial_history"][0].get("customer_commercial_context_snapshot") is None,
        "legacy approval history explicitly preserves missing snapshot without live backfill",
    )

    approvals._approvals.pop(first_approval.approval_id, None)
    missing_detail = build_mina_job_detail(
        repository=jobs, supplier_repository=InMemorySupplierRFQRepository(),
        quote_case_repository=cases, action_repository=InMemoryAutomationActionRepository(),
        quote_approval_repository=approvals, job_id=job.job_id, now=NOW + timedelta(minutes=6),
    )
    check(
        missing_detail["quote"]["approval_commercial_history"][0]["record_state"] == "approval_record_missing"
        and "customer_commercial_context_snapshot" not in missing_detail["quote"]["approval_commercial_history"][0],
        "missing historical approval record fails closed instead of reconstructing commercial context",
    )
    check(
        revised.new_approval.quote_snapshot.matches_quote(
            revised.quote_case.supplier_quote,
            revised.quote_case.customer_quote,
            revised.quote_case.quote_draft,
        ),
        "commercial advisory snapshot does not alter quote-content snapshot validity",
    )

    with TemporaryDirectory(prefix="minai-commercial-snapshot-") as temp_dir:
        db_path = Path(temp_dir) / "pilot.sqlite3"
        durable = SQLiteQuoteApprovalRepository(SQLitePilotStore(db_path, run_id="commercial-snapshot-a"))
        durable.save(revised.new_approval)
        reloaded = SQLiteQuoteApprovalRepository(SQLitePilotStore(db_path, run_id="commercial-snapshot-b")).get(
            revised.new_approval.approval_id
        )
        check(
            reloaded is not None
            and reloaded.customer_commercial_context_snapshot is not None
            and reloaded.customer_commercial_context_snapshot.accepted_final_price_median.value == 2400,
            "commercial advisory snapshot survives durable approval persistence and restart",
        )

    check(
        legacy.customer_commercial_context_snapshot is None,
        "legacy approvals remain readable without fabricating historical commercial context",
    )

    serialized = revised.new_approval.customer_commercial_context_snapshot.model_dump(mode="json", exclude_none=True)
    check(
        serialized["advisory_only"] is True
        and serialized["pricing_authority"] is False
        and serialized["margin_authority"] is False
        and serialized["supplier_negotiation_authority"] is False
        and serialized["quote_send_authority"] is False
        and "evidence" not in str(serialized).casefold(),
        "frozen commercial context remains bounded advisory evidence with no execution authority or raw evidence",
    )

    root = Path(__file__).resolve().parents[2]
    ui = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "approval?.customer_commercial_context_snapshot" in ui
        and "data.quote?.approval_commercial_history" in ui
        and "Ticari Snapshot Geçmişi" in ui
        and "Geçmişe dönük veri uydurulmadı" in ui
        and "sonradan değişen öğrenmeler geçmiş kararı yeniden yazmaz" in ui
        and "const commercialContext = data.customer_commercial_context" not in ui,
        "quote review renders current and historical frozen approval snapshots without live recomputation",
    )
    progression = (root / "src" / "workflow" / "supplier_rfq_progression.py").read_text(encoding="utf-8")
    revision_source = (root / "src" / "core" / "quote_revision_service.py").read_text(encoding="utf-8")
    check(
        "customer_commercial_context_snapshot=commercial_context_snapshot" in progression
        and "customer_commercial_context_snapshot=commercial_context_snapshot" in revision_source,
        "new quote creation and operator revision both capture commercial advisory snapshots",
    )

    for label in passes:
        print("PASS", label)
    for label in failures:
        print("FAIL", label)
    print("\nCustomer commercial snapshot regressions:", "PASS" if not failures else "FAIL")
    return {"name": "Customer commercial advisory snapshot", "passed": not failures, "failures": failures}


if __name__ == "__main__":
    result = evaluate_customer_commercial_snapshot_regressions()
    raise SystemExit(0 if result["passed"] else 1)
