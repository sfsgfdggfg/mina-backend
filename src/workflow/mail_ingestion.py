from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
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
from src.core.inbound_counterparty_identity import (
    infer_sender_organization_name,
    value_supported_before_signature,
)
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import (
    create_mina_job_for_inbound_proposal,
    refine_mina_job_inbound_intake,
)
from src.core.models import Shipment
from src.core.relative_dates import (
    infer_customer_cargo_ready_date,
    infer_customer_quote_deadline,
)
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



_SIGNATURE_GUARDED_FIELDS = (
    "pickup_address", "pickup_postcode", "pickup_contact_name",
    "pickup_contact_phone", "delivery_address", "delivery_postcode",
    "delivery_contact_name", "delivery_contact_phone",
)


def _refine_inbound_shipment(
    *, mail: InboundMailEnvelope, proposed: ShipmentProposalSnapshot,
    trusted_customer_name: str | None = None,
    counterparty_name_hint: str | None = None,
) -> tuple[ShipmentProposalSnapshot, list[str]]:
    updates = {}
    resolved_name = (
        (trusted_customer_name or "").strip()
        or (counterparty_name_hint or "").strip()
        or (infer_sender_organization_name(mail.body_text) or "").strip()
    )
    if resolved_name and proposed.customer_name != resolved_name:
        updates["customer_name"] = resolved_name

    for field_name in _SIGNATURE_GUARDED_FIELDS:
        value = getattr(proposed, field_name, None)
        if value and not value_supported_before_signature(str(value), mail.body_text):
            updates[field_name] = None

    if not updates:
        return proposed, []
    return proposed.model_copy(update=updates), sorted(updates)


def extract_shipment_proposal_from_mail(
    *,
    mail: InboundMailEnvelope,
    shipment_parser: Callable[
        [PrivacySafeText],
        ShipmentProposalSnapshot,
    ],
    trusted_customer_name: str | None = None,
    counterparty_name_hint: str | None = None,
) -> tuple[InboundMailEnvelope, ShipmentProposalSnapshot]:
    """Privacy-transform and parse one mail without persisting a proposal."""

    safe_mail, safe_text = prepare_inbound_mail_for_processing(mail)
    proposed_shipment = shipment_parser(safe_text)
    proposed_shipment, _ = _refine_inbound_shipment(
        mail=mail, proposed=proposed_shipment,
        trusted_customer_name=trusted_customer_name,
        counterparty_name_hint=counterparty_name_hint,
    )
    proposal_updates = {}
    if not proposed_shipment.cargo_ready_date:
        inferred_ready = infer_customer_cargo_ready_date(
            str(safe_text), mail.received_at
        )
        if inferred_ready is not None:
            proposal_updates["cargo_ready_date"] = inferred_ready
    if proposed_shipment.customer_quote_deadline_at is None:
        inferred_quote_deadline = infer_customer_quote_deadline(
            str(safe_text), mail.received_at
        )
        if inferred_quote_deadline is not None:
            proposal_updates["customer_quote_deadline_at"] = inferred_quote_deadline
    if proposal_updates:
        proposed_shipment = proposed_shipment.model_copy(update=proposal_updates)
    return safe_mail, proposed_shipment



def save_preparsed_shipment_proposal(
    *,
    original_mail: InboundMailEnvelope,
    safe_mail: InboundMailEnvelope,
    proposed_shipment: ShipmentProposalSnapshot,
    proposal_repository: ExtractionProposalRepository,
    trusted_customer_name: str | None = None,
    evidence_origin: str = "customer_authored",
) -> dict:
    """Persist one already-parsed proposal with the normal message idempotency gate."""

    message_key = original_mail.message_deduplication_key
    with _message_ingestion_lock(message_key):
        existing = _existing_proposal_for_mail(
            mail=original_mail,
            repository=proposal_repository,
        )
        if existing is not None:
            return _extraction_required_result(
                proposal=existing,
                ingestion_status="duplicate_existing_proposal",
            )
        proposal = create_extraction_proposal(
            mail=safe_mail,
            proposed_shipment=proposed_shipment,
            repository=proposal_repository,
            trusted_customer_name=trusted_customer_name,
            evidence_origin=evidence_origin,
        )
        return _extraction_required_result(
            proposal=proposal,
            ingestion_status="created",
        )


def _refine_existing_inbound_proposal(
    *, existing: ShipmentExtractionProposal, mail: InboundMailEnvelope,
    repository: ExtractionProposalRepository,
    trusted_customer_name: str | None = None,
    counterparty_name_hint: str | None = None,
) -> tuple[ShipmentExtractionProposal, list[str]]:
    if existing.extraction_status != "proposed":
        return existing, []
    effective_trusted = (
        (trusted_customer_name or "").strip()
        or (existing.trusted_customer_name or "").strip()
        or None
    )
    refined, changed_fields = _refine_inbound_shipment(
        mail=mail, proposed=existing.proposed_shipment,
        trusted_customer_name=effective_trusted,
        counterparty_name_hint=counterparty_name_hint,
    )
    trusted_changed = (
        effective_trusted is not None
        and existing.trusted_customer_name != effective_trusted
    )
    if not changed_fields and not trusted_changed:
        return existing, []
    payload = existing.model_dump(
        exclude={"unknown_fields", "unknown_safety_fields"}
    )
    payload["proposed_shipment"] = refined
    payload["trusted_customer_name"] = effective_trusted
    updated = repository.save(ShipmentExtractionProposal.model_validate(payload))
    if trusted_changed:
        changed_fields = sorted({*changed_fields, "trusted_customer_name"})
    return updated, changed_fields


def process_customer_inquiry_mail(
    *,
    mail: InboundMailEnvelope,
    shipment_parser: Callable[
        [PrivacySafeText],
        ShipmentProposalSnapshot,
    ],
    proposal_repository: ExtractionProposalRepository,
    trusted_customer_name: str | None = None,
    counterparty_name_hint: str | None = None,
    evidence_origin: str = "customer_authored",
    mina_job_repository: MinaJobRepository | None = None,
) -> dict:
    """Stop customer mail at a non-authoritative extraction proposal."""

    message_key = mail.message_deduplication_key

    with _message_ingestion_lock(message_key):
        existing = _existing_proposal_for_mail(
            mail=mail,
            repository=proposal_repository,
        )

        if existing is not None:
            existing, refined_fields = _refine_existing_inbound_proposal(
                existing=existing, mail=mail, repository=proposal_repository,
                trusted_customer_name=trusted_customer_name,
                counterparty_name_hint=counterparty_name_hint,
            )
            result = _extraction_required_result(
                proposal=existing,
                ingestion_status="duplicate_existing_proposal",
            )
            if mina_job_repository is not None:
                job = mina_job_repository.find_by_proposal_id(existing.proposal_id)
                if job is not None and refined_fields and job.stage == "inquiry_received":
                    job = refine_mina_job_inbound_intake(
                        repository=mina_job_repository,
                        proposal_id=existing.proposal_id,
                        shipment=Shipment.model_validate(
                            existing.proposed_shipment.model_dump()
                        ),
                        changed_fields=refined_fields,
                        occurred_at=datetime.now(timezone.utc),
                    )
                if job is not None:
                    result.update({
                        "mina_job": job, "job_id": job.job_id,
                        "mina_code": job.mina_code,
                    })
            return result

        safe_mail, proposed_shipment = extract_shipment_proposal_from_mail(
            mail=mail,
            shipment_parser=shipment_parser,
            trusted_customer_name=trusted_customer_name,
            counterparty_name_hint=counterparty_name_hint,
        )
        proposal = create_extraction_proposal(
            mail=safe_mail,
            proposed_shipment=proposed_shipment,
            repository=proposal_repository,
            trusted_customer_name=trusted_customer_name,
            evidence_origin=evidence_origin,
        )

        result = _extraction_required_result(
            proposal=proposal,
            ingestion_status="created",
        )
        if mina_job_repository is not None:
            provisional_shipment = Shipment.model_validate(proposed_shipment.model_dump())
            job = create_mina_job_for_inbound_proposal(
                repository=mina_job_repository,
                proposal_id=proposal.proposal_id,
                shipment=provisional_shipment,
                opened_at=mail.received_at or datetime.now(timezone.utc),
            )
            result.update({"mina_job": job, "job_id": job.job_id, "mina_code": job.mina_code})
        return result
