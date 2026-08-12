from __future__ import annotations

from collections.abc import Callable

from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import (
    ExtractionProposalRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.privacy import (
    PrivacySafeText,
    prepare_inbound_mail_for_processing,
)
from src.workflow.extraction_confirmation import create_extraction_proposal


def process_customer_inquiry_mail(
    *,
    mail: InboundMailEnvelope,
    shipment_parser: Callable[[PrivacySafeText], ShipmentProposalSnapshot],
    proposal_repository: ExtractionProposalRepository,
) -> dict:
    """Stop customer mail at a non-authoritative extraction proposal."""

    safe_mail, safe_text = prepare_inbound_mail_for_processing(mail)
    proposed_shipment = shipment_parser(safe_text)
    proposal = create_extraction_proposal(
        mail=safe_mail,
        proposed_shipment=proposed_shipment,
        repository=proposal_repository,
    )
    return {
        "result_type": "extraction_confirmation_required",
        "extraction_proposal": proposal,
        "shipment": None,
        "customer_memory": None,
        "missing_info": None,
        "regulatory_compliance": None,
        "equipment_decision": None,
        "risk_assessment": None,
        "supplier_selection": None,
        "operational_consistency": None,
        "quote_readiness": None,
        "supplier_rfq_workflow": None,
        "supplier_rfq_drafts": [],
        "supplier_rfq_responses": [],
        "valid_supplier_rfq_responses": [],
        "supplier_rfq_response_validation": None,
        "supplier_quote_comparisons": [],
        "supplier_quote_selection_decision": None,
        "supplier_quote": None,
        "customer_quote": None,
        "quote_draft": None,
        "quote_approval": None,
        "quote_send_safety": None,
        "quote_case": None,
        "clarification_draft": None,
        "management_review_draft": None,
        "action_recommendation": None,
    }
