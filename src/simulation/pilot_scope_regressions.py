from __future__ import annotations

import os
from unittest.mock import patch

from src.core.equipment import decide_equipment
from src.core.models import Package, Shipment
from src.core.risk import assess_risk
from src.core.pilot_scope import evaluate_pilot_scope
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
    SupplierRFQWorkflow,
)
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository


def _road_shipment(**updates) -> Shipment:
    shipment = Shipment(
        customer_name="Pilot Scope Regression",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=12000,
        service_type="FTL",
        transport_mode="road",
        cargo_ready_date="2026-09-15",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[
            Package(
                package_type="pallet",
                quantity=12,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    )
    return Shipment.model_validate({**shipment.model_dump(), **updates})


def _assert_excluded(
    failures: list[str],
    name: str,
    shipment: Shipment,
) -> None:
    decision = evaluate_pilot_scope(
        shipment,
        environ={"MINAI_PILOT_MODE": "1"},
    )
    if decision.eligible or decision.result_type != "pilot_scope_excluded":
        failures.append(f"pilot scope accepted excluded {name} cargo")
    if not decision.reasons:
        failures.append(f"pilot scope gave no reason for excluded {name} cargo")


def _mixed_currency_progression(failures: list[str]) -> None:
    from src.workflow.supplier_rfq_progression import (
        resume_supplier_rfq_workflow,
    )

    shipment = _road_shipment()
    repository = InMemorySupplierRFQRepository()
    workflow = SupplierRFQWorkflow(shipment=shipment)
    drafts = [
        SupplierRFQDraft(
            workflow_id=workflow.workflow_id,
            supplier_name="Pilot Supplier EUR",
            priority=1,
            subject="EUR RFQ",
            body="EUR RFQ body",
            status="responded",
        ),
        SupplierRFQDraft(
            workflow_id=workflow.workflow_id,
            supplier_name="Pilot Supplier USD",
            priority=2,
            subject="USD RFQ",
            body="USD RFQ body",
            status="responded",
        ),
    ]
    workflow.rfq_ids = [draft.rfq_id for draft in drafts]
    repository.save_workflow(workflow)
    repository.save_drafts(drafts)
    repository.save_responses(
        [
            SupplierRFQResponse(
                rfq_id=drafts[0].rfq_id,
                supplier_name=drafts[0].supplier_name,
                rfq_priority=drafts[0].priority,
                status="quoted",
                cost=1000,
                currency="EUR",
            ),
            SupplierRFQResponse(
                rfq_id=drafts[1].rfq_id,
                supplier_name=drafts[1].supplier_name,
                rfq_priority=drafts[1].priority,
                status="quoted",
                cost=1100,
                currency="USD",
            ),
        ]
    )
    supplier_selection = {
        "selected_suppliers": [
            {
                "supplier_name": draft.supplier_name,
                "priority": draft.priority,
                "route_score": 1.0,
                "equipment_score": 1.0,
                "risk_score": 1.0,
                "price_score": 0.8,
                "speed_score": 0.8,
                "total_score": 0.9,
            }
            for draft in drafts
        ],
        "rejected_suppliers": [],
        "source": "pilot_scope_regression",
    }
    approvals = InMemoryQuoteApprovalRepository()
    cases = InMemoryQuoteCaseRepository()

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        with patch(
            "src.workflow.supplier_rfq_progression.select_suppliers_for_shipment",
            return_value=supplier_selection,
        ):
            result = resume_supplier_rfq_workflow(
                workflow_id=workflow.workflow_id,
                rfq_repository=repository,
                approval_repository=approvals,
                quote_case_repository=cases,
            )

    if result.get("result_type") != "pilot_scope_excluded":
        failures.append("mixed-currency workflow did not fail closed")
    if result.get("supplier_quote_comparisons"):
        failures.append("mixed-currency workflow reached quote comparison")
    if any(
        result.get(key) is not None
        for key in (
            "supplier_quote_selection_decision",
            "supplier_quote",
            "customer_quote",
            "quote_approval",
            "quote_case",
        )
    ):
        failures.append("mixed-currency workflow created quote artifacts")
    if approvals.list_all() or cases.list_all():
        failures.append("mixed-currency workflow persisted quote artifacts")


def _transport_mode_confirmation_lifecycle(failures: list[str]) -> None:
    from src.core.extraction_confirmation import ShipmentProposalSnapshot
    from src.core.extraction_confirmation_repository import (
        InMemoryExtractionProposalRepository,
    )
    from src.core.mail import InboundMailEnvelope
    from src.workflow.extraction_confirmation import (
        ExtractionCorrectionError,
        confirm_extraction_proposal,
        create_extraction_proposal,
    )

    def create_unknown_transport_proposal(
        repository: InMemoryExtractionProposalRepository,
    ):
        proposed_shipment = ShipmentProposalSnapshot.model_validate(
            _road_shipment(transport_mode=None).model_dump()
        )
        return create_extraction_proposal(
            mail=InboundMailEnvelope(
                body_text="Privacy-safe synthetic road freight inquiry.",
                privacy_transformed=True,
            ),
            proposed_shipment=proposed_shipment,
            repository=repository,
        )

    corrected_repository = InMemoryExtractionProposalRepository()
    corrected_proposal = create_unknown_transport_proposal(
        corrected_repository
    )
    corrected = confirm_extraction_proposal(
        repository=corrected_repository,
        proposal_id=corrected_proposal.proposal_id,
        operator_identity="pilot-scope-regression-operator",
        corrections={"transport_mode": "road"},
    )
    if (
        corrected.confirmed_shipment is None
        or corrected.confirmed_shipment.transport_mode != "road"
    ):
        failures.append("transport mode correction was not confirmed as road")
    if corrected.operator_corrections.get("transport_mode") != "road":
        failures.append("transport mode was not recorded as an operator correction")
    if "transport_mode" not in corrected.changed_fields:
        failures.append("transport mode was not recorded as a changed field")
    if corrected.proposed_shipment.transport_mode is not None:
        failures.append("transport mode correction overwrote the original proposal")
    if corrected.confirmed_shipment is not None:
        corrected_decision = evaluate_pilot_scope(
            corrected.confirmed_shipment,
            environ={"MINAI_PILOT_MODE": "1"},
        )
        if not corrected_decision.eligible:
            failures.append(
                "confirmed road correction remained excluded from pilot scope"
            )

    uncorrected_repository = InMemoryExtractionProposalRepository()
    uncorrected_proposal = create_unknown_transport_proposal(
        uncorrected_repository
    )
    uncorrected = confirm_extraction_proposal(
        repository=uncorrected_repository,
        proposal_id=uncorrected_proposal.proposal_id,
        operator_identity="pilot-scope-regression-operator",
    )
    if (
        uncorrected.confirmed_shipment is None
        or uncorrected.confirmed_shipment.transport_mode is not None
    ):
        failures.append("uncorrected unknown transport mode was not preserved")
    elif evaluate_pilot_scope(
        uncorrected.confirmed_shipment,
        environ={"MINAI_PILOT_MODE": "1"},
    ).eligible:
        failures.append("uncorrected unknown transport mode did not fail closed")

    invalid_repository = InMemoryExtractionProposalRepository()
    invalid_proposal = create_unknown_transport_proposal(invalid_repository)
    try:
        confirm_extraction_proposal(
            repository=invalid_repository,
            proposal_id=invalid_proposal.proposal_id,
            operator_identity="pilot-scope-regression-operator",
            corrections={"transport_mode": "space"},
        )
    except ExtractionCorrectionError:
        pass
    else:
        failures.append("invalid transport mode correction was accepted")


def evaluate_pilot_scope_regressions() -> dict:
    failures: list[str] = []

    excluded_cases = {
        "ADR": _road_shipment(is_adr=True, adr_class="3"),
        "reefer": _road_shipment(
            is_temperature_controlled=True,
            temperature_requirement="+4C",
        ),
        "temperature requirement": _road_shipment(
            temperature_requirement="+4C",
        ),
        "medical": _road_shipment(commodity="Medikal Ürün"),
        "medical alias": _road_shipment(commodity="Medical device supplies"),
        "pharmaceutical": _road_shipment(commodity="İlaç / Pharma"),
        "chemical": _road_shipment(commodity="Kimyasal Ürün"),
        "chemical alias": _road_shipment(commodity="Industrial chemicals"),
        "oversize": _road_shipment(
            packages=[
                Package(
                    package_type="machine",
                    quantity=1,
                    width_cm=260,
                    height_cm=320,
                    weight_kg=5000,
                ).model_dump()
            ]
        ),
        "project": _road_shipment(
            special_notes="Project cargo / lowbed operation",
        ),
        "multimodal": _road_shipment(transport_mode="multimodal"),
        "unknown transport mode": _road_shipment(transport_mode=None),
    }
    for name, shipment in excluded_cases.items():
        _assert_excluded(failures, name, shipment)

    eligible = evaluate_pilot_scope(
        _road_shipment(),
        environ={"MINAI_PILOT_MODE": "1"},
    )
    if not eligible.eligible or eligible.result_type != "pilot_scope_eligible":
        failures.append("simple road freight was blocked by pilot scope")

    unknown_value = evaluate_pilot_scope(
        _road_shipment(is_high_value=None),
        environ={"MINAI_PILOT_MODE": "1"},
    )
    if not unknown_value.eligible:
        failures.append("unknown cargo value blocked otherwise eligible road freight")

    high_value_shipment = _road_shipment(
        is_high_value=True,
        equipment_type="Tenteli",
    )
    high_value_scope = evaluate_pilot_scope(
        high_value_shipment,
        environ={"MINAI_PILOT_MODE": "1"},
    )
    if not high_value_scope.eligible:
        failures.append("confirmed high-value cargo was treated as an automatic pilot-scope exclusion")

    high_value_risk = assess_risk(high_value_shipment)
    if (
        high_value_risk.risk_level != "yellow"
        or not high_value_risk.requires_human_review
        or high_value_risk.requires_management_review
        or not any("yüksek değerli" in reason.lower() for reason in high_value_risk.risk_reasons)
    ):
        failures.append("confirmed high-value cargo did not become a non-management review signal")

    if decide_equipment(high_value_shipment).selected_equipment != "Tenteli":
        failures.append("high-value signal silently overrode explicit customer equipment")

    from src.workflow.pipeline import process_shipment

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        blocked = process_shipment(_road_shipment(is_adr=True, adr_class="3"))
    if blocked.get("result_type") != "pilot_scope_excluded":
        failures.append("pipeline did not return pilot_scope_excluded for ADR")
    if blocked.get("supplier_rfq_drafts"):
        failures.append("excluded pilot shipment generated supplier RFQs")
    if any(
        blocked.get(key) is not None
        for key in (
            "supplier_quote",
            "customer_quote",
            "quote_approval",
            "quote_case",
        )
    ):
        failures.append("excluded pilot shipment generated quote artifacts")
    recommendation = blocked.get("action_recommendation")
    if (
        recommendation is None
        or recommendation.action_type != "pilot_scope_excluded"
    ):
        failures.append("excluded pilot shipment lacked scope action guidance")
    from src.api import serialize_result

    serialized_block = serialize_result(blocked)
    if (
        serialized_block.get("result_type") != "pilot_scope_excluded"
        or not isinstance(serialized_block.get("pilot_scope"), dict)
    ):
        failures.append("pilot scope exclusion was not API-serializable")

    development_shipment = _road_shipment(is_adr=True, adr_class="3")
    development_decision = evaluate_pilot_scope(
        development_shipment,
        environ={"MINAI_PILOT_MODE": "0"},
    )
    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        development_result = process_shipment(development_shipment)
    if not development_decision.eligible:
        failures.append("development mode applied the pilot scope exclusion")
    if development_result.get("result_type") == "pilot_scope_excluded":
        failures.append("development workflow changed to pilot scope behavior")

    _mixed_currency_progression(failures)
    _transport_mode_confirmation_lifecycle(failures)

    return {
        "name": "Fail-closed shadow-pilot scope eligibility",
        "passed": len(failures) == 0,
        "failures": failures,
    }
