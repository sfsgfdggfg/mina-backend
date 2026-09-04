from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.master_data import CustomerMasterProfile, SupplierMasterProfile
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.mina_job import MinaJob, MinaJobEvent
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.models import CustomerQuote, Shipment, SupplierQuote
from src.core.operation_execution import OperationException, OperationExecutionSnapshot
from src.core.operation_execution_repository import InMemoryOperationExecutionRepository
from src.core.pilot_access import route_allowed
from src.core.quote_case import (
    CustomerQuoteAutomatedSentEvidence,
    CustomerQuoteManualSentEvidence,
    QuoteCase,
)
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.reporting_read_model import build_reporting_read_model, reporting_section
from src.core.supplier_price import SupplierPriceOffer
from src.core.supplier_price_repository import InMemorySupplierPriceRepository
from src.core.supplier_rfq import (
    SupplierRFQAutomatedSentEvidence,
    SupplierRFQDraft,
    SupplierRFQManualSentEvidence,
    SupplierRFQResponse,
    SupplierRFQWorkflow,
)
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository

UTC = timezone.utc
NOW = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)


def _shipment(customer: str, destination: str, *, deadline_hours: int | None = None, delivery_days: int | None = None):
    return Shipment(
        customer_name=customer,
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country=destination,
        delivery_city="Munich" if destination in {"Germany", "Almanya"} else "Vienna",
        transport_mode="road",
        equipment_type="Tenteli",
        customer_quote_deadline_at=(NOW + timedelta(hours=deadline_hours)) if deadline_hours is not None else None,
        required_delivery_date=(NOW.date() + timedelta(days=delivery_days)).isoformat() if delivery_days is not None else None,
    )


def _job(number: int, *, shipment: Shipment, kind: str, stage: str, sales: str | None, ops: str | None, closed_hours: int | None = None, opened_at: datetime = NOW):
    return MinaJob(
        mina_code=f"MINA2026/{number}", sequence_year=2026, sequence_number=number,
        lifecycle_version=2, job_kind=kind, intake_channel="phone",
        manual_intake_id=f"reporting-{number}", shipment=shipment,
        sales_owner=sales, operations_owner=ops, opened_by="Regression Operator",
        opened_at=opened_at, updated_at=(opened_at + timedelta(hours=closed_hours or 1)),
        stage=stage,
        closed_at=(opened_at + timedelta(hours=closed_hours)) if closed_hours is not None else None,
    )


def _stage_event(job: MinaJob, stage: str, hours: float):
    return MinaJobEvent(
        job_id=job.job_id, mina_code=job.mina_code, event_type="stage_changed",
        occurred_at=job.opened_at + timedelta(hours=hours), actor="Regression Operator",
        metadata={"from_stage": "fixture", "to_stage": stage, "lifecycle_version": 2},
    )


def _build_fixture():
    jobs = InMemoryMinaJobRepository()
    quotes = InMemoryQuoteCaseRepository()
    rfqs = InMemorySupplierRFQRepository()
    prices = InMemorySupplierPriceRepository()
    operations = InMemoryOperationExecutionRepository()
    masters = InMemoryMasterDataRepository()
    learning = InMemoryLearningFactRepository()

    job1 = _job(
        1, shipment=_shipment("Acme", "Germany", deadline_hours=4, delivery_days=2),
        kind="price_request", stage="completed", sales="Alice", ops="Ozan", closed_hours=40,
    )
    job2 = _job(
        2, shipment=_shipment("Beta", "Almanya", deadline_hours=4, delivery_days=3),
        kind="price_request", stage="lost", sales="Alice", ops=None, closed_hours=10,
    )
    job3 = _job(
        3, shipment=_shipment("ACME Logistics", "Austria", delivery_days=3),
        kind="approved_job", stage="in_transit", sales="Bob", ops="Ozan",
    )
    old_job = _job(
        4, shipment=_shipment("Old Customer", "Germany"), kind="approved_job",
        stage="pricing", sales="Old Sales", ops="Old Ops", opened_at=NOW - timedelta(days=2),
    )
    for job in (job1, job2, job3, old_job):
        jobs.save(job)

    for event in (
        _stage_event(job1, "quote_sent", 2), _stage_event(job1, "accepted", 5),
        _stage_event(job1, "operation_opened", 6), _stage_event(job1, "completed", 40),
        _stage_event(job2, "quote_sent", 6), _stage_event(job2, "lost", 10),
        _stage_event(job3, "operation_opened", 1), _stage_event(job3, "in_transit", 12),
    ):
        jobs.append_event(event)

    case1 = QuoteCase(
        shipment=job1.shipment, mina_job_id=job1.job_id, mina_code=job1.mina_code,
        supplier_quote=SupplierQuote(supplier_name="Carrier A", cost=2000, currency="EUR"),
        customer_quote=CustomerQuote(
            supplier_cost=2000, markup_type="fixed_profit", markup_value=300,
            final_price=2300, currency="EUR",
        ),
    )
    case1.automated_sent_evidence.append(CustomerQuoteAutomatedSentEvidence(
        case_id=case1.case_id, approval_id="approval-1", revision_number=0,
        recipient_email="ops@acme.test", provider_name="outlook",
        provider_message_id="msg-1", sent_at=NOW + timedelta(hours=2),
    ))
    case2 = QuoteCase(
        shipment=job2.shipment, mina_job_id=job2.job_id, mina_code=job2.mina_code,
        supplier_quote=SupplierQuote(supplier_name="Carrier B", cost=2100, currency="USD"),
        customer_quote=CustomerQuote(
            supplier_cost=2100, markup_type="fixed_profit", markup_value=400,
            final_price=2500, currency="USD",
        ),
    )
    case2.manual_sent_evidence.append(CustomerQuoteManualSentEvidence(
        case_id=case2.case_id, approval_id="approval-2", revision_number=0,
        recipient_email="ops@beta.test", sent_by="Alice", sent_at=NOW + timedelta(hours=6),
    ))
    case3 = QuoteCase(
        shipment=job3.shipment, mina_job_id=job3.job_id, mina_code=job3.mina_code,
        supplier_quote=SupplierQuote(supplier_name="Carrier A", cost=1900, currency="EUR"),
    )
    for case, job in ((case1, job1), (case2, job2), (case3, job3)):
        quotes.save(case)
        jobs.save(job.model_copy(update={"quote_case_id": case.case_id}))

    operations.save_snapshot(OperationExecutionSnapshot(
        job_id=job1.job_id, mina_code=job1.mina_code, vehicle_plate="01 ABC 01",
        driver_name="Driver One", vehicle_assigned_at=NOW + timedelta(hours=10),
        loaded_at=NOW + timedelta(hours=12), delivered_at=NOW + timedelta(hours=32),
        cmr_received_at=NOW + timedelta(hours=35), updated_at=NOW + timedelta(hours=35),
        updated_by="Ozan",
    ))
    operations.create_exception(OperationException(
        entry_id="exception-1", job_id=job1.job_id, mina_code=job1.mina_code,
        stage_at_report="in_transit", exception_type="border_congestion",
        impact_level="actual_delay", cause="Border delay", source_type="supplier_phone",
        reported_at=NOW + timedelta(hours=20), created_at=NOW + timedelta(hours=20),
        created_by="Ozan", updated_at=NOW + timedelta(hours=22), updated_by="Ozan",
        status="resolved", resolved_at=NOW + timedelta(hours=22), resolved_by="Ozan",
        resolution_note="Cleared border and delivery recovered.",
    ))
    operations.create_exception(OperationException(
        entry_id="exception-2", job_id=job3.job_id, mina_code=job3.mina_code,
        stage_at_report="in_transit", exception_type="weather",
        impact_level="delivery_risk", cause="Storm risk", source_type="operator",
        reported_at=NOW + timedelta(hours=13), created_at=NOW + timedelta(hours=13),
        created_by="Ozan", updated_at=NOW + timedelta(hours=13), updated_by="Ozan",
    ))

    workflow1 = SupplierRFQWorkflow(
        workflow_id="workflow-1", shipment=job1.shipment, mina_job_id=job1.job_id,
        mina_code=job1.mina_code, created_at=NOW, updated_at=NOW,
    )
    draft_a = SupplierRFQDraft(
        rfq_id="rfq-a", workflow_id=workflow1.workflow_id, supplier_name="Carrier A",
        priority=1, subject="RFQ", body="Body", status="responded",
        created_at=NOW, sent_at=NOW + timedelta(minutes=10), responded_at=NOW + timedelta(minutes=40),
    )
    draft_b = SupplierRFQDraft(
        rfq_id="rfq-b", workflow_id=workflow1.workflow_id, supplier_name="Carrier B",
        priority=2, subject="RFQ", body="Body", status="responded",
        created_at=NOW, sent_at=NOW + timedelta(minutes=10), responded_at=NOW + timedelta(minutes=30),
    )
    rfqs.save_workflow(workflow1)
    rfqs.save_drafts([draft_a, draft_b])
    rfqs.save_responses([
        SupplierRFQResponse(
            rfq_id="rfq-a", supplier_name="Carrier A", rfq_priority=1, status="quoted",
            cost=2000, currency="EUR", source="email", received_at=NOW + timedelta(minutes=40),
        ),
        SupplierRFQResponse(
            rfq_id="rfq-b", supplier_name="Carrier B", rfq_priority=2, status="no_capacity",
            source="email", received_at=NOW + timedelta(minutes=30),
        ),
    ])
    rfqs.save_automated_sent_evidence(SupplierRFQAutomatedSentEvidence(
        rfq_id="rfq-a", recipient_email="a@carrier.test", provider_name="outlook",
        provider_message_id="rfq-msg-a", sent_at=NOW + timedelta(minutes=10),
    ))
    rfqs.save_manual_sent_evidence(SupplierRFQManualSentEvidence(
        rfq_id="rfq-b", recorded_by="Alice", recorded_at=NOW + timedelta(minutes=10),
    ))

    prices.create_offer(SupplierPriceOffer(
        entry_id="price-job3-a", mina_job_id=job3.job_id, mina_code=job3.mina_code,
        supplier_name="Carrier A", source_type="manual", cost=1900, currency="EUR",
        recorded_by="Ozan", recorded_at=NOW + timedelta(minutes=20),
    ))
    prices.create_offer(SupplierPriceOffer(
        entry_id="price-job2-b", mina_job_id=job2.job_id, mina_code=job2.mina_code,
        supplier_name="Carrier B", source_type="manual", cost=2100, currency="USD",
        recorded_by="Alice", recorded_at=NOW + timedelta(minutes=30),
    ))

    masters.create_customer(CustomerMasterProfile(
        entry_id="acme-master", customer_name="Acme", aliases=["ACME Logistics"],
        created_at=NOW, updated_at=NOW, updated_by="Admin",
    ))
    masters.create_supplier(SupplierMasterProfile(
        entry_id="carrier-a", supplier_name="Carrier A", reliability_score=0.9,
        price_score=0.7, speed_score=0.8, created_at=NOW, updated_at=NOW, updated_by="Admin",
    ))

    evidence = LearningEvidence(
        source_type="operation_history", source_reference=job1.mina_code,
        observed_at=NOW + timedelta(hours=2), summary="Historical route pattern observed during operation.",
    )
    learning.create(LearningFact(
        entry_id="learn-confirmed", subject_type="operation", subject_id=job1.job_id,
        subject_label=job1.mina_code, fact_key="route.border_pattern", value="stable",
        confidence=0.9, source_type="minai_inference", evidence=[evidence], status="confirmed",
        created_at=NOW + timedelta(hours=3), created_by="MINAI",
        updated_at=NOW + timedelta(hours=4), reviewed_at=NOW + timedelta(hours=4),
        reviewed_by="Ozan", review_note="Confirmed from history.",
    ))
    learning.create(LearningFact(
        entry_id="learn-proposed", subject_type="operation", subject_id=job3.job_id,
        subject_label=job3.mina_code, fact_key="route.weather_pattern", value="watch",
        confidence=0.8, source_type="minai_inference", evidence=[LearningEvidence(
            source_type="operation_history", source_reference=job3.mina_code,
            observed_at=NOW + timedelta(hours=5), summary="Current operation weather observation.",
        )], created_at=NOW + timedelta(hours=5), created_by="MINAI",
        updated_at=NOW + timedelta(hours=5),
    ))
    return jobs, quotes, rfqs, prices, operations, masters, learning, (job1, job2, job3, old_job)


def evaluate_reporting_read_model_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str):
        (passes if condition else failures).append(label)

    jobs, quotes, rfqs, prices, operations, masters, learning, fixture_jobs = _build_fixture()
    report = build_reporting_read_model(
        mina_repository=jobs, quote_case_repository=quotes, supplier_rfq_repository=rfqs,
        supplier_price_repository=prices, operation_execution_repository=operations,
        master_data_repository=masters, learning_fact_repository=learning,
        start_date=date(2026, 9, 4), end_date=date(2026, 9, 4), as_of=NOW + timedelta(days=1),
    )
    check(
        report["period"]["job_count"] == 3
        and all(row["mina_code"] != "MINA2026/4" for row in report["jobs"]),
        "reporting period filters cohorts by MINA opened-at Istanbul date",
    )
    overview = report["overview"]
    check(
        overview["price_request_count"] == 2 and overview["approved_job_count"] == 1
        and overview["quotes_sent_count"] == 2 and overview["accepted_price_request_count"] == 1
        and overview["quote_to_accept_conversion_percent"] == 50.0
        and overview["completed_job_count"] == 1,
        "overview derives historical conversion milestones from durable timeline evidence",
    )
    check(
        overview["quote_deadline_sla_percent"] == 50.0
        and overview["on_time_delivery_percent"] == 100.0
        and overview["average_quote_turnaround_hours"] == 4.0,
        "overview exposes only measurable SLA and turnaround evidence",
    )
    money = report["financial"]
    eur = money["by_currency"]["EUR"]
    check(
        money["financially_covered_job_count"] == 2
        and money["uncovered_job_count"] == 1
        and set(money["by_currency"]) == {"EUR", "USD"}
        and round(eur["quoted_value"], 2) == 2300
        and round(eur["quoted_gross_profit"], 2) == 300
        and round(eur["accepted_value"], 2) == 2300
        and round(eur["completed_gross_profit"], 2) == 300
        and round(money["by_currency"]["USD"]["quoted_value"], 2) == 2500
        and round(money["by_currency"]["USD"]["accepted_value"], 2) == 0,
        "financial reporting keeps currencies separate and leaves missing approved-job revenue uncovered",
    )
    alice = next(row for row in report["sales"]["rows"] if row["name"] == "Alice")
    ozan = next(row for row in report["operations"]["rows"] if row["name"] == "Ozan")
    check(
        alice["job_count"] == 2 and alice["quote_sent_count"] == 2
        and alice["accepted_price_request_count"] == 1 and alice["quote_to_accept_conversion_percent"] == 50.0
        and alice["average_quote_turnaround_hours"] == 4.0
        and alice["quote_deadline_sla_percent"] == 50.0,
        "sales-person read model preserves quote conversion without counting approved jobs as quotes",
    )
    check(
        ozan["job_count"] == 2 and ozan["completed_count"] == 1
        and ozan["exception_count"] == 2 and ozan["actual_delay_count"] == 1
        and ozan["average_operation_cycle_hours"] == 34.0
        and ozan["on_time_delivery_percent"] == 100.0,
        "operations-person read model combines workload completion and exception outcomes",
    )
    acme = next(row for row in report["customers"]["rows"] if row["name"] == "Acme")
    route_de = next(row for row in report["routes"]["rows"] if row["name"] == "Türkiye → Germany")
    check(
        acme["job_count"] == 2 and acme["completed_count"] == 1
        and all(row["name"] != "ACME Logistics" for row in report["customers"]["rows"])
        and acme["accepted_price_request_count"] == 1
        and acme["quote_to_accept_conversion_percent"] == 100.0
        and acme["awarded_job_count"] == 2
        and route_de["job_count"] == 2 and route_de["quote_sent_count"] == 2
        and route_de["route_key"] == "turkiye->germany",
        "customer aliases and country aliases aggregate through master-data normalization",
    )
    carrier_a = next(row for row in report["suppliers"]["rows"] if row["name"] == "Carrier A")
    check(
        carrier_a["rfq_sent_count"] == 1 and carrier_a["responded_count"] == 1
        and carrier_a["quoted_count"] == 1 and carrier_a["average_response_minutes"] == 30.0
        and carrier_a["selected_count"] == 2 and carrier_a["master_reliability_score"] == 0.9,
        "supplier reporting combines RFQ responsiveness price participation selection and master score evidence",
    )
    check(
        carrier_a["selection_rate_percent"] == 100.0
        and carrier_a["selection_provenance_gap_count"] == 0,
        "supplier selection rate stays bounded when candidate price provenance is complete",
    )
    exception = report["exceptions"]
    check(
        exception["total_count"] == 2 and exception["status_counts"] == {"open": 1, "resolved": 1}
        and exception["impact_counts"]["actual_delay"] == 1
        and exception["impact_counts"]["delivery_risk"] == 1
        and exception["average_resolution_hours"] == 2.0,
        "exception report preserves deviation-risk-delay semantics and resolution duration",
    )
    minai = report["minai"]
    check(
        minai["learning_period_basis"] == "learning_fact_created_at_istanbul"
        and minai["learning_fact_status_counts"]["confirmed"] == 1
        and minai["learning_fact_status_counts"]["proposed"] == 1
        and minai["minai_inference_confirmation_percent"] == 100.0
        and minai["tracked_external_send_automation_share_percent"] == 50.0,
        "MINAI report uses reviewed learning and actual outbound-send evidence",
    )
    quality = report["data_quality"]
    check(
        quality["financially_uncovered_job_count"] == 1
        and quality["customer_master_matched_job_count"] == 2
        and quality["customer_master_coverage_percent"] == 66.67
        and quality["supplier_selection_provenance_gap_count"] == 0
        and quality["missing_operations_owner_count"] == 1
        and quality["delivery_sla_measurable_count"] == 1,
        "reporting exposes data coverage gaps instead of coercing missing evidence to zero",
    )
    check(
        reporting_section(report, "financial")["financial"] == report["financial"],
        "reporting section projection preserves shared period context and exact section data",
    )
    try:
        build_reporting_read_model(
            mina_repository=jobs, quote_case_repository=quotes, supplier_rfq_repository=rfqs,
            supplier_price_repository=prices, operation_execution_repository=operations,
            master_data_repository=masters, learning_fact_repository=learning,
            start_date=date(2026, 9, 5), end_date=date(2026, 9, 4),
        )
        bad_period_rejected = False
    except ValueError:
        bad_period_rejected = True
    check(bad_period_rejected, "reporting rejects inverted date ranges")

    import src.api as api
    originals = (
        api.mina_job_repository, api.quote_case_repository, api.supplier_rfq_repository,
        api.supplier_price_repository, api.operation_execution_repository,
        api.master_data_repository, api.learning_fact_repository,
    )
    try:
        (
            api.mina_job_repository, api.quote_case_repository, api.supplier_rfq_repository,
            api.supplier_price_repository, api.operation_execution_repository,
            api.master_data_repository, api.learning_fact_repository,
        ) = (jobs, quotes, rfqs, prices, operations, masters, learning)
        api_report = api.get_reporting_read_model(start_date=date(2026, 9, 4), end_date=date(2026, 9, 4))
        api_financial = api.get_reporting_section("financial", start_date=date(2026, 9, 4), end_date=date(2026, 9, 4))
    finally:
        (
            api.mina_job_repository, api.quote_case_repository, api.supplier_rfq_repository,
            api.supplier_price_repository, api.operation_execution_repository,
            api.master_data_repository, api.learning_fact_repository,
        ) = originals
    check(
        api_report["overview"]["job_count"] == 3
        and api_financial["financial"]["uncovered_job_count"] == 1,
        "reporting API exposes full and section read models from the same repository authorities",
    )
    check(
        route_allowed("GET", "/reports") and route_allowed("GET", "/reports/overview")
        and route_allowed("GET", "/reports/financial") and not route_allowed("POST", "/reports"),
        "pilot access exposes reporting as read-only controlled surfaces",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_reporting_read_model_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nReporting read-model regressions: " + ("PASS" if result["passed"] else "FAIL"))
