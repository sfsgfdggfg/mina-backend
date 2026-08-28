from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from threading import Lock

from src.core.extraction_confirmation import (
    ShipmentExtractionProposal,
    ShipmentProposalSnapshot,
)
from src.core.extraction_confirmation_repository import (
    ExtractionProposalRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.privacy import (
    PrivacySafeText,
    fingerprint_text,
    prepare_inbound_mail_for_processing,
)
from src.workflow.extraction_confirmation import (
    create_extraction_proposal,
)


class InboundMailIdempotencyConflictError(ValueError):
    pass


_MESSAGE_LOCKS_GUARD = Lock()
_MESSAGE_LOCKS: dict[str, Lock] = {}


@contextmanager
def _message_ingestion_lock(
    message_key: str | None,
):
    if message_key is None:
        yield
        return

    with _MESSAGE_LOCKS_GUARD:
        lock = _MESSAGE_LOCKS.setdefault(
            message_key,
            Lock(),
        )

    with lock:
        yield


def _existing_proposal_for_mail(
    *,
    mail: InboundMailEnvelope,
    repository: ExtractionProposalRepository,
) -> ShipmentExtractionProposal | None:
    message_key = mail.message_deduplication_key

    if message_key is None:
        return None

    existing = repository.find_by_message_key(
        message_key
    )

    if existing is None:
        return None

    existing_hash = (
        existing.inbound_mail.raw_body_sha256
    )
    incoming_hash = fingerprint_text(
        mail.body_text
    )

    if (
        existing_hash is None
        or existing_hash != incoming_hash
        or existing.inbound_mail.sender_address
        != mail.sender_address
    ):
        raise InboundMailIdempotencyConflictError(
            "Inbound message ID was reused with "
            "different content or sender."
        )

    return existing


def _extraction_required_result(
    *,
    proposal: ShipmentExtractionProposal,
    ingestion_status: str,
) -> dict:
    return {
        "result_type": (
            "extraction_confirmation_required"
        ),
        "ingestion_status": ingestion_status,
        "extraction_proposal": proposal,
        "shipment": None,
        "pilot_scope": None,
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



def existing_proposal_for_mail(
    *,
    mail: InboundMailEnvelope,
    repository: ExtractionProposalRepository,
):
    """Return an exact prior customer ingestion or fail on ID reuse."""
    return _existing_proposal_for_mail(
        mail=mail,
        repository=repository,
    )


def process_customer_inquiry_mail(
    *,
    mail: InboundMailEnvelope,
    shipment_parser: Callable[
        [PrivacySafeText],
        ShipmentProposalSnapshot,
    ],
    proposal_repository: ExtractionProposalRepository,
    trusted_customer_name: str | None = None,
) -> dict:
    """Stop customer mail at a non-authoritative extraction proposal."""

    message_key = mail.message_deduplication_key

    with _message_ingestion_lock(message_key):
        existing = _existing_proposal_for_mail(
            mail=mail,
            repository=proposal_repository,
        )

        if existing is not None:
            return _extraction_required_result(
                proposal=existing,
                ingestion_status=(
                    "duplicate_existing_proposal"
                ),
            )

        safe_mail, safe_text = (
            prepare_inbound_mail_for_processing(
                mail
            )
        )
        proposed_shipment = shipment_parser(
            safe_text
        )
        if trusted_customer_name and trusted_customer_name.strip():
            proposed_shipment = proposed_shipment.model_copy(
                update={"customer_name": trusted_customer_name.strip()}
            )
        proposal = create_extraction_proposal(
            mail=safe_mail,
            proposed_shipment=proposed_shipment,
            repository=proposal_repository,
        )

        return _extraction_required_result(
            proposal=proposal,
            ingestion_status="created",
        )
