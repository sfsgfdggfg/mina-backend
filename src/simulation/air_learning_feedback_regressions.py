from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_learning_feedback_repository import (
    AirLearningFeedbackConflictError,
    InMemoryAirLearningFeedbackRepository,
    SQLiteAirLearningFeedbackRepository,
)
from src.core.air_learning_service import (
    AirLearningTransitionError,
    build_air_learning_feedback_view,
    build_air_route_learning_advisory,
    build_air_route_learning_advisory_for_route,
    current_air_learning_feedback,
    derive_air_route_learning,
    record_air_learning_feedback,
)
from src.core.air_operation_handoff_repository import InMemoryAirOperationHandoffRepository
from src.core.air_operation_handoff_service import prepare_air_operation_handoff
from src.core.learning_fact_repository import InMemoryLearningFactRepository, SQLiteLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact, list_learning_facts
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.air_freight_calculation_preview_regressions import _table_repo
from src.simulation.air_operation_handoff_regressions import (
    HANDOFF_AT,
    _approve_send_accept,
)
from src.simulation.air_quote_preparation_regressions import (
    _customer_repo,
    _job,
    _prepare,
    _setup,
    _validity_repo,
)
from src.simulation.air_quote_readiness_preview_regressions import _availability_repo, _shipment


FEEDBACK_AT = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def _handoff_chain(key: str, *, with_expected_delivery: bool = True):
    setup = _setup()
    source_repo = setup[0]
    customer_repo, customer = _customer_repo()
    validity_repo = _validity_repo(source_repo)
    expected = date(2026, 9, 17) if with_expected_delivery else None
    availability_repo = _availability_repo(source_repo, expected_delivery_date=expected)
    from src.core.mina_job_repository import InMemoryMinaJobRepository
    from src.core.quote_case_repository import InMemoryQuoteCaseRepository
    from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository

    jobs = InMemoryMinaJobRepository()
    cases = InMemoryQuoteCaseRepository()
    approvals = InMemoryQuoteApprovalRepository()
    shipment = _shipment(required_delivery_date=("2026-09-18" if with_expected_delivery else None))
    job = _job(jobs, key=key, shipment=shipment)
    prepared = _prepare(
        setup=setup, customer_repo=customer_repo, customer=customer,
        job_repo=jobs, job=job, cases=cases, approvals=approvals,
        availability_repo=availability_repo, validity_repo=validity_repo,
    )
    _approve_send_accept(job_repo=jobs, cases=cases, approvals=approvals, prepared=prepared)
    handoffs = InMemoryAirOperationHandoffRepository()
    handoff = prepare_air_operation_handoff(
        job_id=job.job_id, handed_off_by="Air Ops",
        handoff_repository=handoffs, mina_repository=jobs,
        quote_case_repository=cases, approval_repository=approvals,
        handed_off_at=HANDOFF_AT,
    ).handoff
    return jobs, cases, approvals, handoffs, job, handoff, setup


def _feedback(
    *, repo, jobs, handoffs, job, index: int,
    tariff_usage: str = "used_as_quoted",
    actual_cost: Decimal | None = None,
    currency: str | None = "USD",
    actual_weight: Decimal | None = None,
    actual_delivery: date | None = date(2026, 9, 17),
    corrections: list[str] | None = None,
    entry_id: str | None = None,
    supersedes: str | None = None,
    airline: str = "THY",
    routing: str = "direct",
    via: str | None = None,
):
    return record_air_learning_feedback(
        feedback_repository=repo, handoff_repository=handoffs, mina_repository=jobs,
        job_id=job.job_id, entry_id=entry_id or f"air-learning-{index}",
        tariff_usage=tariff_usage, actual_airline_name=airline,
        actual_routing_context=routing, actual_via_airport=via,
        actual_service_date=date(2026, 9, 16), actual_delivery_date=actual_delivery,
        actual_chargeable_weight_kg=actual_weight,
        actual_cost_amount=actual_cost, actual_cost_currency=(currency if actual_cost is not None else None),
        correction_categories=list(corrections or []),
        evidence_source="airline_invoice", source_reference=f"INV-{index}",
        note=f"Explicit air outcome evidence {index}", recorded_by="Air Outcome Operator",
        supersedes_feedback_id=supersedes, occurred_at=FEEDBACK_AT + timedelta(minutes=index),
    )


def evaluate_air_learning_feedback_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    feedback_repo = InMemoryAirLearningFeedbackRepository()
    learning_repo = InMemoryLearningFactRepository()

    # No P2-43 handoff means no air outcome-learning authority.
    jobs0, _cases0, _approvals0, _handoffs0, job0, _handoff0, _setup0 = _handoff_chain("air-p244-nohandoff")
    empty_handoffs = InMemoryAirOperationHandoffRepository()
    no_handoff_blocked = False
    try:
        record_air_learning_feedback(
            feedback_repository=feedback_repo, handoff_repository=empty_handoffs,
            mina_repository=jobs0, job_id=job0.job_id, entry_id="no-handoff",
            tariff_usage="used_as_quoted", actual_airline_name="THY",
            actual_routing_context="direct", evidence_source="operator",
            source_reference="none", note="should block", recorded_by="Operator",
            occurred_at=FEEDBACK_AT,
        )
    except AirLearningTransitionError as exc:
        no_handoff_blocked = "requires a durable accepted-quote operation handoff" in str(exc)
    check(no_handoff_blocked, "air outcome feedback cannot exist without the durable accepted-quote handoff")

    jobs1, cases1, approvals1, handoffs1, job1, handoff1, _ = _handoff_chain("air-p244-1")
    first = _feedback(
        repo=feedback_repo, jobs=jobs1, handoffs=handoffs1, job=job1, index=1,
        actual_cost=Decimal("990.675"), actual_weight=Decimal("306"),
    )
    check(
        first.quoted_air_context == handoff1.air_quote_context
        and first.quoted_air_context.quoted_chargeable_weight_kg == Decimal("300")
        and any(
            event.event_type == "air_learning_feedback_recorded"
            and event.resource_id == first.feedback_id
            for event in jobs1.list_events(job1.job_id)
        ),
        "air feedback freezes exact quoted air provenance and records bounded MINA timeline evidence",
    )
    retried = _feedback(
        repo=feedback_repo, jobs=jobs1, handoffs=handoffs1, job=job1, index=1,
        actual_cost=Decimal("990.675"), actual_weight=Decimal("306"),
    )
    check(
        retried.feedback_id == first.feedback_id and len(feedback_repo.list_for_job(job1.job_id)) == 1,
        "identical air feedback retry is idempotent by entry_id",
    )
    conflict = False
    try:
        _feedback(
            repo=feedback_repo, jobs=jobs1, handoffs=handoffs1, job=job1, index=1,
            actual_cost=Decimal("1000"), actual_weight=Decimal("306"),
        )
    except AirLearningFeedbackConflictError:
        conflict = True
    check(conflict, "air feedback entry_id cannot drift to different evidence")

    missing_supersession = False
    try:
        _feedback(
            repo=feedback_repo, jobs=jobs1, handoffs=handoffs1, job=job1, index=101,
            tariff_usage="used_with_correction", actual_cost=Decimal("1000"),
            actual_weight=Decimal("309"), corrections=["surcharge"],
        )
    except AirLearningTransitionError as exc:
        missing_supersession = "must explicitly supersede" in str(exc)
    check(missing_supersession, "new air feedback must explicitly supersede the current job feedback")

    revised = _feedback(
        repo=feedback_repo, jobs=jobs1, handoffs=handoffs1, job=job1, index=102,
        tariff_usage="used_with_correction", actual_cost=Decimal("1009.545"),
        actual_weight=Decimal("309"), corrections=["surcharge"], supersedes=first.feedback_id,
    )
    check(
        current_air_learning_feedback(feedback_repo, job_id=job1.job_id).feedback_id == revised.feedback_id
        and len(feedback_repo.list_for_job(job1.job_id)) == 2,
        "air feedback correction preserves prior evidence and makes only the explicit replacement current",
    )

    # One current record is intentionally below all aggregation thresholds.
    sparse = derive_air_route_learning(
        job_id=job1.job_id, feedback_repository=feedback_repo,
        learning_repository=learning_repo, created_by="Learning Operator",
        occurred_at=FEEDBACK_AT + timedelta(hours=2),
    )
    check(
        sparse["eligible_feedback_count"] == 1 and sparse["proposed_fact_count"] == 0,
        "single air outcome never becomes a learned route rule",
    )

    chains = [(jobs1, handoffs1, job1, revised)]
    specs = [
        # index, tariff_usage, actual cost, currency, weight, delivery, corrections, airline, routing, via
        (2, "used_as_quoted", Decimal("971.805"), "USD", Decimal("303"), date(2026, 9, 17), [], "THY", "direct", None),
        (3, "used_with_correction", Decimal("1028.415"), "USD", Decimal("315"), date(2026, 9, 18), ["surcharge"], "THY", "direct", None),
        (4, "not_used", Decimal("900"), "EUR", Decimal("297"), None, ["airline", "routing"], "LH", "connecting", "MUC"),
        (5, "used_with_correction", Decimal("910"), "EUR", Decimal("312"), date(2026, 9, 17), ["surcharge"], "THY", "direct", None),
    ]
    for idx, usage, cost, curr, weight, delivery, corrections, airline, routing, via in specs:
        jobs, _cases, _approvals, handoffs, job, _handoff, _setupx = _handoff_chain(f"air-p244-{idx}")
        item = _feedback(
            repo=feedback_repo, jobs=jobs, handoffs=handoffs, job=job, index=idx,
            tariff_usage=usage, actual_cost=cost, currency=curr, actual_weight=weight,
            actual_delivery=delivery, corrections=corrections, airline=airline, routing=routing, via=via,
        )
        chains.append((jobs, handoffs, job, item))

    derived = derive_air_route_learning(
        job_id=job1.job_id, feedback_repository=feedback_repo,
        learning_repository=learning_repo, created_by="Learning Operator",
        occurred_at=FEEDBACK_AT + timedelta(hours=3),
    )
    proposed_by_key = {item["fact_key"]: item for item in derived["proposed_facts"]}
    check(
        derived["eligible_feedback_count"] == 5
        and derived["cost_variance_sample_count"] == 3
        and "air.cost_basis_variance_median_percent" in proposed_by_key
        and proposed_by_key["air.cost_basis_variance_median_percent"]["status"] == "proposed",
        "three same-currency current outcomes can propose cost-basis variance while cross-currency costs are excluded without FX",
    )
    check(
        derived["chargeable_weight_variance_sample_count"] == 5
        and "air.chargeable_weight_variance_median_percent" in proposed_by_key,
        "three-plus frozen quoted/actual chargeable-weight observations can propose a route accuracy advisory",
    )
    check(
        "air.quoted_tariff_exact_use_rate_percent" in proposed_by_key
        and "air.route_plan_unchanged_rate_percent" in proposed_by_key,
        "five explicit outcomes can propose tariff-reuse and actual-route consistency rates",
    )
    check(
        derived["delivery_sample_count"] == 4
        and "air.expected_delivery_met_rate_percent" not in proposed_by_key,
        "missing delivery evidence is excluded rather than counted late and a four-sample delivery set stays below threshold",
    )
    check(
        "air.frequent_correction_categories" in proposed_by_key
        and "surcharge" in proposed_by_key["air.frequent_correction_categories"]["value"],
        "recurring correction categories are proposed only after repeated explicit outcome evidence",
    )
    check(
        derived["pricing_authority_created"] is False
        and derived["tariff_authority_created"] is False
        and derived["routing_authority_created"] is False
        and derived["booking_authority_created"] is False,
        "air route derivation creates no pricing tariff routing or booking authority",
    )

    # Human confirmation does not promote P2-44 route facts into generic runtime authority.
    variance_fact = next(
        item for item in learning_repo.list_all()
        if item.fact_key == "air.cost_basis_variance_median_percent" and item.status == "proposed"
    )
    confirmed = confirm_learning_fact(
        repository=learning_repo, fact_id=variance_fact.fact_id,
        reviewed_by="Air Learning Reviewer", review_note="Historical route advisory is supported.",
        occurred_at=FEEDBACK_AT + timedelta(hours=4),
    )
    advisory = build_air_route_learning_advisory(
        learning_repository=learning_repo, context=handoff1.air_quote_context,
    )
    check(
        confirmed.status == "confirmed" and confirmed.runtime_authoritative is False
        and confirmed.fact_id in advisory["source_fact_ids"]
        and list_learning_facts(repository=learning_repo, runtime_only=True) == [],
        "human-confirmed air route learning remains advisory and is excluded from generic runtime-only authority",
    )
    other_route = build_air_route_learning_advisory_for_route(
        learning_repository=learning_repo, origin_airport="ADA", destination_code="FRA",
        airline_name="LH", routing_context="direct",
    )
    check(
        advisory["confirmed_fact_count"] == 1 and other_route["confirmed_fact_count"] == 0
        and advisory["pricing_authority"] is False and advisory["tariff_authority"] is False
        and advisory["routing_authority"] is False and advisory["booking_authority"] is False,
        "confirmed air advisory is isolated by exact airport-pair airline and routing context",
    )

    view = build_air_learning_feedback_view(
        job_id=job1.job_id, feedback_repository=feedback_repo,
        learning_repository=learning_repo, handoff_repository=handoffs1,
    )
    check(
        view["current"]["feedback_id"] == revised.feedback_id
        and len(view["history"]) == 2
        and view["advisory"]["confirmed_fact_count"] == 1,
        "air learning read model exposes current feedback full audit history and confirmed advisory separately",
    )

    # Durable namespaces and repository reconstruction.
    with TemporaryDirectory(prefix="minai-air-p244-") as temp_dir:
        db_path = Path(temp_dir) / "pilot.sqlite3"
        store = SQLitePilotStore(db_path, run_id="air-p244-a")
        sqlite_feedback = SQLiteAirLearningFeedbackRepository(store)
        sqlite_learning = SQLiteLearningFactRepository(store)
        persisted_feedback, created = sqlite_feedback.create(revised)
        persisted_fact, fact_created = sqlite_learning.create(confirmed)
        reopened = SQLitePilotStore(db_path, run_id="air-p244-b")
        rebuilt_feedback = SQLiteAirLearningFeedbackRepository(reopened).get(persisted_feedback.feedback_id)
        rebuilt_fact = SQLiteLearningFactRepository(reopened).get(persisted_fact.fact_id)
        check(
            created and fact_created and rebuilt_feedback is not None and rebuilt_fact is not None
            and rebuilt_feedback.quoted_air_context.source_sha256 == revised.quoted_air_context.source_sha256
            and rebuilt_fact.runtime_authoritative is False,
            "air feedback and reviewed advisory survive SQLite reconstruction without gaining runtime authority",
        )
    check(
        "air_learning_feedback" in PERSISTENT_STATE_NAMESPACES
        and "air_learning_feedback_by_entry" in PERSISTENT_STATE_NAMESPACES,
        "air learning feedback namespaces are protected from ordinary retention purge",
    )

    check(
        route_allowed("GET", "/mina-jobs/job-1/air-learning-feedback")
        and route_allowed("POST", "/mina-jobs/job-1/air-learning-feedback")
        and route_allowed("POST", "/mina-jobs/job-1/derive-air-learning")
        and route_allowed("POST", "/air-rate-table-reviews/rev/rows/row/learning-advisory"),
        "pilot access admits bounded air feedback derivation and advisory routes",
    )

    # Controlled API uses authenticated identity and remains authority-free.
    from src import api
    from src.core.mina_job_repository import InMemoryMinaJobRepository
    from src.core.quote_case_repository import InMemoryQuoteCaseRepository
    from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
    from src.core.quote_approval_service import approve_quote
    from src.core.quote_manual_sent import record_customer_quote_manually_sent
    from src.core.mina_job_service import transition_mina_job_stage

    api_setup = _setup()
    api_source_repo = api_setup[0]
    api_customer_repo, api_customer = _customer_repo()
    api_validity = _validity_repo(api_source_repo)
    api_availability = _availability_repo(api_source_repo, expected_delivery_date=date(2026, 9, 17))
    api_jobs = InMemoryMinaJobRepository()
    api_cases = InMemoryQuoteCaseRepository()
    api_approvals = InMemoryQuoteApprovalRepository()
    api_job = _job(
        api_jobs, key="air-p244-api",
        shipment=_shipment(required_delivery_date="2026-09-18"),
        opened_at=datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc),
    )
    api_prepared = _prepare(
        setup=api_setup, customer_repo=api_customer_repo, customer=api_customer,
        job_repo=api_jobs, job=api_job, cases=api_cases, approvals=api_approvals,
        availability_repo=api_availability, validity_repo=api_validity,
        prepared_at=datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc),
    )
    api_case = api_prepared.quote_case; api_approval = api_prepared.quote_approval
    assert api_case is not None and api_approval is not None
    api_approved = approve_quote(
        repository=api_approvals, approval_id=api_approval.approval_id,
        approved_by="API Approval", approved_at=datetime(2026, 9, 14, 9, 35, tzinfo=timezone.utc),
        quote_case_repository=api_cases,
    )
    record_customer_quote_manually_sent(
        quote_case_repository=api_cases, approval_repository=api_approvals,
        case_id=api_case.case_id, expected_approval_id=api_approved.approval_id,
        recipient_email="air.api@example.com", sent_by="API Sender",
        sent_at=datetime(2026, 9, 14, 9, 40, tzinfo=timezone.utc), mina_job_repository=api_jobs,
    )
    api_current = api_jobs.get(api_job.job_id); assert api_current is not None
    transition_mina_job_stage(
        repository=api_jobs, mina_code=api_current.mina_code, target_stage="accepted",
        actor="API Sales", occurred_at=datetime(2026, 9, 14, 9, 45, tzinfo=timezone.utc),
    )
    api_handoffs = InMemoryAirOperationHandoffRepository()
    api_handoff = prepare_air_operation_handoff(
        job_id=api_job.job_id, handed_off_by="API Ops", handoff_repository=api_handoffs,
        mina_repository=api_jobs, quote_case_repository=api_cases, approval_repository=api_approvals,
        handed_off_at=datetime(2026, 9, 14, 9, 50, tzinfo=timezone.utc),
    ).handoff
    api_feedback_repo = InMemoryAirLearningFeedbackRepository()
    api_learning_repo = InMemoryLearningFactRepository()
    originals = (
        api.mina_job_repository, api.air_operation_handoff_repository,
        api.air_learning_feedback_repository, api.learning_fact_repository,
        api.air_rate_table_review_repository, api.air_shadow_repository,
    )
    try:
        api.mina_job_repository = api_jobs
        api.air_operation_handoff_repository = api_handoffs
        api.air_learning_feedback_repository = api_feedback_repo
        api.learning_fact_repository = api_learning_repo
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        request.state.pilot_operator = "Authenticated Air Learning Operator"
        response = api.record_mina_job_air_learning_feedback(
            api_job.job_id,
            api.AirLearningFeedbackRequest(
                entry_id="api-air-feedback", tariff_usage="used_as_quoted",
                actual_airline_name="THY", actual_routing_context="direct",
                actual_service_date=date(2026, 9, 16), actual_delivery_date=date(2026, 9, 17),
                actual_chargeable_weight_kg=Decimal("301"),
                actual_cost_amount=Decimal("950"), actual_cost_currency="USD",
                correction_categories=[], evidence_source="airline_invoice",
                source_reference="API-INV-1", note="API explicit outcome evidence",
            ),
            request,
        )
        recorded = api_feedback_repo.find_by_entry("api-air-feedback")
        # Use a source fixture whose immutable SHA exactly matches the table review.
        from src.core.air_shadow import AirRateSource
        from src.core.air_shadow_repository import InMemoryAirShadowRepository
        advisory_source_repo = InMemoryAirShadowRepository()
        source = api_setup[0].get_rate_source("source-0001"); assert source is not None
        advisory_source_repo.create_rate_source(AirRateSource.model_validate(
            source.model_copy(update={
                "entry_id": "p244-advisory-source", "sha256_hex": "a" * 64,
            }).model_dump()
        ))
        api.air_rate_table_review_repository = _table_repo()
        api.air_shadow_repository = advisory_source_repo
        advisory_response = api.preview_air_learning_advisory(
            "table-review-0001", "table-row-fra-0001",
            api.AirLearningAdvisoryRequest(routing_context="direct"),
        )
    finally:
        (
            api.mina_job_repository, api.air_operation_handoff_repository,
            api.air_learning_feedback_repository, api.learning_fact_repository,
            api.air_rate_table_review_repository, api.air_shadow_repository,
        ) = originals
    check(
        recorded is not None and recorded.recorded_by == "Authenticated Air Learning Operator"
        and response["pricing_authority_created"] is False
        and response["booking_authority_created"] is False
        and advisory_response["confirmed_fact_count"] == 0
        and advisory_response["advisory_only"] is True,
        "controlled API captures authenticated air outcome evidence and returns advisory-only learning",
    )

    root = Path(__file__).resolve().parents[2]
    service_text = (root / "src" / "core" / "air_learning_service.py").read_text(encoding="utf-8")
    ui_text = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "calculate_customer_quote" not in service_text
        and "dispatch_outbound_mail" not in service_text
        and "booking" not in "\n".join(
            line for line in service_text.splitlines() if line.lstrip().startswith("from ")
        ),
        "air learning service has no pricing outbound or booking execution dependency",
    )
    check(
        "Havayolu Öğrenme Geri Beslemesi" in ui_text
        and "Air Learning Advisory Göster" in ui_text
        and "CONFIRMED OLSA BİLE ADVISORY ONLY" in ui_text
        and "pricing/tariff/routing/booking authority yok" in ui_text,
        "browser exposes air feedback review and confirmed advisory without presenting learning as execution authority",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_learning_feedback_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir learning feedback regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
