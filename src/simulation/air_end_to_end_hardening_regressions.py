from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.air_additional_cost_evidence_repository import InMemoryAirAdditionalCostEvidenceRepository
from src.core.air_additional_cost_evidence_service import record_air_additional_cost_evidence
from src.core.air_cost_scope_review import AIR_COST_SCOPE_CATEGORIES
from src.core.air_cost_scope_review_repository import InMemoryAirCostScopeReviewRepository
from src.core.air_cost_scope_review_service import record_air_cost_scope_review
from src.core.air_fx_rate_evidence_repository import InMemoryAirFxRateEvidenceRepository
from src.core.air_learning_feedback_repository import InMemoryAirLearningFeedbackRepository
from src.core.air_learning_service import derive_air_route_learning, record_air_learning_feedback
from src.core.air_operation_handoff_repository import InMemoryAirOperationHandoffRepository
from src.core.air_operation_handoff_service import AirOperationHandoffTransitionError, prepare_air_operation_handoff
from src.core.air_quote_preparation import AirQuotePreparationTransitionError, prepare_air_quote_case
from src.core.air_rate_document_store import AirRateDocumentStore
from src.core.air_rate_source_service import register_commercial_air_rate_pdf
from src.core.air_rate_structure_review_repository import InMemoryAirRateStructureReviewRepository
from src.core.air_rate_structure_review_service import create_air_rate_structure_review, decide_air_rate_structure_candidate
from src.core.air_rate_table_review_repository import InMemoryAirRateTableReviewRepository
from src.core.air_rate_table_review_service import create_air_rate_table_review, decide_air_rate_table_row
from src.core.air_rate_surcharge_review import AirRateSurchargeReview
from src.core.air_rate_surcharge_review_repository import InMemoryAirRateSurchargeReviewRepository
from src.core.air_rate_surcharge_review_service import (
    create_air_rate_surcharge_review,
    decide_air_rate_surcharge_candidate,
    decide_air_rate_surcharge_application_basis,
    decide_air_rate_surcharge_applicability_scope,
    decide_air_rate_surcharge_operational_conditions,
    decide_air_rate_surcharge_flat_quantity_basis,
)
from src.core.air_rate_validity_review_repository import InMemoryAirRateValidityReviewRepository
from src.core.air_rate_validity_review_service import review_air_rate_validity
from src.core.air_rate_weight_rounding_review_repository import InMemoryAirRateWeightRoundingReviewRepository
from src.core.air_rate_weight_rounding_review_service import review_air_rate_weight_rounding
from src.core.air_reviewed_surcharge_cost_preview import AirReviewedSurchargeCostPreviewError, build_air_reviewed_surcharge_cost_preview
from src.core.air_service_availability_repository import InMemoryAirServiceAvailabilityRepository
from src.core.air_service_availability_service import record_air_service_availability_confirmation
from src.core.air_shadow_repository import InMemoryAirShadowRepository
from src.core.air_unsupported_cost_semantics_review import AIR_UNSUPPORTED_COST_SEMANTICS
from src.core.air_unsupported_cost_semantics_review_repository import InMemoryAirUnsupportedCostSemanticsReviewRepository
from src.core.air_unsupported_cost_semantics_review_service import record_air_unsupported_cost_semantics_review
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import create_manual_mina_job, transition_mina_job_stage
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_approval_service import approve_quote
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.quote_manual_sent import record_customer_quote_manually_sent
from src.simulation.air_quote_readiness_preview_regressions import _customer_repo, _shipment
from src.simulation.attachment_safe_extraction_regressions import _pdf_with_text


SERVICE_DATE = date(2026, 9, 16)
EXPECTED_DELIVERY = date(2026, 9, 17)
PDF_TEXT = """GENERAL CARGO USD MIN +45 +100 +300 +500 +1000
VOLUMETRIC / 6000
FSC SECURITY HANDLING
FRA 120.00 2.50 2.30 2.10 1.90 1.70
FSC USD 0.50 / KG
SECURITY USD 0.10 / KG
HANDLING USD 25 / SHIPMENT
"""


def _scope_requirements():
    return [
        {
            "category": category,
            "status": "required" if category in {"pickup", "delivery"} else "not_applicable",
            "rationale": f"P2-45 explicit {category} scope classification.",
        }
        for category in AIR_COST_SCOPE_CATEGORIES
    ]


def _semantic_requirements():
    return [
        {"semantic": semantic, "status": "not_applicable", "rationale": f"P2-45 reviewed {semantic}."}
        for semantic in AIR_UNSUPPORTED_COST_SEMANTICS
    ]


def _build_reviewed_pdf_chain(root: Path):
    docs = AirRateDocumentStore(root / "air-docs")
    sources = InMemoryAirShadowRepository()
    structures = InMemoryAirRateStructureReviewRepository()
    tables = InMemoryAirRateTableReviewRepository()
    surcharges = InMemoryAirRateSurchargeReviewRepository()
    pdf = _pdf_with_text(PDF_TEXT)
    source, created = register_commercial_air_rate_pdf(
        repository=sources,
        document_store=docs,
        entry_id="p245-thy-ada-fra-sep",
        airline_name="THY",
        document_name="thy-ada-fra-september.pdf",
        content_type="application/pdf",
        content=pdf,
        cargo_scope="general_cargo",
        origin_airport="ADA",
        valid_from=date(2026, 9, 1),
        valid_to=date(2026, 9, 30),
        recorded_by="P2-45 Tariff Operator",
    )
    structure, _ = create_air_rate_structure_review(
        source_id=source.source_id,
        source_repository=sources,
        review_repository=structures,
        document_store=docs,
        requested_by="P2-45 Tariff Operator",
    )
    for candidate in list(structure.candidates):
        structure = decide_air_rate_structure_candidate(
            review_id=structure.review_id,
            candidate_id=candidate.candidate_id,
            decision="confirm",
            review_note="P2-45 visible PDF structure confirmed.",
            reviewed_by="P2-45 Senior Air Operator",
            repository=structures,
            reviewed_at=datetime(2026, 9, 14, 9, 10, tzinfo=timezone.utc),
        )
    table, _ = create_air_rate_table_review(
        source_id=source.source_id,
        source_repository=sources,
        structure_repository=structures,
        review_repository=tables,
        document_store=docs,
        requested_by="P2-45 Tariff Operator",
    )
    for candidate in list(table.candidates):
        table = decide_air_rate_table_row(
            review_id=table.review_id,
            candidate_id=candidate.candidate_id,
            decision="confirm" if candidate.destination_code == "FRA" else "reject",
            review_note="P2-45 tariff row checked against PDF.",
            reviewed_by="P2-45 Senior Air Operator",
            repository=tables,
            reviewed_at=datetime(2026, 9, 14, 9, 20, tzinfo=timezone.utc),
        )
    row = next(item for item in table.candidates if item.destination_code == "FRA" and item.status == "confirmed")
    surcharge, _ = create_air_rate_surcharge_review(
        source_id=source.source_id,
        source_repository=sources,
        structure_repository=structures,
        review_repository=surcharges,
        document_store=docs,
        requested_by="P2-45 Tariff Operator",
    )
    for candidate in list(surcharge.candidates):
        surcharge = decide_air_rate_surcharge_candidate(
            review_id=surcharge.review_id,
            candidate_id=candidate.candidate_id,
            decision="confirm",
            review_note="P2-45 surcharge amount/currency/unit checked.",
            reviewed_by="P2-45 Senior Air Operator",
            repository=surcharges,
            reviewed_at=datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc),
        )
        application_basis = "flat" if candidate.basis == "flat" else "chargeable_weight"
        surcharge = decide_air_rate_surcharge_application_basis(
            review_id=surcharge.review_id,
            candidate_id=candidate.candidate_id,
            application_basis=application_basis,
            review_note="P2-45 application basis checked.",
            reviewed_by="P2-45 Senior Air Operator",
            repository=surcharges,
            reviewed_at=datetime(2026, 9, 14, 9, 31, tzinfo=timezone.utc),
        )
        surcharge = decide_air_rate_surcharge_applicability_scope(
            review_id=surcharge.review_id,
            candidate_id=candidate.candidate_id,
            applicability_scope="source_wide",
            destination_code=None,
            review_note="P2-45 source-wide scope checked.",
            reviewed_by="P2-45 Senior Air Operator",
            repository=surcharges,
            table_repository=tables,
            reviewed_at=datetime(2026, 9, 14, 9, 32, tzinfo=timezone.utc),
        )
        surcharge = decide_air_rate_surcharge_operational_conditions(
            review_id=surcharge.review_id,
            candidate_id=candidate.candidate_id,
            cargo_applicability="source_scope",
            routing_applicability="direct_only",
            via_airport=None,
            review_note="P2-45 direct general-cargo condition checked.",
            reviewed_by="P2-45 Senior Air Operator",
            repository=surcharges,
            source_repository=sources,
            reviewed_at=datetime(2026, 9, 14, 9, 33, tzinfo=timezone.utc),
        )
        if candidate.basis == "flat":
            surcharge = decide_air_rate_surcharge_flat_quantity_basis(
                review_id=surcharge.review_id,
                candidate_id=candidate.candidate_id,
                flat_quantity_basis="per_shipment",
                review_note="P2-45 shipment quantity basis checked.",
                reviewed_by="P2-45 Senior Air Operator",
                repository=surcharges,
                reviewed_at=datetime(2026, 9, 14, 9, 34, tzinfo=timezone.utc),
            )
    return {
        "docs": docs, "pdf": pdf, "source": source, "sources": sources,
        "structures": structures, "structure": structure,
        "tables": tables, "table": table, "row": row,
        "surcharges": surcharges, "surcharge": surcharge, "created": created,
    }


def _shared_evidence(chain):
    validity = InMemoryAirRateValidityReviewRepository()
    review_air_rate_validity(
        source_id=chain["source"].source_id,
        valid_from=date(2026, 9, 1), valid_to=date(2026, 9, 30),
        review_note="P2-45 validity checked against PDF.",
        reviewed_by="P2-45 Senior Air Operator",
        source_repository=chain["sources"], repository=validity,
        reviewed_at=datetime(2026, 9, 14, 9, 40, tzinfo=timezone.utc),
    )
    rounding = InMemoryAirRateWeightRoundingReviewRepository()
    review_air_rate_weight_rounding(
        source_id=chain["source"].source_id,
        rounding_mode="none", increment_kg=None,
        review_note="P2-45 source explicitly has no extra weight rounding rule.",
        reviewed_by="P2-45 Senior Air Operator",
        source_repository=chain["sources"], repository=rounding,
        reviewed_at=datetime(2026, 9, 14, 9, 41, tzinfo=timezone.utc),
    )
    return validity, rounding


def _inquiry_evidence(chain, *, index: int, inquiry: str, service_date: date = SERVICE_DATE):
    scopes = chain["scopes"]
    semantics = chain["semantics"]
    additional = chain["additional"]
    availability = chain["availability"]
    scope, _ = record_air_cost_scope_review(
        source_id=chain["source"].source_id,
        entry_id=f"p245-scope-{index}", inquiry_reference=inquiry,
        requirements=_scope_requirements(), review_note="P2-45 inquiry cost scope complete.",
        reviewed_by="P2-45 Cost Operator", source_repository=chain["sources"], repository=scopes,
        reviewed_at=datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=index),
    )
    semantic, _ = record_air_unsupported_cost_semantics_review(
        source_id=chain["source"].source_id,
        entry_id=f"p245-semantics-{index}", inquiry_reference=inquiry,
        requirements=_semantic_requirements(), review_note="P2-45 unsupported semantics explicitly cleared.",
        reviewed_by="P2-45 Cost Operator", source_repository=chain["sources"], repository=semantics,
        reviewed_at=datetime(2026, 9, 14, 10, 10, tzinfo=timezone.utc) + timedelta(minutes=index),
    )
    pickup, _ = record_air_additional_cost_evidence(
        source_id=chain["source"].source_id, entry_id=f"p245-pickup-{index}", inquiry_reference=inquiry,
        cost_category="pickup", provider_name="Adana Pickup Co", amount=Decimal("80"), currency="USD",
        quantity_basis="per_shipment", evidence_source="email", evidence_reference=f"PICKUP-{index}",
        evidence_note="P2-45 pickup quote evidence.", recorded_by="P2-45 Cost Operator",
        source_repository=chain["sources"], repository=additional,
        recorded_at=datetime(2026, 9, 14, 10, 20, tzinfo=timezone.utc) + timedelta(minutes=index),
    )
    delivery, _ = record_air_additional_cost_evidence(
        source_id=chain["source"].source_id, entry_id=f"p245-delivery-{index}", inquiry_reference=inquiry,
        cost_category="delivery", provider_name="Frankfurt Delivery GmbH", amount=Decimal("120"), currency="USD",
        quantity_basis="per_shipment", evidence_source="email", evidence_reference=f"DELIVERY-{index}",
        evidence_note="P2-45 delivery quote evidence.", recorded_by="P2-45 Cost Operator",
        source_repository=chain["sources"], repository=additional,
        recorded_at=datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc) + timedelta(minutes=index),
    )
    confirmation, _ = record_air_service_availability_confirmation(
        source_id=chain["source"].source_id, entry_id=f"p245-availability-{index}", inquiry_reference=inquiry,
        destination_code="FRA", routing_context="direct", service_date=service_date,
        expected_delivery_date=(EXPECTED_DELIVERY if service_date == SERVICE_DATE else service_date + timedelta(days=1)),
        capacity_status="available", schedule_status="confirmed", flight_reference=f"TK-P245-{index}",
        evidence_channel="email", evidence_reference=f"AIRLINE-AVAIL-{index}",
        evidence_note="P2-45 capacity and schedule explicitly confirmed.", confirmed_by="P2-45 Air Operator",
        source_repository=chain["sources"], repository=availability,
        confirmed_at=datetime(2026, 9, 14, 10, 40, tzinfo=timezone.utc) + timedelta(minutes=index),
    )
    return scope, semantic, pickup, delivery, confirmation


def _prepare(chain, *, jobs, cases, approvals, customer_repo, customer, index: int, inquiry: str,
             shipment=None, service_date: date = SERVICE_DATE, evidence=None):
    scope, semantic, pickup, delivery, _confirmation = evidence or _inquiry_evidence(
        chain, index=index, inquiry=inquiry, service_date=service_date
    )
    opened = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc) + timedelta(minutes=index)
    job = create_manual_mina_job(
        repository=jobs, manual_intake_id=f"p245-job-{index}-{inquiry}", intake_channel="email",
        job_kind="price_request", shipment=shipment or _shipment(required_delivery_date="2026-09-18"),
        opened_by="P2-45 Intake Operator", opened_at=opened,
    )
    prepared = prepare_air_quote_case(
        job_id=job.job_id, review_id=chain["table"].review_id,
        candidate_id=chain["row"].candidate_id, cost_scope_review_id=scope.review_id,
        unsupported_cost_semantics_review_id=semantic.review_id, inquiry_reference=inquiry,
        customer_id=customer.customer_id, service_date=service_date, cargo_context="general_cargo",
        routing_context="direct", shipment_count=1,
        additional_cost_evidence_ids=[pickup.evidence_id, delivery.evidence_id],
        prepared_by="P2-45 Pricing Operator",
        mina_job_repository=jobs, quote_case_repository=cases, approval_repository=approvals,
        table_repository=chain["tables"], structure_repository=chain["structures"],
        surcharge_repository=chain["surcharges"], source_repository=chain["sources"],
        scope_repository=chain["scopes"], unsupported_semantics_repository=chain["semantics"],
        additional_cost_repository=chain["additional"], rounding_repository=chain["rounding"],
        validity_repository=chain["validity"], availability_repository=chain["availability"],
        fx_repository=chain["fx"], master_data_repository=customer_repo,
        learning_fact_repository=chain["learning"], environ={},
        prepared_at=datetime(2026, 9, 14, 11, 0, tzinfo=timezone.utc) + timedelta(minutes=index),
    )
    return job, prepared


def _accept_handoff(chain, *, jobs, cases, approvals, job, prepared, index: int):
    case = prepared.quote_case
    approval = prepared.quote_approval
    assert case is not None and approval is not None
    base = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc) + timedelta(minutes=20 * index)
    approved = approve_quote(
        repository=approvals, approval_id=approval.approval_id,
        approved_by="P2-45 Approval Operator", approved_at=base,
        quote_case_repository=cases,
    )
    record_customer_quote_manually_sent(
        quote_case_repository=cases, approval_repository=approvals, case_id=case.case_id,
        expected_approval_id=approved.approval_id, recipient_email="air.customer@example.com",
        sent_by="P2-45 Send Operator", sent_at=base + timedelta(minutes=2), mina_job_repository=jobs,
    )
    current = jobs.get(job.job_id)
    assert current is not None
    transition_mina_job_stage(
        repository=jobs, mina_code=current.mina_code, target_stage="accepted",
        actor="P2-45 Sales Operator", occurred_at=base + timedelta(minutes=4),
    )
    result = prepare_air_operation_handoff(
        job_id=job.job_id, handed_off_by="P2-45 Air Ops",
        handoff_repository=chain["handoffs"], mina_repository=jobs,
        quote_case_repository=cases, approval_repository=approvals,
        handed_off_at=base + timedelta(minutes=6),
    )
    return result.handoff


def evaluate_air_end_to_end_hardening_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    with TemporaryDirectory(prefix="minai-air-p245-") as td:
        chain = _build_reviewed_pdf_chain(Path(td))
        validity, rounding = _shared_evidence(chain)
        chain.update({
            "validity": validity, "rounding": rounding,
            "scopes": InMemoryAirCostScopeReviewRepository(),
            "semantics": InMemoryAirUnsupportedCostSemanticsReviewRepository(),
            "additional": InMemoryAirAdditionalCostEvidenceRepository(),
            "availability": InMemoryAirServiceAvailabilityRepository(),
            "fx": InMemoryAirFxRateEvidenceRepository(),
            "handoffs": InMemoryAirOperationHandoffRepository(),
            "feedback": InMemoryAirLearningFeedbackRepository(),
            "learning": InMemoryLearningFactRepository(),
        })
        source = chain["source"]
        check(
            chain["created"] and chain["docs"].path_for_sha256(source.sha256_hex).read_bytes() == chain["pdf"]
            and chain["structure"].source_sha256 == source.sha256_hex
            and chain["table"].source_sha256 == source.sha256_hex
            and chain["surcharge"].source_sha256 == source.sha256_hex
            and chain["table"].structure_review_id == chain["structure"].review_id
            and chain["surcharge"].structure_review_id == chain["structure"].review_id
            and chain["table"].extracted_text_sha256 == chain["surcharge"].extracted_text_sha256 == chain["structure"].extracted_text_sha256,
            "one stored PDF artifact carries exact source SHA and extraction lineage through structure table and surcharge review",
        )

        customer_repo, customer = _customer_repo()
        jobs = InMemoryMinaJobRepository(); cases = InMemoryQuoteCaseRepository(); approvals = InMemoryQuoteApprovalRepository()
        happy = []
        for i in range(1, 6):
            inquiry = f"AIR-P245-{i:03d}"
            evidence = _inquiry_evidence(chain, index=i, inquiry=inquiry)
            job, prepared = _prepare(
                chain, jobs=jobs, cases=cases, approvals=approvals,
                customer_repo=customer_repo, customer=customer, index=i, inquiry=inquiry, evidence=evidence,
            )
            check(
                prepared.status == "prepared" and prepared.readiness.quote_ready
                and prepared.quote_case is not None and prepared.quote_approval is not None
                and prepared.quote_case.air_quote_context is not None
                and prepared.quote_case.air_quote_context.source_sha256 == source.sha256_hex
                and prepared.quote_case.air_quote_context.inquiry_reference == inquiry
                and prepared.quote_case.supplier_quote is not None
                and prepared.quote_case.supplier_quote.cost == float(prepared.quote_case.air_quote_context.confirmed_cost_basis_amount),
                f"job {i} reaches durable quote readiness from its own inquiry-bound PDF cost and availability evidence",
            )
            handoff = _accept_handoff(chain, jobs=jobs, cases=cases, approvals=approvals, job=job, prepared=prepared, index=i)
            context = handoff.air_quote_context
            multiplier = [Decimal("1.00"), Decimal("1.05"), Decimal("0.98"), Decimal("1.02"), Decimal("1.04")][i-1]
            weight_multiplier = [Decimal("1.00"), Decimal("1.02"), Decimal("0.99"), Decimal("1.01"), Decimal("1.03")][i-1]
            corrected = i in {2, 5}
            feedback = record_air_learning_feedback(
                feedback_repository=chain["feedback"], handoff_repository=chain["handoffs"], mina_repository=jobs,
                job_id=job.job_id, entry_id=f"p245-feedback-{i}",
                tariff_usage="used_with_correction" if corrected else "used_as_quoted",
                actual_airline_name="THY", actual_routing_context="direct",
                actual_service_date=SERVICE_DATE, actual_delivery_date=EXPECTED_DELIVERY,
                actual_chargeable_weight_kg=context.quoted_chargeable_weight_kg * weight_multiplier,
                actual_cost_amount=context.confirmed_cost_basis_amount * multiplier,
                actual_cost_currency=context.confirmed_cost_basis_currency,
                correction_categories=["chargeable_weight"] if corrected else [],
                evidence_source="airline_invoice", source_reference=f"P245-INVOICE-{i}",
                note=f"P2-45 explicit realized air outcome {i}.", recorded_by="P2-45 Outcome Operator",
                occurred_at=datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=i),
            )
            check(
                feedback.quoted_air_context.preparation_key == context.preparation_key
                and feedback.quoted_air_context.source_sha256 == source.sha256_hex,
                f"job {i} outcome feedback preserves the exact accepted quote provenance",
            )
            happy.append((job, prepared, handoff, feedback))

        learned = derive_air_route_learning(
            job_id=happy[-1][0].job_id, feedback_repository=chain["feedback"],
            learning_repository=chain["learning"], created_by="P2-45 Learning Operator",
            occurred_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        )
        keys = {item["fact_key"] for item in learned["proposed_facts"]}
        check(
            learned["eligible_feedback_count"] == 5
            and "air.cost_basis_variance_median_percent" in keys
            and "air.chargeable_weight_variance_median_percent" in keys
            and "air.quoted_tariff_exact_use_rate_percent" in keys
            and "air.route_plan_unchanged_rate_percent" in keys
            and "air.expected_delivery_met_rate_percent" in keys
            and "air.frequent_correction_categories" in keys
            and learned["pricing_authority_created"] is False
            and learned["tariff_authority_created"] is False
            and learned["routing_authority_created"] is False
            and learned["booking_authority_created"] is False,
            "five independent inquiry-bound outcomes close the route-learning loop without creating execution authority",
        )
        check(
            all(not fact.runtime_authoritative for fact in chain["learning"].list_all()),
            "all P2-45 air learning proposals remain non-runtime-authoritative",
        )

        # Customer master isolation: authoritative job customer cannot borrow another customer policy.
        mismatch_evidence = _inquiry_evidence(chain, index=20, inquiry="AIR-P245-CUSTOMER-MISMATCH")
        mismatch_job, mismatch = _prepare(
            chain, jobs=jobs, cases=cases, approvals=approvals,
            customer_repo=customer_repo, customer=customer, index=20,
            inquiry="AIR-P245-CUSTOMER-MISMATCH",
            shipment=_shipment(customer_name="Different Customer", required_delivery_date="2026-09-18"),
            evidence=mismatch_evidence,
        )
        check(
            mismatch.status == "blocked" and "shipment_customer_mismatch" in mismatch.readiness.blockers
            and jobs.get(mismatch_job.job_id).quote_case_id is None,
            "customer identity mismatch cannot borrow a different customer pricing policy or create a quote case",
        )

        # Stale tariff: exact service date outside reviewed validity must fail before durable quote creation.
        stale_inquiry = "AIR-P245-STALE"
        stale_evidence = _inquiry_evidence(chain, index=21, inquiry=stale_inquiry, service_date=date(2026, 10, 1))
        stale_blocked = False
        before_cases = len(cases.list_all())
        try:
            _prepare(
                chain, jobs=jobs, cases=cases, approvals=approvals,
                customer_repo=customer_repo, customer=customer, index=21, inquiry=stale_inquiry,
                service_date=date(2026, 10, 1), evidence=stale_evidence,
                shipment=_shipment(cargo_ready_date="2026-09-30", required_delivery_date="2026-10-03"),
            )
        except AirQuotePreparationTransitionError as exc:
            stale_blocked = "air_rate_tariff_not_valid_for_reference_date" in str(exc)
        check(stale_blocked and len(cases.list_all()) == before_cases,
              "stale tariff cannot reach quote preparation and writes no durable quote case")

        # Cross-inquiry local cost reuse must fail closed.
        cross_scope, cross_sem, _cross_pickup, cross_delivery, _ = _inquiry_evidence(
            chain, index=22, inquiry="AIR-P245-CROSS-B"
        )
        foreign_pickup = happy[0][1].readiness.pricing_preview.cost_completeness.coverage_preview.cost_preview.additional_cost_evidence_ids_used[0]
        cross_blocked = False
        cross_job = create_manual_mina_job(
            repository=jobs, manual_intake_id="p245-cross-job", intake_channel="email", job_kind="price_request",
            shipment=_shipment(required_delivery_date="2026-09-18"), opened_by="P2-45 Intake Operator",
            opened_at=datetime(2026, 9, 14, 8, 30, tzinfo=timezone.utc),
        )
        try:
            prepare_air_quote_case(
                job_id=cross_job.job_id, review_id=chain["table"].review_id, candidate_id=chain["row"].candidate_id,
                cost_scope_review_id=cross_scope.review_id, unsupported_cost_semantics_review_id=cross_sem.review_id,
                inquiry_reference="AIR-P245-CROSS-B", customer_id=customer.customer_id, service_date=SERVICE_DATE,
                cargo_context="general_cargo", routing_context="direct", shipment_count=1,
                additional_cost_evidence_ids=[foreign_pickup, cross_delivery.evidence_id],
                prepared_by="P2-45 Pricing Operator", mina_job_repository=jobs, quote_case_repository=cases,
                approval_repository=approvals, table_repository=chain["tables"], structure_repository=chain["structures"],
                surcharge_repository=chain["surcharges"], source_repository=chain["sources"],
                scope_repository=chain["scopes"], unsupported_semantics_repository=chain["semantics"],
                additional_cost_repository=chain["additional"], rounding_repository=chain["rounding"],
                validity_repository=chain["validity"], availability_repository=chain["availability"],
                fx_repository=chain["fx"], master_data_repository=customer_repo, learning_fact_repository=chain["learning"], environ={},
                prepared_at=datetime(2026, 9, 14, 11, 30, tzinfo=timezone.utc),
            )
        except AirQuotePreparationTransitionError as exc:
            cross_blocked = "air_additional_cost_evidence_inquiry_mismatch" in str(exc)
        check(cross_blocked and jobs.get(cross_job.job_id).quote_case_id is None,
              "local-cost evidence cannot leak across air inquiry boundaries in the full preparation path")

        # Source SHA drift between current source and reviewed table/surcharge evidence must fail closed.
        drift_sources = InMemoryAirShadowRepository()
        drift_sources.create_rate_source(source.model_copy(update={
            "entry_id": "p245-drift-source", "sha256_hex": "f" * 64,
        }))
        source_drift_blocked = False
        try:
            build_air_reviewed_surcharge_cost_preview(
                review_id=chain["table"].review_id, candidate_id=chain["row"].candidate_id,
                actual_weight_kg=287, total_volume_cm3=960000,
                cargo_context="general_cargo", routing_context="direct", shipment_count=1,
                table_repository=chain["tables"], structure_repository=chain["structures"],
                surcharge_repository=chain["surcharges"], source_repository=drift_sources,
                rounding_repository=chain["rounding"],
            )
        except AirReviewedSurchargeCostPreviewError as exc:
            source_drift_blocked = str(exc) == "air_rate_table_review_source_mismatch"
        check(source_drift_blocked, "reviewed cost fails closed when current source SHA drifts from the reviewed tariff table")

        # Exact semantic duplicate local costs under different IDs must never double-count.
        dup_inquiry = "AIR-P245-DUP-LOCAL"
        dup_repo = InMemoryAirAdditionalCostEvidenceRepository()
        dup_ids = []
        for suffix in ("A", "B"):
            item, _ = record_air_additional_cost_evidence(
                source_id=source.source_id, entry_id=f"p245-dup-local-{suffix}", inquiry_reference=dup_inquiry,
                cost_category="pickup", provider_name="Same Pickup Co", amount=Decimal("80"), currency="USD",
                quantity_basis="per_shipment", evidence_source="email", evidence_reference="SAME-PICKUP-REF",
                evidence_note=f"Duplicate semantic test {suffix}.", recorded_by="P2-45 Cost Operator",
                source_repository=chain["sources"], repository=dup_repo,
                recorded_at=datetime(2026, 9, 14, 10, 50, tzinfo=timezone.utc),
            )
            dup_ids.append(item.evidence_id)
        dup_local_blocked = False
        try:
            build_air_reviewed_surcharge_cost_preview(
                review_id=chain["table"].review_id, candidate_id=chain["row"].candidate_id,
                actual_weight_kg=287, total_volume_cm3=960000, cargo_context="general_cargo", routing_context="direct",
                shipment_count=1, inquiry_reference=dup_inquiry, additional_cost_evidence_ids=dup_ids,
                table_repository=chain["tables"], structure_repository=chain["structures"],
                surcharge_repository=chain["surcharges"], source_repository=chain["sources"],
                additional_cost_repository=dup_repo, rounding_repository=chain["rounding"],
            )
        except AirReviewedSurchargeCostPreviewError as exc:
            dup_local_blocked = str(exc).startswith("duplicate_additional_cost_semantic_evidence:")
        check(dup_local_blocked, "different evidence IDs cannot double-count one exact semantic local-cost item")

        # Exact semantic duplicate surcharge candidates must never double-count.
        first_surcharge = next(item for item in chain["surcharge"].candidates if item.basis == "per_kg")
        duplicate_candidate = first_surcharge.model_copy(update={"candidate_id": "duplicate-fsc-0001"})
        duplicate_review = AirRateSurchargeReview.model_validate(chain["surcharge"].model_copy(update={
            "review_id": "p245-duplicate-surcharge-review",
            "candidates": [first_surcharge, duplicate_candidate],
            "status": "completed",
        }).model_dump())
        duplicate_surcharge_repo = InMemoryAirRateSurchargeReviewRepository()
        duplicate_surcharge_repo.create(duplicate_review)
        dup_surcharge_blocked = False
        try:
            build_air_reviewed_surcharge_cost_preview(
                review_id=chain["table"].review_id, candidate_id=chain["row"].candidate_id,
                actual_weight_kg=287, total_volume_cm3=960000, cargo_context="general_cargo", routing_context="direct",
                shipment_count=1, table_repository=chain["tables"], structure_repository=chain["structures"],
                surcharge_repository=duplicate_surcharge_repo, source_repository=chain["sources"],
                rounding_repository=chain["rounding"],
            )
        except AirReviewedSurchargeCostPreviewError as exc:
            dup_surcharge_blocked = str(exc).startswith("duplicate_applicable_surcharge_semantic:")
        check(dup_surcharge_blocked, "different candidate IDs cannot double-count one exact applicable surcharge semantic")

        # Approval snapshot tampering must stop the accepted-to-operation handoff.
        tamper_inquiry = "AIR-P245-TAMPER"
        tamper_evidence = _inquiry_evidence(chain, index=23, inquiry=tamper_inquiry)
        tamper_job, tamper_prepared = _prepare(
            chain, jobs=jobs, cases=cases, approvals=approvals, customer_repo=customer_repo, customer=customer,
            index=23, inquiry=tamper_inquiry, evidence=tamper_evidence,
        )
        tcase = tamper_prepared.quote_case; tapproval = tamper_prepared.quote_approval
        assert tcase is not None and tapproval is not None and tcase.air_quote_context is not None
        base = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)
        approved = approve_quote(
            repository=approvals, approval_id=tapproval.approval_id, approved_by="P2-45 Approval Operator",
            approved_at=base, quote_case_repository=cases,
        )
        record_customer_quote_manually_sent(
            quote_case_repository=cases, approval_repository=approvals, case_id=tcase.case_id,
            expected_approval_id=approved.approval_id, recipient_email="air.customer@example.com",
            sent_by="P2-45 Send Operator", sent_at=base + timedelta(minutes=2), mina_job_repository=jobs,
        )
        current = jobs.get(tamper_job.job_id); assert current is not None
        transition_mina_job_stage(
            repository=jobs, mina_code=current.mina_code, target_stage="accepted",
            actor="P2-45 Sales Operator", occurred_at=base + timedelta(minutes=4),
        )
        current_case = cases.get(tcase.case_id); assert current_case is not None and current_case.air_quote_context is not None
        bad_context = current_case.air_quote_context.model_copy(update={
            "customer_final_price": current_case.air_quote_context.customer_final_price + Decimal("1")
        })
        cases.save(current_case.model_copy(update={"air_quote_context": bad_context}))
        tamper_blocked = False
        try:
            prepare_air_operation_handoff(
                job_id=tamper_job.job_id, handed_off_by="P2-45 Air Ops",
                handoff_repository=chain["handoffs"], mina_repository=jobs,
                quote_case_repository=cases, approval_repository=approvals,
                handed_off_at=base + timedelta(minutes=6),
            )
        except AirOperationHandoffTransitionError as exc:
            tamper_blocked = str(exc) == "air_operation_handoff_air_context_snapshot_mismatch"
        check(tamper_blocked and chain["handoffs"].find_by_job(tamper_job.job_id) is None,
              "accepted quote cannot hand off after frozen air context diverges from its approved snapshot")

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_end_to_end_hardening_regressions()
    for label in result["passes"]: print(f"PASS {label}")
    for label in result["failures"]: print(f"FAIL {label}")
    print("\nAir end-to-end pilot hardening regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
