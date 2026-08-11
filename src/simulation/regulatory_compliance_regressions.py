from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from src.core import clarification_requirements as clarification_contract
from src.core.action_recommendation import generate_action_recommendation
from src.core.clarification_requirements import (
    apply_clarification_answers,
    get_all_clarification_requirements,
)
from src.core.missing_info import check_missing_information
from src.core.models import (
    CustomerQuote,
    EquipmentDecision,
    QuoteDraft,
    RiskAssessment,
    Shipment,
    SupplierQuote,
)
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_readiness import decide_quote_readiness
from src.core.quote_send_safety import evaluate_quote_send_safety
from src.core.regulatory_compliance import (
    approve_regulatory_exception,
    assess_regulatory_compliance,
    reject_regulatory_exception,
    request_regulatory_exception_review,
)
from src.simulation.clarification_resolution_regressions import (
    evaluate_clarification_resolution_regressions,
)


CONTROLLED_COMMODITY = "Verified Regulatory Fixture"
DOCUMENT_KEY = "verified regulatory document"
UNVERIFIED_PRODUCTION_DOCUMENT_KEYS = {
    "msds/sds document",
    "medical compliance document",
    "pharma compliance document",
}


def _verified_regulatory_fixture() -> dict:
    return {
        "canonical_commodity": CONTROLLED_COMMODITY,
        "keywords": ["verified-regulatory-fixture"],
        "operational_profile": {
            "clarification_requirements": [
                {
                    "key": DOCUMENT_KEY,
                    "value_type": "boolean",
                    "question": (
                        "Doğrulanmış düzenleyici belge mevcut mu?"
                    ),
                    "critical": True,
                    "compliance_policy": {
                        "policy_type": "regulatory_document",
                        "document_label": (
                            "Doğrulanmış düzenleyici test belgesi"
                        ),
                        "required_before_quote": True,
                        "customer_promise_requires_human_review": True,
                    },
                }
            ]
        },
    }


def _shipment(commodity: str, **updates) -> Shipment:
    data = {
        "customer_name": "Regulatory Regression Customer",
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


def _controlled_shipment(**answers) -> Shipment:
    shipment = _shipment(CONTROLLED_COMMODITY)
    if not answers:
        return shipment
    return apply_clarification_answers(shipment, answers)


def _readiness(
    shipment: Shipment,
    risk_level: str = "yellow",
):
    missing = check_missing_information(shipment)
    compliance = assess_regulatory_compliance(shipment)
    readiness = decide_quote_readiness(
        missing_info=missing,
        risk_assessment=RiskAssessment(
            risk_level=risk_level,
            risk_reasons=(
                ["Controlled fixture requires normal human review."]
                if risk_level == "yellow"
                else []
            ),
            requires_human_review=risk_level == "yellow",
        ),
        operational_consistency={"errors": []},
        regulatory_compliance=compliance,
    )
    return missing, compliance, readiness


def _evaluate_verified_policy_scenarios(
    failures: list[str],
) -> None:
    requirements = get_all_clarification_requirements()
    fixture_requirement = requirements.get(DOCUMENT_KEY)
    if (
        fixture_requirement is None
        or fixture_requirement.compliance_policy is None
        or not fixture_requirement.compliance_policy.required_before_quote
    ):
        failures.append(
            "controlled fixture should have explicit regulatory metadata"
        )

    unanswered = _controlled_shipment()
    missing, compliance, readiness = _readiness(unanswered)
    if DOCUMENT_KEY not in missing.missing_fields:
        failures.append("unanswered regulatory document should be missing")
    if compliance.status != "clarification_required":
        failures.append("unknown document status should require clarification")
    if readiness.result_type != "clarification":
        failures.append("unknown document status should stop at clarification")

    available = _controlled_shipment(**{DOCUMENT_KEY: True})
    missing, compliance, readiness = _readiness(available)
    if not missing.can_continue_to_quote or compliance.status != "clear":
        failures.append("available regulatory document should be satisfied")
    if readiness.result_type != "quote_with_review":
        failures.append(
            "available document should proceed to the next normal check"
        )

    unavailable = _controlled_shipment(**{DOCUMENT_KEY: False})
    missing, compliance, readiness = _readiness(unavailable)
    if not missing.can_continue_to_quote:
        failures.append("known unavailable document is not missing info")
    if compliance.status != "blocked":
        failures.append("unavailable regulatory document should be blocked")
    if (
        readiness.result_type != "regulatory_blocked"
        or readiness.can_generate_quote
    ):
        failures.append("unavailable document should block automatic quote")
    if not any(
        "Doğrulanmış düzenleyici test belgesi" in reason
        for reason in readiness.reasons
    ):
        failures.append("regulatory block reason should be human-readable")

    pending = request_regulatory_exception_review(
        unavailable,
        DOCUMENT_KEY,
        (
            "Lütfen şimdi fiyat verin; belgeyi yüklemeden önce "
            "sağlayacağız."
        ),
    )
    _, compliance, readiness = _readiness(pending)
    if compliance.status != "human_review_required":
        failures.append("document promise should require human review")
    if (
        readiness.result_type != "regulatory_review"
        or readiness.can_generate_quote
        or not readiness.requires_human_review
    ):
        failures.append("pending review should fail closed")

    supplier_quote = SupplierQuote(
        supplier_name="Regression Supplier",
        cost=2000,
    )
    customer_quote = CustomerQuote(
        supplier_cost=2000,
        markup_type="percentage",
        markup_value=15,
        final_price=2300,
    )
    quote_draft = QuoteDraft(
        subject="Regression quote",
        body="Regression quote body",
    )
    approved_quote = QuoteApproval(
        approval_status="approved",
        approved_by="Quote Approver",
        approved_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        quote_snapshot=QuoteApprovalSnapshot.from_quote(
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
        ),
    )
    send_decision = evaluate_quote_send_safety(
        approval=approved_quote,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
        regulatory_compliance=compliance,
    )
    if (
        readiness.can_generate_quote
        or send_decision.can_send
        or send_decision.block_reason != "regulatory_review_pending"
    ):
        failures.append("pending review must block quote and send eligibility")

    pending_action = generate_action_recommendation(
        shipment=pending,
        equipment_decision=EquipmentDecision(
            selected_equipment="Controlled Test Equipment",
            reason="Regression fixture",
            confidence=1.0,
        ),
        risk_assessment=RiskAssessment(risk_level="yellow"),
        missing_info=check_missing_information(pending),
        result_type="regulatory_review",
    )
    if pending_action.action_type != "regulatory_review":
        failures.append("pending review should have a dedicated action")

    approved = approve_regulatory_exception(
        pending,
        DOCUMENT_KEY,
        decided_by="Senior Operator",
        decision_reason="Controlled manual exception approved.",
    )
    _, compliance, readiness = _readiness(approved)
    if compliance.status != "clear":
        failures.append("approved exception should clear compliance gate")
    if DOCUMENT_KEY not in compliance.approved_exception_requirements:
        failures.append("approved exception should remain traceable")
    if readiness.result_type != "quote_with_review":
        failures.append("approved exception should resume normal checks")

    rejected = reject_regulatory_exception(
        pending,
        DOCUMENT_KEY,
        decided_by="Senior Operator",
        decision_reason="Document must be available before quotation.",
    )
    _, compliance, readiness = _readiness(rejected)
    if (
        compliance.status != "blocked"
        or readiness.result_type != "regulatory_blocked"
    ):
        failures.append("rejected exception should remain blocked")


def evaluate_regulatory_compliance_regressions() -> dict:
    failures: list[str] = []
    production_requirements = get_all_clarification_requirements()
    inferred_classifications = {
        key
        for key in UNVERIFIED_PRODUCTION_DOCUMENT_KEYS
        if production_requirements[key].compliance_policy is not None
    }
    if inferred_classifications:
        failures.append(
            "unverified production documents must not be classified: "
            f"{sorted(inferred_classifications)}"
        )

    unverified_negative_cases = [
        (
            "Kimyasal Ürün",
            {
                "msds/sds document": False,
                "adr status": False,
                "chemical packaging type": "UN onaylı varil",
            },
        ),
        (
            "Medikal Ürün",
            {
                "medical product type": "Tıbbi cihaz",
                "medical compliance document": False,
                "medical temperature sensitivity": False,
            },
        ),
        (
            "İlaç / Pharma",
            {
                "pharma temperature requirement": "+15C / +25C",
                "pharma compliance document": False,
                "pharma special transport requirements": "Yok",
            },
        ),
    ]
    for commodity, answers in unverified_negative_cases:
        shipment = apply_clarification_answers(
            _shipment(commodity),
            answers,
        )
        missing, compliance, readiness = _readiness(shipment)
        if not missing.can_continue_to_quote:
            failures.append(
                f"answered {commodity} requirement should not stay missing"
            )
        if compliance.status != "clear" or readiness.result_type in {
            "regulatory_blocked",
            "regulatory_review",
        }:
            failures.append(
                f"unverified {commodity} document must not trigger "
                "regulatory blocking"
            )

    production_dictionary = clarification_contract._load_dictionary()
    controlled_dictionary = [
        *production_dictionary,
        _verified_regulatory_fixture(),
    ]
    with patch.object(
        clarification_contract,
        "_load_dictionary",
        return_value=controlled_dictionary,
    ):
        _evaluate_verified_policy_scenarios(failures)

    non_regulatory = apply_clarification_answers(
        _shipment("Dondurulmuş Gıda"),
        {
            "frozen temperature requirement": "-18C",
            "reefer confirmation": False,
            "cold chain sensitivity": False,
        },
    )
    missing, compliance, _ = _readiness(
        non_regulatory,
        risk_level="green",
    )
    if not missing.can_continue_to_quote or compliance.status != "clear":
        failures.append(
            "non-regulatory attributes must not trigger regulatory blocking"
        )

    textile = _shipment("Tekstil")
    missing, compliance, readiness = _readiness(
        textile,
        risk_level="green",
    )
    if (
        not missing.can_continue_to_quote
        or compliance.status != "clear"
        or readiness.result_type != "quote_ready"
    ):
        failures.append("normal textile flow should remain unchanged")

    clarification_result = (
        evaluate_clarification_resolution_regressions()
    )
    if not clarification_result.get("passed"):
        failures.append(
            "existing clarification regressions failed: "
            f"{clarification_result.get('failures')}"
        )

    return {
        "name": "Regulatory document and human review boundary",
        "passed": not failures,
        "failures": failures,
    }
