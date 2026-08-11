from __future__ import annotations

from src.ai.extraction_models import ShipmentExtraction
from src.ai.extraction_mapping import shipment_from_extraction
from src.ai.clarification_generator import generate_clarification_draft
from src.core.clarification_requirements import (
    UnknownClarificationKeyError,
    apply_clarification_answers,
    get_all_clarification_requirements,
)
from src.core.missing_info import check_missing_information
from src.core.models import RiskAssessment, Shipment
from src.core.quote_readiness import decide_quote_readiness


def _shipment(commodity: str, **updates) -> Shipment:
    data = {
        "customer_name": "Clarification Regression Customer",
        "pickup_country": "Türkiye",
        "pickup_city": "Gebze",
        "delivery_country": "Almanya",
        "delivery_city": "Hamburg",
        "commodity": commodity,
        "gross_weight_kg": 6000,
        "cargo_ready_date": "2026-09-01",
    }
    data.update(updates)
    return Shipment(**data)


def evaluate_clarification_resolution_regressions() -> dict:
    failures: list[str] = []
    requirements = get_all_clarification_requirements()

    if len(requirements) != 18:
        failures.append(
            f"expected 18 canonical requirements, got {len(requirements)}"
        )

    if sum(item.critical for item in requirements.values()) != 15:
        failures.append("expected 15 critical clarification requirements")

    critical_commodities = {
        requirement.commodity
        for requirement in requirements.values()
        if requirement.critical
    }
    for commodity in sorted(critical_commodities):
        commodity_requirements = [
            requirement
            for requirement in requirements.values()
            if requirement.commodity == commodity
            and requirement.critical
        ]
        representative_answers = {
            requirement.key: (
                False
                if requirement.value_type == "boolean"
                else 1.0
                if requirement.value_type == "number"
                else "Teyit edildi"
            )
            for requirement in commodity_requirements
        }
        representative_shipment = apply_clarification_answers(
            _shipment(commodity),
            representative_answers,
        )
        representative_missing = check_missing_information(
            representative_shipment
        )
        unresolved_critical = {
            requirement.key
            for requirement in commodity_requirements
        }.intersection(representative_missing.missing_fields)

        if unresolved_critical:
            failures.append(
                f"{commodity} requirements remain unresolved: "
                f"{sorted(unresolved_critical)}"
            )

    initial = _shipment("Kimyasal Ürün")
    initial_missing = check_missing_information(initial)
    expected_chemical_keys = {
        "msds/sds document",
        "adr status",
        "chemical packaging type",
    }

    if initial_missing.can_continue_to_quote:
        failures.append("unanswered chemical requirements should clarify")

    initial_readiness = decide_quote_readiness(
        missing_info=initial_missing,
        risk_assessment=RiskAssessment(risk_level="yellow"),
        operational_consistency={"errors": []},
    )
    if initial_readiness.result_type != "clarification":
        failures.append("initial missing answers should block quote readiness")

    if set(initial_missing.missing_fields) != expected_chemical_keys:
        failures.append(
            "initial chemical missing fields do not match canonical keys"
        )

    clarification = generate_clarification_draft(
        initial,
        initial_missing,
    )
    if "Yük ADR kapsamında mıdır?" not in clarification.body:
        failures.append("clarification draft should use canonical question")

    extracted = ShipmentExtraction(
        customer_name="Original Email Customer",
        pickup_country="Türkiye",
        pickup_city="Gebze",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Kimyasal Ürün",
        gross_weight_kg=6000,
        cargo_ready_date="2026-09-01",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        commodity_attributes={
            "msds/sds document": True,
            "adr status": False,
            "chemical packaging type": "UN onaylı varil",
        },
    )
    from src.core.extraction_confirmation_repository import (
        InMemoryExtractionProposalRepository,
    )
    from src.core.mail import InboundMailEnvelope
    from src.workflow.extraction_confirmation import (
        confirm_extraction_proposal,
        create_extraction_proposal,
    )

    extraction_repository = InMemoryExtractionProposalRepository()
    extraction_proposal = create_extraction_proposal(
        mail=InboundMailEnvelope(
            body_text="Controlled clarification extraction fixture.",
            source="manual",
        ),
        proposed_shipment=shipment_from_extraction(extracted),
        repository=extraction_repository,
    )
    extracted_shipment = confirm_extraction_proposal(
        repository=extraction_repository,
        proposal_id=extraction_proposal.proposal_id,
        operator_identity="Clarification regression fixture",
    ).confirmed_shipment
    extracted_missing = check_missing_information(extracted_shipment)

    if not extracted_missing.can_continue_to_quote:
        failures.append(
            "answers extracted from original email should avoid clarification"
        )

    if extracted_shipment.model_dump().get("commodity_attributes") != {
        "msds/sds document": True,
        "adr status": False,
        "chemical packaging type": "UN onaylı varil",
    }:
        failures.append("commodity attributes should serialize on Shipment")

    resolved = apply_clarification_answers(
        initial,
        {
            "msds/sds document": True,
            "adr status": False,
            "chemical packaging type": "UN onaylı varil",
        },
    )
    resolved_missing = check_missing_information(resolved)

    if not resolved_missing.can_continue_to_quote:
        failures.append(
            "fully answered clarification should restore quote readiness"
        )

    resolved_readiness = decide_quote_readiness(
        missing_info=resolved_missing,
        risk_assessment=RiskAssessment(risk_level="yellow"),
        operational_consistency={"errors": []},
    )
    if (
        not resolved_readiness.can_generate_quote
        or resolved_readiness.result_type != "quote_with_review"
    ):
        failures.append(
            "resolved clarification should reopen the quote workflow"
        )

    if resolved.is_adr is not False:
        failures.append("explicit false ADR answer should update shipment")

    partial = apply_clarification_answers(
        initial,
        {"adr status": False},
    )
    partial_missing = check_missing_information(partial)

    if "adr status" in partial_missing.missing_fields:
        failures.append("explicit false answer must count as answered")

    if set(partial_missing.missing_fields) != {
        "msds/sds document",
        "chemical packaging type",
    }:
        failures.append("partial answers should leave only unanswered keys")

    original_attributes = dict(initial.commodity_attributes)
    try:
        apply_clarification_answers(
            initial,
            {"unrecognized field": "unsafe mutation"},
        )
    except UnknownClarificationKeyError:
        pass
    else:
        failures.append("unknown clarification key should fail safely")

    if initial.commodity_attributes != original_attributes:
        failures.append("failed answer application mutated original shipment")

    normal = _shipment("Tekstil")
    normal_missing = check_missing_information(normal)
    if (
        not normal_missing.can_continue_to_quote
        or normal_missing.missing_fields
    ):
        failures.append("normal cargo missing-info behavior should be unchanged")

    return {
        "name": "Clarification resolution contract",
        "passed": not failures,
        "failures": failures,
    }
