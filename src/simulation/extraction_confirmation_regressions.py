from __future__ import annotations

from datetime import datetime, timezone

from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.mail import InboundMailEnvelope
from src.core.models import Package, Shipment


def _shipment(**updates) -> Shipment:
    data = {
        "customer_name": "Extraction Checkpoint Customer",
        "pickup_country": "Türkiye",
        "pickup_city": "Adana",
        "delivery_country": "Almanya",
        "delivery_city": "Hamburg",
        "commodity": "Tekstil",
        "gross_weight_kg": 20000,
        "service_type": "FTL",
        "cargo_ready_date": "2026-09-10",
        "is_adr": False,
        "is_temperature_controlled": False,
        "is_high_value": False,
        "packages": [
            Package(
                package_type="pallet",
                quantity=20,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    }
    data.update(updates)
    return Shipment(**data)


def _snapshot(**updates) -> ShipmentProposalSnapshot:
    data = _shipment().model_dump()
    data.update(updates)
    return ShipmentProposalSnapshot.model_validate(data)


def evaluate_extraction_confirmation_regressions() -> dict:
    from src.core.extraction_confirmation_repository import (
        InMemoryExtractionProposalRepository,
    )
    from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts
    from src.core.customer_memory import enrich_shipment_with_customer_memory
    from src.core.equipment import decide_equipment
    from src.core.missing_info import check_missing_information
    from src.core.risk import assess_risk
    from src.core.supplier_selection import select_suppliers_for_shipment
    from src.core.quote_approval_repository import (
        InMemoryQuoteApprovalRepository,
    )
    from src.core.quote_case_repository import InMemoryQuoteCaseRepository
    from src.core.supplier_rfq import SupplierRFQDraft
    from src.core.supplier_rfq_lifecycle import approve_supplier_rfq
    from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
    from src.simulation.regulatory_compliance_regressions import (
        evaluate_regulatory_compliance_regressions,
    )
    from src.simulation.supplier_response_ingestion_regressions import (
        evaluate_supplier_response_ingestion_regressions,
    )
    from src.simulation.supplier_rfq_lifecycle_regressions import (
        evaluate_supplier_rfq_lifecycle_regressions,
    )
    from src.workflow.extraction_confirmation import (
        ExtractionConfirmationTransitionError,
        ExtractionCorrectionError,
        ExtractionProposalNotFoundError,
        confirm_extraction_proposal,
        create_extraction_proposal,
        resume_confirmed_extraction,
    )
    from src.workflow.mail_delivery import send_supplier_rfq_via_mail
    from src.workflow.mail_ingestion import process_customer_inquiry_mail
    from src.workflow.pipeline import process_shipment

    failures: list[str] = []
    mail = InboundMailEnvelope(
        external_message_id="customer-message-1",
        provider_name="regression-mail",
        mailbox_id="operations@example.invalid",
        sender_address="customer@example.invalid",
        recipient_addresses=["operations@example.invalid"],
        subject="Freight inquiry",
        body_text="Original normalized customer inquiry.",
        received_at=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
        source="email",
    )

    proposal_repository = InMemoryExtractionProposalRepository()
    rfq_repository = InMemorySupplierRFQRepository()
    initial = process_customer_inquiry_mail(
        mail=mail,
        shipment_parser=lambda _: _snapshot(
            customer_name="Oğuz Gıda",
            pickup_city=None,
            pickup_area=None,
        ),
        proposal_repository=proposal_repository,
    )
    proposal = initial.get("extraction_proposal")
    if (
        initial.get("result_type") != "extraction_confirmation_required"
        or proposal is None
        or proposal.extraction_status != "proposed"
    ):
        failures.append("new customer mail did not stop at extraction proposal")
    if initial.get("shipment") is not None:
        failures.append("unconfirmed extraction exposed an operational Shipment")
    if initial.get("customer_memory") is not None:
        failures.append("unconfirmed extraction activated customer memory")
    if proposal and proposal.proposed_shipment.pickup_city is not None:
        failures.append("unconfirmed proposal received customer-memory defaults")
    if any(
        initial.get(field_name) is not None
        for field_name in (
            "equipment_decision",
            "risk_assessment",
            "supplier_selection",
            "quote_readiness",
        )
    ):
        failures.append("unconfirmed extraction triggered operational engines")
    if initial.get("supplier_rfq_drafts") or rfq_repository.list_drafts():
        failures.append("unconfirmed extraction created supplier RFQs")
    if proposal is not None:
        try:
            process_shipment(proposal.proposed_shipment, email_text=mail.body_text)
        except TypeError:
            pass
        else:
            failures.append(
                "operational pipeline accepted an unconfirmed proposal"
            )
        blocked_engine_calls = (
            lambda: enrich_shipment_with_customer_memory(
                proposal.proposed_shipment,
                email_text=mail.body_text,
            ),
            lambda: check_missing_information(proposal.proposed_shipment),
            lambda: decide_equipment(proposal.proposed_shipment),
            lambda: assess_risk(proposal.proposed_shipment),
            lambda: select_suppliers_for_shipment(
                proposal.proposed_shipment
            ),
            lambda: generate_supplier_rfq_drafts(
                shipment=proposal.proposed_shipment,
                equipment_decision=None,
                supplier_selection={"selected_suppliers": []},
            ),
        )
        for blocked_call in blocked_engine_calls:
            try:
                blocked_call()
            except TypeError:
                pass
            else:
                failures.append(
                    "an operational engine accepted an unconfirmed proposal"
                )
    if proposal and (
        proposal.inbound_mail.external_message_id != "customer-message-1"
        or proposal.inbound_mail.body_text
        != "Original normalized customer inquiry."
    ):
        failures.append("proposal did not preserve normalized inbound mail")

    unchanged_repository = InMemoryExtractionProposalRepository()
    unchanged = create_extraction_proposal(
        mail=mail,
        proposed_shipment=_snapshot(),
        repository=unchanged_repository,
    )
    confirmation_time = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)
    confirmed = confirm_extraction_proposal(
        repository=unchanged_repository,
        proposal_id=unchanged.proposal_id,
        operator_identity="  Claimed Pilot Operator  ",
        confirmed_at=confirmation_time,
    )
    if (
        confirmed.extraction_status != "confirmed"
        or confirmed.confirmed_shipment is None
        or confirmed.changed_fields
        or confirmed.operator_corrections
        or confirmed.confirmed_by != "Claimed Pilot Operator"
        or confirmed.confirmed_at != confirmation_time
    ):
        failures.append("unchanged confirmation metadata/snapshot is invalid")

    unchanged_rfq_repository = InMemorySupplierRFQRepository()
    resumed = resume_confirmed_extraction(
        repository=unchanged_repository,
        proposal_id=unchanged.proposal_id,
        rfq_repository=unchanged_rfq_repository,
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
    )
    if (
        resumed.get("result_type") != "supplier_rfq_approval_required"
        or not resumed.get("supplier_rfq_drafts")
        or resumed.get("shipment") is None
    ):
        failures.append("confirmed unchanged snapshot did not resume RFQ workflow")

    corrected_repository = InMemoryExtractionProposalRepository()
    corrected = create_extraction_proposal(
        mail=mail,
        proposed_shipment=_snapshot(
            delivery_city="Hamburg",
            gross_weight_kg=20000,
        ),
        repository=corrected_repository,
    )
    corrected_confirmation = confirm_extraction_proposal(
        repository=corrected_repository,
        proposal_id=corrected.proposal_id,
        operator_identity="Correction Operator",
        corrections={
            "delivery_city": "Berlin",
            "gross_weight_kg": 18000,
        },
    )
    corrected_result = resume_confirmed_extraction(
        repository=corrected_repository,
        proposal_id=corrected.proposal_id,
        rfq_repository=InMemorySupplierRFQRepository(),
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
    )
    stored_corrected = corrected_repository.get(corrected.proposal_id)
    if (
        corrected_result["shipment"].delivery_city != "Berlin"
        or corrected_result["shipment"].gross_weight_kg != 18000
    ):
        failures.append("downstream workflow did not use corrected snapshot")
    if (
        stored_corrected is None
        or stored_corrected.proposed_shipment.delivery_city != "Hamburg"
        or stored_corrected.proposed_shipment.gross_weight_kg != 20000
        or set(stored_corrected.changed_fields)
        != {"delivery_city", "gross_weight_kg"}
        or stored_corrected.operator_corrections.get("delivery_city") != "Berlin"
    ):
        failures.append("original AI proposal/correction evidence was not preserved")
    if corrected_confirmation.confirmed_shipment is None:
        failures.append("corrected confirmation did not create confirmed snapshot")

    unknown_repository = InMemoryExtractionProposalRepository()
    unknown = create_extraction_proposal(
        mail=mail,
        proposed_shipment=_snapshot(
            is_adr=None,
            is_temperature_controlled=None,
            is_high_value=None,
        ),
        repository=unknown_repository,
    )
    if set(unknown.unknown_safety_fields) != {
        "is_adr",
        "is_temperature_controlled",
        "is_high_value",
    }:
        failures.append("unknown safety facts were not preserved explicitly")
    unknown_confirmation = confirm_extraction_proposal(
        repository=unknown_repository,
        proposal_id=unknown.proposal_id,
        operator_identity="Safety Operator",
    )
    if (
        unknown_confirmation.confirmed_shipment is None
        or unknown_confirmation.confirmed_shipment.is_adr is not None
        or unknown_confirmation.confirmed_shipment.is_temperature_controlled
        is not None
        or unknown_confirmation.confirmed_shipment.is_high_value is not None
        or unknown_confirmation.changed_fields
        or unknown_confirmation.operator_corrections
    ):
        failures.append("unknown safety facts were not confirmed unchanged")
    unknown_result = resume_confirmed_extraction(
        repository=unknown_repository,
        proposal_id=unknown.proposal_id,
        rfq_repository=InMemorySupplierRFQRepository(),
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
    )
    if unknown_result.get("result_type") != "supplier_rfq_approval_required":
        failures.append("ordinary shipment with unknown safety facts did not resume")

    explicit_false_repository = InMemoryExtractionProposalRepository()
    explicit_false = create_extraction_proposal(
        mail=mail,
        proposed_shipment=_snapshot(
            is_adr=False,
            is_temperature_controlled=False,
            is_high_value=False,
        ),
        repository=explicit_false_repository,
    )
    if explicit_false.unknown_safety_fields:
        failures.append("explicit false safety facts were treated as unknown")
    explicit_false_confirmation = confirm_extraction_proposal(
        repository=explicit_false_repository,
        proposal_id=explicit_false.proposal_id,
        operator_identity="Explicit False Operator",
    )
    explicit_false_shipment = explicit_false_confirmation.confirmed_shipment
    if (
        explicit_false_shipment is None
        or explicit_false_shipment.is_adr is not False
        or explicit_false_shipment.is_temperature_controlled is not False
        or explicit_false_shipment.is_high_value is not False
    ):
        failures.append("explicit false safety facts were not preserved")

    positive_repository = InMemoryExtractionProposalRepository()
    positive = create_extraction_proposal(
        mail=mail,
        proposed_shipment=_snapshot(
            is_adr=True,
            adr_class="3",
            is_temperature_controlled=True,
            temperature_requirement="2-8 C",
            is_high_value=True,
        ),
        repository=positive_repository,
    )
    confirm_extraction_proposal(
        repository=positive_repository,
        proposal_id=positive.proposal_id,
        operator_identity="Positive Risk Operator",
    )
    positive_result = resume_confirmed_extraction(
        repository=positive_repository,
        proposal_id=positive.proposal_id,
        rfq_repository=InMemorySupplierRFQRepository(),
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
    )
    positive_shipment = positive_result.get("shipment")
    positive_risk = positive_result.get("risk_assessment")
    if (
        positive_shipment is None
        or positive_shipment.is_adr is not True
        or positive_shipment.is_temperature_controlled is not True
        or positive_shipment.is_high_value is not True
        or positive_risk is None
        or not positive_risk.requires_human_review
        or positive_result.get("result_type") != "supplier_selection_required"
    ):
        failures.append("positive exception signals lost downstream protection")

    for contradictory_snapshot in (
        _snapshot(is_adr=False, adr_class="3"),
        _snapshot(
            is_temperature_controlled=False,
            temperature_requirement="2-8 C",
        ),
    ):
        contradiction_repository = InMemoryExtractionProposalRepository()
        contradiction = create_extraction_proposal(
            mail=mail,
            proposed_shipment=contradictory_snapshot,
            repository=contradiction_repository,
        )
        try:
            confirm_extraction_proposal(
                repository=contradiction_repository,
                proposal_id=contradiction.proposal_id,
                operator_identity="Contradiction Operator",
            )
        except ExtractionCorrectionError:
            pass
        else:
            failures.append("safety contradiction was accepted")

    atomic_repository = InMemoryExtractionProposalRepository()
    atomic = create_extraction_proposal(
        mail=mail,
        proposed_shipment=_snapshot(),
        repository=atomic_repository,
    )
    try:
        confirm_extraction_proposal(
            repository=atomic_repository,
            proposal_id=atomic.proposal_id,
            operator_identity="Atomic Operator",
            corrections={"not_a_shipment_field": "unsafe"},
        )
    except ExtractionCorrectionError:
        pass
    else:
        failures.append("invalid correction was accepted")
    atomic_after_failure = atomic_repository.get(atomic.proposal_id)
    if (
        atomic_after_failure.extraction_status != "proposed"
        or atomic_after_failure.confirmed_shipment is not None
    ):
        failures.append("invalid correction partially mutated proposal")

    try:
        confirm_extraction_proposal(
            repository=atomic_repository,
            proposal_id="unknown-proposal",
            operator_identity="Operator",
        )
    except ExtractionProposalNotFoundError:
        pass
    else:
        failures.append("unknown proposal confirmation did not fail closed")

    duplicate_repository = InMemoryExtractionProposalRepository()
    duplicate = create_extraction_proposal(
        mail=mail,
        proposed_shipment=_snapshot(),
        repository=duplicate_repository,
    )
    first_confirmation = confirm_extraction_proposal(
        repository=duplicate_repository,
        proposal_id=duplicate.proposal_id,
        operator_identity="First Operator",
    )
    try:
        confirm_extraction_proposal(
            repository=duplicate_repository,
            proposal_id=duplicate.proposal_id,
            operator_identity="Second Operator",
            corrections={"delivery_city": "Munich"},
        )
    except ExtractionConfirmationTransitionError:
        pass
    else:
        failures.append("duplicate confirmation overwrote confirmed snapshot")
    duplicate_stored = duplicate_repository.get(duplicate.proposal_id)
    if (
        duplicate_stored.confirmed_by != first_confirmation.confirmed_by
        or duplicate_stored.confirmed_shipment
        != first_confirmation.confirmed_shipment
    ):
        failures.append("duplicate confirmation changed confirmation history")

    clarification_repository = InMemoryExtractionProposalRepository()
    clarification = create_extraction_proposal(
        mail=mail,
        proposed_shipment=_snapshot(cargo_ready_date=None),
        repository=clarification_repository,
    )
    confirm_extraction_proposal(
        repository=clarification_repository,
        proposal_id=clarification.proposal_id,
        operator_identity="Clarification Operator",
    )
    clarification_result = resume_confirmed_extraction(
        repository=clarification_repository,
        proposal_id=clarification.proposal_id,
        rfq_repository=InMemorySupplierRFQRepository(),
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
    )
    if clarification_result.get("result_type") != "clarification":
        failures.append("confirmation bypassed existing clarification gate")

    regulatory_repository = InMemoryExtractionProposalRepository()
    regulatory = create_extraction_proposal(
        mail=mail,
        proposed_shipment=_snapshot(
            commodity="Kimyasal Ürün",
            commodity_attributes={},
        ),
        repository=regulatory_repository,
    )
    confirm_extraction_proposal(
        repository=regulatory_repository,
        proposal_id=regulatory.proposal_id,
        operator_identity="Regulatory Operator",
    )
    regulatory_result = resume_confirmed_extraction(
        repository=regulatory_repository,
        proposal_id=regulatory.proposal_id,
        rfq_repository=InMemorySupplierRFQRepository(),
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
    )
    if regulatory_result.get("result_type") != "clarification":
        failures.append("confirmation bypassed commodity/regulatory checks")

    existing_regressions = (
        evaluate_regulatory_compliance_regressions(),
        evaluate_supplier_rfq_lifecycle_regressions(),
        evaluate_supplier_response_ingestion_regressions(),
    )
    for regression in existing_regressions:
        if not regression.get("passed"):
            failures.extend(
                f"existing {regression.get('name')}: {failure}"
                for failure in regression.get("failures", [])
            )

    no_provider_repository = InMemorySupplierRFQRepository()
    no_provider_draft = SupplierRFQDraft(
        rfq_id="checkpoint-no-outbound",
        workflow_id="checkpoint-no-outbound-workflow",
        supplier_name="Checkpoint Supplier",
        priority=1,
        recipient_email="supplier@example.invalid",
        subject="Checkpoint RFQ",
        body="Checkpoint RFQ body.",
    )
    no_provider_repository.save_drafts([no_provider_draft])
    approve_supplier_rfq(
        no_provider_repository,
        no_provider_draft.rfq_id,
        approved_by="Checkpoint Operator",
    )
    no_provider_result = send_supplier_rfq_via_mail(
        repository=no_provider_repository,
        rfq_id=no_provider_draft.rfq_id,
        sender=None,
    )
    if (
        no_provider_result.delivery.status != "provider_unavailable"
        or no_provider_result.supplier_rfq.status != "approved"
    ):
        failures.append("extraction checkpoint changed outbound mail safety")

    import src.api as api

    original_api_state = (
        api.parse_email_with_ai,
        api.extraction_proposal_repository,
        api.supplier_rfq_repository,
        api.quote_approval_repository,
        api.quote_case_repository,
    )
    try:
        api.parse_email_with_ai = lambda _: _snapshot()
        api.extraction_proposal_repository = (
            InMemoryExtractionProposalRepository()
        )
        api.supplier_rfq_repository = InMemorySupplierRFQRepository()
        api.quote_approval_repository = InMemoryQuoteApprovalRepository()
        api.quote_case_repository = InMemoryQuoteCaseRepository()

        api_initial = api.process_email(
            api.ProcessEmailRequest(email_text="API checkpoint inquiry")
        )
        api_proposal_id = api_initial["extraction_proposal"]["proposal_id"]
        api_inspected = api.get_extraction_proposal(api_proposal_id)
        api_confirmed = api.confirm_extraction_proposal_endpoint(
            api_proposal_id,
            api.ConfirmExtractionRequest(
                operator_identity="API Claimed Operator"
            ),
        )
        api_resumed = api.resume_extraction_proposal_endpoint(api_proposal_id)
        if (
            api_initial.get("result_type")
            != "extraction_confirmation_required"
            or api_initial.get("shipment") is not None
            or api_inspected.get("extraction_status") != "proposed"
            or api_confirmed.get("extraction_status") != "confirmed"
            or api_resumed.get("result_type")
            != "supplier_rfq_approval_required"
        ):
            failures.append("extraction confirmation API lifecycle is invalid")
    finally:
        (
            api.parse_email_with_ai,
            api.extraction_proposal_repository,
            api.supplier_rfq_repository,
            api.quote_approval_repository,
            api.quote_case_repository,
        ) = original_api_state

    return {
        "name": "Human extraction confirmation checkpoint",
        "passed": not failures,
        "failures": failures,
    }
