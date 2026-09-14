from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from starlette.requests import Request

from src.core.air_fx_rate_evidence_repository import InMemoryAirFxRateEvidenceRepository
from src.core.air_quote_preparation import (
    AirQuotePreparationTransitionError,
    prepare_air_quote_case,
)
from src.core.air_service_availability_repository import InMemoryAirServiceAvailabilityRepository
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import create_manual_mina_job
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.pricing_policy import PricingFormula
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.quote_revision_service import revise_quote_case
from src.core.regulatory_compliance import RegulatoryComplianceAssessment
from src.core.sqlite_repositories import (
    SQLiteMinaJobRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
)
from src.simulation.air_additional_cost_consumption_regressions import _simple_surcharges
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo
from src.simulation.air_quote_readiness_preview_regressions import (
    INQUIRY,
    NOW,
    SERVICE_DATE,
    _availability_repo,
    _customer_repo,
    _shipment,
    _validity_repo,
)
from src.simulation.air_cost_completeness_preview_regressions import _rounding_repo, _setup


def _job(repository, *, shipment=None, job_kind="price_request", key="air-p242", opened_at=NOW):
    return create_manual_mina_job(
        repository=repository,
        manual_intake_id=key,
        intake_channel="email",
        job_kind=job_kind,
        shipment=shipment or _shipment(),
        opened_by="Air Intake Operator",
        opened_at=opened_at,
    )


def _prepare(*, setup, customer_repo, customer, job_repo, job, cases, approvals,
             availability_repo, validity_repo, prepared_by="Air Pricing Operator", **overrides):
    source_repo, scope_repo, scope, semantics_repo, semantics, additional_repo, pickup, delivery = setup
    payload = dict(
        job_id=job.job_id,
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        cost_scope_review_id=scope.review_id,
        unsupported_cost_semantics_review_id=semantics.review_id,
        inquiry_reference=INQUIRY,
        customer_id=customer.customer_id,
        service_date=SERVICE_DATE,
        cargo_context="general_cargo",
        routing_context="direct",
        shipment_count=1,
        additional_cost_evidence_ids=[pickup.evidence_id, delivery.evidence_id],
        prepared_by=prepared_by,
        prepared_at=datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc),
        mina_job_repository=job_repo,
        quote_case_repository=cases,
        approval_repository=approvals,
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=_simple_surcharges(),
        source_repository=source_repo,
        scope_repository=scope_repo,
        unsupported_semantics_repository=semantics_repo,
        additional_cost_repository=additional_repo,
        rounding_repository=_rounding_repo(),
        validity_repository=validity_repo,
        availability_repository=availability_repo,
        fx_repository=InMemoryAirFxRateEvidenceRepository(),
        master_data_repository=customer_repo,
        learning_fact_repository=None,
        environ={},
    )
    payload.update(overrides)
    return prepare_air_quote_case(**payload)


def evaluate_air_quote_preparation_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    setup = _setup()
    source_repo = setup[0]
    customer_repo, customer = _customer_repo()
    validity_repo = _validity_repo(source_repo)
    availability_repo = _availability_repo(source_repo)
    job_repo = InMemoryMinaJobRepository()
    job = _job(job_repo)
    cases = InMemoryQuoteCaseRepository()
    approvals = InMemoryQuoteApprovalRepository()

    prepared = _prepare(
        setup=setup, customer_repo=customer_repo, customer=customer,
        job_repo=job_repo, job=job, cases=cases, approvals=approvals,
        availability_repo=availability_repo, validity_repo=validity_repo,
    )
    case = prepared.quote_case
    approval = prepared.quote_approval
    linked = job_repo.get(job.job_id)
    check(
        prepared.status == "prepared" and prepared.created is True
        and case is not None and approval is not None
        and approval.approval_status == "pending"
        and linked is not None and linked.quote_case_id == case.case_id
        and linked.stage == "quote_ready",
        "quote-ready air job creates one durable QuoteCase pending human approval and links the MINA job",
    )
    check(
        case is not None
        and case.supplier_quote is not None
        and case.supplier_quote.price_source == "air_tariff_evidence"
        and case.supplier_quote.supplier_name == "THY"
        and case.customer_quote is not None
        and case.customer_quote.final_price == 1043.5
        and case.quote_draft is not None
        and "Havayolu Taşıma Teklifimiz" in case.quote_draft.subject
        and "Chargeable Ağırlık" in case.quote_draft.body,
        "air quote uses confirmed tariff cost basis and deterministic air-specific customer draft",
    )
    check(
        case is not None and case.air_quote_context is not None
        and approval is not None and approval.air_quote_context_snapshot is not None
        and approval.air_quote_context_snapshot == case.air_quote_context
        and case.air_quote_context.inquiry_reference == INQUIRY
        and case.air_quote_context.availability_confirmation_id is not None
        and case.air_quote_context.confirmed_cost_basis_amount > 0
        and case.air_quote_context.prepared_by == "Air Pricing Operator",
        "durable case and approval freeze the exact air readiness provenance snapshot",
    )
    check(
        case is not None and case.quote_send_safety is not None
        and case.quote_send_safety.can_send is False
        and case.quote_send_safety.block_reason == "approval_pending"
        and prepared.quote_send_authority is False
        and prepared.booking_authority is False
        and prepared.outbound_authority is False,
        "P2-42 creates no automatic send booking or outbound authority",
    )

    repeated = _prepare(
        setup=setup, customer_repo=customer_repo, customer=customer,
        job_repo=job_repo, job=job, cases=cases, approvals=approvals,
        availability_repo=availability_repo, validity_repo=validity_repo,
        prepared_by="Second Operator",
        prepared_at=datetime(2026, 9, 14, 13, 5, tzinfo=timezone.utc),
    )
    check(
        repeated.status == "existing" and repeated.created is False
        and repeated.quote_case is not None and case is not None
        and repeated.quote_case.case_id == case.case_id
        and repeated.quote_approval is not None and approval is not None
        and repeated.quote_approval.approval_id == approval.approval_id
        and len(cases.list_all()) == 1 and len(approvals.list_all()) == 1,
        "identical air preparation is idempotent and never duplicates QuoteCase or approval",
    )

    different_evidence_blocked = False
    try:
        _prepare(
            setup=setup, customer_repo=customer_repo, customer=customer,
            job_repo=job_repo, job=job, cases=cases, approvals=approvals,
            availability_repo=availability_repo, validity_repo=validity_repo,
            quote_pricing_override=PricingFormula(method="fixed_profit", value=200),
        )
    except AirQuotePreparationTransitionError as exc:
        different_evidence_blocked = str(exc) == "mina_job_quote_case_already_linked_to_different_evidence"
    check(
        different_evidence_blocked and len(cases.list_all()) == 1,
        "same MINA job cannot silently create a second quote case from different air evidence",
    )

    blocked_job_repo = InMemoryMinaJobRepository()
    blocked_job = _job(blocked_job_repo, key="air-p242-blocked")
    blocked_cases = InMemoryQuoteCaseRepository()
    blocked_approvals = InMemoryQuoteApprovalRepository()
    blocked = _prepare(
        setup=setup, customer_repo=customer_repo, customer=customer,
        job_repo=blocked_job_repo, job=blocked_job, cases=blocked_cases, approvals=blocked_approvals,
        availability_repo=InMemoryAirServiceAvailabilityRepository(), validity_repo=validity_repo,
    )
    blocked_job_after = blocked_job_repo.get(blocked_job.job_id)
    check(
        blocked.status == "blocked" and blocked.created is False
        and blocked.quote_case is None and blocked.quote_approval is None
        and blocked_job_after is not None and blocked_job_after.quote_case_id is None
        and blocked_job_after.stage == "inquiry_confirmed"
        and blocked_cases.list_all() == [] and blocked_approvals.list_all() == [],
        "failed air readiness writes no QuoteCase approval or MINA stage transition",
    )

    approved_job_repo = InMemoryMinaJobRepository()
    approved_job = _job(approved_job_repo, job_kind="approved_job", key="air-p242-approved")
    approved_job_blocked = False
    try:
        _prepare(
            setup=setup, customer_repo=customer_repo, customer=customer,
            job_repo=approved_job_repo, job=approved_job,
            cases=InMemoryQuoteCaseRepository(), approvals=InMemoryQuoteApprovalRepository(),
            availability_repo=availability_repo, validity_repo=validity_repo,
        )
    except AirQuotePreparationTransitionError as exc:
        approved_job_blocked = str(exc) == "air_customer_quote_requires_price_request_job"
    check(approved_job_blocked, "approved-job intake cannot enter the customer air quote lifecycle")

    road_job_repo = InMemoryMinaJobRepository()
    road_job = _job(
        road_job_repo,
        shipment=_shipment(transport_mode="road"),
        key="air-p242-road",
    )
    road_blocked = False
    try:
        _prepare(
            setup=setup, customer_repo=customer_repo, customer=customer,
            job_repo=road_job_repo, job=road_job,
            cases=InMemoryQuoteCaseRepository(), approvals=InMemoryQuoteApprovalRepository(),
            availability_repo=availability_repo, validity_repo=validity_repo,
        )
    except AirQuotePreparationTransitionError as exc:
        road_blocked = str(exc) == "mina_job_transport_mode_must_be_air"
    check(road_blocked, "non-air MINA job cannot consume the air quote preparation path")

    regulatory_job_repo = InMemoryMinaJobRepository()
    regulatory_job = _job(regulatory_job_repo, key="air-p242-regulatory")
    regulatory_cases = InMemoryQuoteCaseRepository()
    regulatory_approvals = InMemoryQuoteApprovalRepository()
    regulatory_block = RegulatoryComplianceAssessment(
        status="blocked",
        can_continue_to_quote=False,
        requires_human_review=False,
        blocking_requirements=["synthetic_air_document"],
        reasons=["Synthetic future air document requirement."],
    )
    with patch("src.core.air_quote_readiness_preview.assess_regulatory_compliance", return_value=regulatory_block):
        regulatory = _prepare(
            setup=setup, customer_repo=customer_repo, customer=customer,
            job_repo=regulatory_job_repo, job=regulatory_job,
            cases=regulatory_cases, approvals=regulatory_approvals,
            availability_repo=availability_repo, validity_repo=validity_repo,
        )
    check(
        regulatory.status == "blocked"
        and regulatory.readiness.regulatory_compliance_clear is False
        and "regulatory:blocked:synthetic_air_document" in regulatory.readiness.blockers
        and regulatory_cases.list_all() == [] and regulatory_approvals.list_all() == [],
        "air quote readiness cannot bypass generic regulatory compliance before durable quote creation",
    )

    if case is not None and approval is not None:
        revised = revise_quote_case(
            quote_case_repository=cases,
            approval_repository=approvals,
            case_id=case.case_id,
            expected_approval_id=approval.approval_id,
            subject=case.quote_draft.subject + " · Revize",
            body=case.quote_draft.body + "\n\nOperatör notuyla revize edildi.",
            edited_by="Air Revision Operator",
            mina_job_repository=job_repo,
            master_data_repository=customer_repo,
            learning_fact_repository=None,
        )
        check(
            revised.quote_case.air_quote_context is not None
            and revised.new_approval.air_quote_context_snapshot is not None
            and revised.new_approval.air_quote_context_snapshot.preparation_key
            == revised.quote_case.air_quote_context.preparation_key
            == case.air_quote_context.preparation_key,
            "operator quote revision preserves the frozen air evidence lineage in the fresh approval snapshot",
        )

    with TemporaryDirectory(prefix="minai-air-quote-p242-") as tmp:
        store = SQLitePilotStore(Path(tmp) / "pilot.sqlite3", run_id="air-quote-p242")
        sqlite_jobs = SQLiteMinaJobRepository(store)
        sqlite_cases = SQLiteQuoteCaseRepository(store)
        sqlite_approvals = SQLiteQuoteApprovalRepository(store)
        sqlite_job = _job(sqlite_jobs, key="air-p242-sqlite")
        durable = _prepare(
            setup=setup, customer_repo=customer_repo, customer=customer,
            job_repo=sqlite_jobs, job=sqlite_job, cases=sqlite_cases, approvals=sqlite_approvals,
            availability_repo=availability_repo, validity_repo=validity_repo,
        )
        reopened_jobs = SQLiteMinaJobRepository(store)
        reopened_cases = SQLiteQuoteCaseRepository(store)
        reopened_approvals = SQLiteQuoteApprovalRepository(store)
        saved_job = reopened_jobs.get(sqlite_job.job_id)
        saved_case = None if saved_job is None or saved_job.quote_case_id is None else reopened_cases.get(saved_job.quote_case_id)
        saved_approval = None if saved_case is None or saved_case.quote_approval is None else reopened_approvals.get(saved_case.quote_approval.approval_id)
        check(
            durable.created is True and saved_job is not None and saved_case is not None and saved_approval is not None
            and saved_case.air_quote_context is not None
            and saved_approval.air_quote_context_snapshot is not None
            and saved_case.air_quote_context.preparation_key == saved_approval.air_quote_context_snapshot.preparation_key,
            "air quote case approval provenance and MINA link survive SQLite repository reconstruction",
        )

    from src import api
    api_job_repo = InMemoryMinaJobRepository()
    api_job = _job(api_job_repo, key="air-p242-api", opened_at=datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc))
    api_cases = InMemoryQuoteCaseRepository()
    api_approvals = InMemoryQuoteApprovalRepository()
    api_learning = InMemoryLearningFactRepository()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Quote Operator"
    originals = (
        api.mina_job_repository, api.quote_case_repository, api.quote_approval_repository,
        api.air_rate_table_review_repository, api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository, api.air_shadow_repository,
        api.air_cost_scope_review_repository, api.air_unsupported_cost_semantics_review_repository,
        api.air_additional_cost_evidence_repository, api.air_rate_weight_rounding_review_repository,
        api.air_rate_validity_review_repository, api.air_service_availability_repository,
        api.air_fx_rate_evidence_repository, api.master_data_repository, api.learning_fact_repository,
    )
    try:
        (
            api.mina_job_repository, api.quote_case_repository, api.quote_approval_repository,
            api.air_rate_table_review_repository, api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository, api.air_shadow_repository,
            api.air_cost_scope_review_repository, api.air_unsupported_cost_semantics_review_repository,
            api.air_additional_cost_evidence_repository, api.air_rate_weight_rounding_review_repository,
            api.air_rate_validity_review_repository, api.air_service_availability_repository,
            api.air_fx_rate_evidence_repository, api.master_data_repository, api.learning_fact_repository,
        ) = (
            api_job_repo, api_cases, api_approvals,
            _table_repo(), _structure_repo(), _simple_surcharges(), setup[0], setup[1], setup[3],
            setup[5], _rounding_repo(), validity_repo, availability_repo,
            InMemoryAirFxRateEvidenceRepository(), customer_repo, api_learning,
        )
        api_response = api.prepare_mina_job_air_quote(
            api_job.job_id,
            api.AirQuotePreparationRequest(
                review_id="table-review-0001",
                candidate_id="table-row-fra-0001",
                cost_scope_review_id=setup[2].review_id,
                unsupported_cost_semantics_review_id=setup[4].review_id,
                inquiry_reference=INQUIRY,
                customer_id=customer.customer_id,
                service_date=SERVICE_DATE,
                cargo_context="general_cargo",
                routing_context="direct",
                shipment_count=1,
                additional_cost_evidence_ids=[setup[-2].evidence_id, setup[-1].evidence_id],
            ),
            request,
        )
    finally:
        (
            api.mina_job_repository, api.quote_case_repository, api.quote_approval_repository,
            api.air_rate_table_review_repository, api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository, api.air_shadow_repository,
            api.air_cost_scope_review_repository, api.air_unsupported_cost_semantics_review_repository,
            api.air_additional_cost_evidence_repository, api.air_rate_weight_rounding_review_repository,
            api.air_rate_validity_review_repository, api.air_service_availability_repository,
            api.air_fx_rate_evidence_repository, api.master_data_repository, api.learning_fact_repository,
        ) = originals
    check(
        api_response["status"] == "prepared"
        and api_response["quote_approval"]["approval_status"] == "pending"
        and api_response["quote_case"]["air_quote_context"]["prepared_by"] == "API Air Quote Operator"
        and api_response["quote_send_authority"] is False
        and api_response["booking_authority"] is False,
        "controlled API creates only authenticated pending air quote approval with no automatic send or booking",
    )

    check(
        route_allowed("POST", f"/mina-jobs/{job.job_id}/air-quote/prepare"),
        "pilot access admits the bounded durable air quote preparation route",
    )

    root = Path(__file__).resolve().parents[2]
    service = (root / "src" / "core" / "air_quote_preparation.py").read_text(encoding="utf-8")
    ui = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "openai" not in service.casefold()
        and "QuoteCase + Human Approval Hazırla" in ui
        and "HİÇBİR QUOTE CASE YAZILMADI" in ui
        and "Air Readiness Provenance · Frozen Snapshot" in ui
        and "SEND OTOMATİK DEĞİL" in ui,
        "browser exposes durable human-approval preparation and frozen air provenance without AI generation or auto-send semantics",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_quote_preparation_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir quote preparation regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
