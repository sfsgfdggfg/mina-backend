from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import (
    MinaJobTransitionError,
    create_manual_mina_job,
    link_mina_job_workflow,
    transition_mina_job_stage,
)
from src.core.mina_job_view import build_mina_job_detail
from src.core.models import Shipment
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.sqlite_repositories import SQLiteMinaJobRepository
from src.core.supplier_price import SupplierPriceOffer, evaluate_fixed_rate_applicability
from src.core.supplier_price_repository import (
    InMemorySupplierPriceRepository,
    SQLiteSupplierPriceRepository,
    SupplierPriceIdempotencyConflictError,
)
from src.core.supplier_price_service import (
    build_job_supplier_price_view,
    create_direct_supplier_price_offer,
    create_supplier_fixed_rate,
    set_supplier_fixed_rate_active,
    use_fixed_rate_for_job,
)
from src.core.supplier_quote_comparison import build_supplier_price_offer_comparisons
from src.core.supplier_quote_selection import (
    build_supplier_quote_selection_decision,
    select_supplier_quote_from_price_offers,
)
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQResponse, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository

NOW = datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)


def _shipment(customer: str = "P2 Customer") -> Shipment:
    return Shipment(
        customer_name=customer,
        pickup_country="Turkey",
        pickup_city="Bursa",
        delivery_country="Germany",
        delivery_city="Stuttgart",
        transport_mode="road",
        service_type="FTL",
        equipment_type="Tenteli",
        quote_mode="indicative",
    )


def evaluate_supplier_price_source_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    jobs = InMemoryMinaJobRepository()
    prices = InMemorySupplierPriceRepository()
    suppliers = InMemorySupplierRFQRepository()
    job = create_manual_mina_job(
        repository=jobs,
        manual_intake_id="p2-approved-job",
        intake_channel="phone",
        job_kind="approved_job",
        shipment=_shipment(),
        opened_by="Operator One",
        opened_at=NOW,
    )
    job = transition_mina_job_stage(
        repository=jobs,
        mina_code=job.mina_code,
        target_stage="pricing",
        actor="Operator One",
        occurred_at=NOW + timedelta(minutes=1),
    )

    rate = create_supplier_fixed_rate(
        repository=prices,
        entry_id="rate-entry-1",
        supplier_name="FixedTrans",
        origin_country="Turkey",
        destination_country="Germany",
        origin_city="Bursa",
        transport_mode="road",
        service_type="FTL",
        equipment_type="Curtainsider",
        cost=2000,
        currency="eur",
        transit_time="4 days",
        valid_from=date(2026, 9, 1),
        valid_to=date(2026, 9, 30),
        evidence_source="agreement",
        evidence_reference="September agreement",
        recorded_by="Operator One",
        recorded_at=NOW,
    )
    repeated_rate = create_supplier_fixed_rate(
        repository=prices,
        entry_id="rate-entry-1",
        supplier_name="FixedTrans",
        origin_country="Turkey",
        destination_country="Germany",
        origin_city="Bursa",
        transport_mode="road",
        service_type="FTL",
        equipment_type="Curtainsider",
        cost=2000,
        currency="EUR",
        transit_time="4 days",
        valid_from=date(2026, 9, 1),
        valid_to=date(2026, 9, 30),
        evidence_source="agreement",
        evidence_reference="September agreement",
        recorded_by="Operator One",
        recorded_at=NOW + timedelta(minutes=1),
    )
    try:
        create_supplier_fixed_rate(
            repository=prices, entry_id="rate-entry-1", supplier_name="FixedTrans",
            origin_country="Turkey", destination_country="Germany", cost=9999,
            currency="EUR", valid_from=date(2026, 9, 1), valid_to=date(2026, 9, 30),
            evidence_source="agreement", recorded_by="Operator One", recorded_at=NOW,
        )
        rate_conflict_blocked = False
    except SupplierPriceIdempotencyConflictError:
        rate_conflict_blocked = True
    applicability = evaluate_fixed_rate_applicability(
        rate=rate, shipment=job.shipment, as_of=date(2026, 9, 4)
    )
    check(
        repeated_rate.rate_id == rate.rate_id
        and repeated_rate.cost == 2000
        and rate.currency == "EUR"
        and applicability.applicable
        and rate_conflict_blocked,
        "fixed rates are idempotent normalized and deterministically applicable",
    )

    mismatch_rate = create_supplier_fixed_rate(
        repository=prices,
        entry_id="rate-entry-mismatch",
        supplier_name="WrongLane",
        origin_country="Turkey",
        destination_country="Italy",
        cost=1700,
        currency="EUR",
        valid_from=date(2026, 9, 1),
        valid_to=date(2026, 9, 30),
        evidence_source="email",
        recorded_by="Operator One",
        recorded_at=NOW,
    )
    try:
        use_fixed_rate_for_job(
            price_repository=prices,
            mina_repository=jobs,
            job_id=job.job_id,
            rate_id=mismatch_rate.rate_id,
            entry_id="use-wrong-rate",
            recorded_by="Operator One",
            recorded_at=NOW + timedelta(minutes=2),
            as_of=date(2026, 9, 4),
        )
        mismatch_blocked = False
    except ValueError as exc:
        mismatch_blocked = "destination_country_mismatch" in str(exc)
    check(mismatch_blocked, "fixed rate use fails closed on route mismatch")

    region_rate = create_supplier_fixed_rate(
        repository=prices, entry_id="rate-entry-region", supplier_name="RegionTrans",
        origin_country="Turkey", destination_country="Germany",
        destination_region="Bavaria", cost=1800, currency="EUR",
        valid_from=date(2026, 9, 1), valid_to=date(2026, 9, 30),
        evidence_source="agreement", recorded_by="Operator One", recorded_at=NOW,
    )
    region_applicability = evaluate_fixed_rate_applicability(
        rate=region_rate, shipment=job.shipment, as_of=date(2026, 9, 4)
    )
    status_rate = create_supplier_fixed_rate(
        repository=prices, entry_id="rate-entry-status", supplier_name="StatusTrans",
        origin_country="Turkey", destination_country="Germany", cost=2200, currency="EUR",
        valid_from=date(2026, 9, 1), valid_to=date(2026, 9, 30),
        evidence_source="agreement", recorded_by="Operator One", recorded_at=NOW,
    )
    status_rate = set_supplier_fixed_rate_active(
        repository=prices, rate_id=status_rate.rate_id, active=False,
        updated_by="Manager One", updated_at=NOW + timedelta(minutes=2),
    )
    status_applicability = evaluate_fixed_rate_applicability(
        rate=status_rate, shipment=job.shipment, as_of=date(2026, 9, 4)
    )
    check(
        not region_applicability.applicable
        and "fixed_rate_destination_region_mismatch" in region_applicability.reasons
        and not status_rate.active
        and status_rate.updated_by == "Manager One"
        and "fixed_rate_inactive" in status_applicability.reasons,
        "fixed-rate region scope is exact and agreements can be explicitly deactivated",
    )

    phone_offer = create_direct_supplier_price_offer(
        price_repository=prices,
        mina_repository=jobs,
        job_id=job.job_id,
        entry_id="phone-price-1",
        supplier_name="PhoneTrans",
        source_type="phone",
        cost=1950,
        currency="EUR",
        transit_time="5 days",
        equipment_type="Tenteli",
        recorded_by="Operator One",
        recorded_at=NOW + timedelta(minutes=3),
        notes="Price confirmed by supplier pricing desk.",
    )
    repeated_phone = create_direct_supplier_price_offer(
        price_repository=prices,
        mina_repository=jobs,
        job_id=job.job_id,
        entry_id="phone-price-1",
        supplier_name="PhoneTrans",
        source_type="phone",
        cost=1950,
        currency="EUR",
        transit_time="5 days",
        equipment_type="Tenteli",
        recorded_by="Operator One",
        recorded_at=NOW + timedelta(minutes=4),
        notes="Price confirmed by supplier pricing desk.",
    )
    try:
        create_direct_supplier_price_offer(
            price_repository=prices, mina_repository=jobs, job_id=job.job_id,
            entry_id="phone-price-1", supplier_name="PhoneTrans", source_type="phone",
            cost=2500, currency="EUR", recorded_by="Operator One",
            recorded_at=NOW + timedelta(minutes=4),
        )
        phone_conflict_blocked = False
    except SupplierPriceIdempotencyConflictError:
        phone_conflict_blocked = True
    check(
        repeated_phone.offer_id == phone_offer.offer_id
        and repeated_phone.cost == 1950
        and phone_conflict_blocked
        and sum(e.event_type == "supplier_price_recorded" for e in jobs.list_events(job.job_id)) == 1,
        "direct supplier price entry is idempotent and creates one job audit event",
    )

    fixed_offer = use_fixed_rate_for_job(
        price_repository=prices,
        mina_repository=jobs,
        job_id=job.job_id,
        rate_id=rate.rate_id,
        entry_id="fixed-use-1",
        recorded_by="Operator One",
        recorded_at=NOW + timedelta(minutes=5),
        as_of=date(2026, 9, 4),
    )
    repeated_fixed_offer = use_fixed_rate_for_job(
        price_repository=prices,
        mina_repository=jobs,
        job_id=job.job_id,
        rate_id=rate.rate_id,
        entry_id="fixed-use-retry-different-entry",
        recorded_by="Operator One",
        recorded_at=NOW + timedelta(minutes=6),
        as_of=date(2026, 9, 4),
    )
    check(
        repeated_fixed_offer.offer_id == fixed_offer.offer_id
        and fixed_offer.source_type == "fixed_rate"
        and fixed_offer.fixed_rate_id == rate.rate_id
        and sum(e.event_type == "supplier_fixed_rate_used" for e in jobs.list_events(job.job_id)) == 1,
        "one fixed rate materializes at most once per MINA job with provenance",
    )

    workflow = SupplierRFQWorkflow(
        shipment=job.shipment,
        mina_job_id=job.job_id,
        mina_code=job.mina_code,
    )
    draft = SupplierRFQDraft(
        workflow_id=workflow.workflow_id,
        supplier_name="RFQTrans",
        priority=3,
        subject="RFQ",
        body="Please quote.",
        status="responded",
        responded_at=NOW + timedelta(minutes=7),
    )
    workflow = workflow.model_copy(update={"rfq_ids": [draft.rfq_id]})
    suppliers.save_workflow(workflow)
    suppliers.save_drafts([draft])
    suppliers.save_responses([SupplierRFQResponse(
        rfq_id=draft.rfq_id,
        supplier_name="RFQTrans",
        rfq_priority=3,
        status="quoted",
        cost=2050,
        currency="EUR",
        transit_time="4 days",
        equipment_type="Tenteli",
        source="email",
        received_at=NOW + timedelta(minutes=7),
    )])
    job = link_mina_job_workflow(
        repository=jobs,
        job_id=job.job_id,
        workflow_id=workflow.workflow_id,
        result_type="supplier_rfq_required",
        occurred_at=NOW + timedelta(minutes=7),
    )
    view = build_job_supplier_price_view(
        price_repository=prices,
        mina_repository=jobs,
        supplier_repository=suppliers,
        job_id=job.job_id,
        as_of=date(2026, 9, 4),
    )
    sources = {item["source_type"] for item in view["price_offers"]}
    check(
        {"phone", "fixed_rate", "rfq_email"}.issubset(sources)
        and len(view["applicable_fixed_rates"]) == 1,
        "job price view unifies RFQ direct and fixed-rate price sources",
    )

    rfq_offer = SupplierPriceOffer.model_validate(
        next(item for item in view["price_offers"] if item["source_type"] == "rfq_email")
    )
    supplier_selection = {
        "selected_suppliers": [
            {"supplier_name": "PhoneTrans", "priority": 1, "total_score": 0.80,
             "route_score": 0.9, "equipment_score": 0.9, "risk_score": 0.8,
             "price_score": 0.7, "speed_score": 0.7},
            {"supplier_name": "FixedTrans", "priority": 2, "total_score": 0.95,
             "route_score": 1.0, "equipment_score": 1.0, "risk_score": 0.9,
             "price_score": 0.9, "speed_score": 0.9},
            {"supplier_name": "RFQTrans", "priority": 3, "total_score": 0.70,
             "route_score": 0.8, "equipment_score": 0.9, "risk_score": 0.7,
             "price_score": 0.7, "speed_score": 0.6},
        ]
    }
    all_source_offers = [phone_offer, fixed_offer, rfq_offer]
    comparisons = build_supplier_price_offer_comparisons(
        all_source_offers, supplier_selection,
        shipment=job.shipment, expected_equipment="Tenteli",
        require_commercial_safety=False,
    )
    decision = build_supplier_quote_selection_decision(comparisons)
    selected_quote = select_supplier_quote_from_price_offers(comparisons, all_source_offers)
    check(
        len(comparisons) == 3
        and {item.price_source for item in comparisons} == {"phone", "fixed_rate", "rfq_email"}
        and decision is not None
        and decision.selected_price_offer_id == fixed_offer.offer_id
        and decision.selected_price_source == "fixed_rate"
        and selected_quote is not None
        and selected_quote.supplier_name == "FixedTrans"
        and selected_quote.price_source == "fixed_rate"
        and selected_quote.price_source_reference == rate.rate_id,
        "RFQ direct and fixed offers share the same multi-criteria comparison and preserve source",
    )

    job = transition_mina_job_stage(
        repository=jobs,
        mina_code=job.mina_code,
        target_stage="operation_opened",
        actor="Operator One",
        occurred_at=NOW + timedelta(minutes=8),
    )
    try:
        create_direct_supplier_price_offer(
            price_repository=prices,
            mina_repository=jobs,
            job_id=job.job_id,
            entry_id="too-late-price",
            supplier_name="LateTrans",
            source_type="manual",
            cost=1800,
            currency="EUR",
            recorded_by="Operator One",
            recorded_at=NOW + timedelta(minutes=9),
        )
        late_price_blocked = False
    except MinaJobTransitionError:
        late_price_blocked = True
    check(late_price_blocked, "initial supplier price sourcing closes once operation opens")

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "supplier-price.sqlite3", retention_days=1)
        durable_jobs = SQLiteMinaJobRepository(store)
        durable_prices = SQLiteSupplierPriceRepository(store)
        durable_job = create_manual_mina_job(
            repository=durable_jobs,
            manual_intake_id="durable-price-job",
            intake_channel="phone",
            job_kind="approved_job",
            shipment=_shipment("Durable Price Customer"),
            opened_by="Operator One",
            opened_at=NOW,
        )
        durable_job = transition_mina_job_stage(
            repository=durable_jobs,
            mina_code=durable_job.mina_code,
            target_stage="pricing",
            actor="Operator One",
            occurred_at=NOW + timedelta(minutes=1),
        )
        durable_rate = create_supplier_fixed_rate(
            repository=durable_prices,
            entry_id="durable-rate",
            supplier_name="DurableTrans",
            origin_country="Turkey",
            destination_country="Germany",
            cost=2100,
            currency="EUR",
            valid_from=date(2026, 9, 1),
            valid_to=date(2026, 12, 31),
            evidence_source="agreement",
            recorded_by="Operator One",
            recorded_at=NOW,
        )
        durable_offer = use_fixed_rate_for_job(
            price_repository=durable_prices,
            mina_repository=durable_jobs,
            job_id=durable_job.job_id,
            rate_id=durable_rate.rate_id,
            entry_id="durable-use",
            recorded_by="Operator One",
            recorded_at=NOW + timedelta(minutes=2),
            as_of=date(2026, 9, 4),
        )
        store.purge_expired(now=NOW + timedelta(days=40))
        reopened_prices = SQLiteSupplierPriceRepository(store)
        reopened_jobs = SQLiteMinaJobRepository(store)
        repeated_durable_job = create_manual_mina_job(
            repository=reopened_jobs, manual_intake_id="durable-price-job",
            intake_channel="phone", job_kind="approved_job",
            shipment=_shipment("Durable Price Customer"), opened_by="Operator One",
            opened_at=NOW + timedelta(days=40),
        )
        check(
            reopened_prices.get_fixed_rate(durable_rate.rate_id) is not None
            and reopened_prices.get_offer(durable_offer.offer_id) is not None
            and repeated_durable_job.job_id == durable_job.job_id,
            "fixed prices offers and manual-intake idempotency survive ordinary retention purge",
        )

    detail = build_mina_job_detail(
        repository=jobs,
        supplier_repository=suppliers,
        quote_case_repository=InMemoryQuoteCaseRepository(),
        action_repository=InMemoryAutomationActionRepository(),
        price_repository=prices,
        job_id=job.job_id,
        now=NOW + timedelta(minutes=10),
    )
    check(
        detail["supplier_prices"] is not None
        and {item["source_type"] for item in detail["supplier_prices"]["price_offers"]}
        >= {"phone", "fixed_rate", "rfq_email"},
        "MINA job detail exposes unified supplier price sourcing context",
    )

    from starlette.requests import Request
    from src import api
    api_jobs = InMemoryMinaJobRepository()
    api_prices = InMemorySupplierPriceRepository()
    api_suppliers = InMemorySupplierRFQRepository()
    api_job = create_manual_mina_job(
        repository=api_jobs, manual_intake_id="api-price-job", intake_channel="phone",
        job_kind="approved_job", shipment=_shipment("API Price Customer"),
        opened_by="API Operator", opened_at=NOW,
    )
    api_job = transition_mina_job_stage(
        repository=api_jobs, mina_code=api_job.mina_code, target_stage="pricing",
        actor="API Operator", occurred_at=NOW + timedelta(minutes=1),
    )
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Operator"
    original_repositories = (
        api.mina_job_repository, api.supplier_price_repository, api.supplier_rfq_repository,
    )
    try:
        api.mina_job_repository = api_jobs
        api.supplier_price_repository = api_prices
        api.supplier_rfq_repository = api_suppliers
        api_rate = api.create_fixed_rate(
            api.SupplierFixedRateCreateRequest(
                entry_id="api-fixed", supplier_name="API Fixed",
                origin_country="Turkey", destination_country="Germany",
                transport_mode="road", service_type="FTL", equipment_type="Tenteli",
                cost=1990, currency="EUR", valid_from=date(2026, 9, 1),
                valid_to=date(2026, 9, 30), evidence_source="agreement",
            ),
            request,
        )
        api_direct = api.create_mina_job_supplier_price(
            api_job.job_id,
            api.SupplierDirectPriceCreateRequest(
                entry_id="api-direct", supplier_name="API Phone", source_type="phone",
                cost=1980, currency="EUR", transit_time="4 days",
            ),
            request,
        )
        api_fixed = api.use_mina_job_fixed_rate(
            api_job.job_id, api_rate["rate_id"],
            api.SupplierFixedRateUseRequest(entry_id="api-fixed-use"),
            request,
        )
        api_view = api.get_mina_job_supplier_prices(api_job.job_id)
        api_rate_status = api.update_fixed_rate_status(
            api_rate["rate_id"], api.SupplierFixedRateStatusRequest(active=False), request
        )
    finally:
        api.mina_job_repository, api.supplier_price_repository, api.supplier_rfq_repository = original_repositories
    check(
        api_direct["source_type"] == "phone"
        and api_fixed["source_type"] == "fixed_rate"
        and len(api_view["price_offers"]) == 2
        and len(api_view["applicable_fixed_rates"]) == 1
        and api_rate_status["active"] is False,
        "supplier price API creates lists and materializes controlled price sources",
    )

    check(
        route_allowed("GET", "/supplier-fixed-rates")
        and route_allowed("POST", "/supplier-fixed-rates")
        and route_allowed("POST", "/supplier-fixed-rates/rate-1/status")
        and route_allowed("GET", "/mina-jobs/job-1/supplier-prices")
        and route_allowed("POST", "/mina-jobs/job-1/supplier-prices/manual")
        and route_allowed("POST", "/mina-jobs/job-1/supplier-prices/fixed-rate/rate-1"),
        "pilot access explicitly allows controlled supplier price source APIs",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_supplier_price_source_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nSupplier price source regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
