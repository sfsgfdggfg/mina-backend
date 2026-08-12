from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import ValidationError

from src.core.extraction_confirmation import (
    SAFETY_SENSITIVE_FIELDS,
    ShipmentExtractionProposal,
    ShipmentProposalSnapshot,
    utc_now,
)
from src.core.extraction_confirmation_repository import (
    ExtractionProposalRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.models import Shipment
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.workflow.pipeline import process_shipment


class PilotEvidenceRecorder(Protocol):
    def record_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: Any,
    ) -> None:
        ...


class ExtractionProposalNotFoundError(LookupError):
    pass


class ExtractionConfirmationTransitionError(ValueError):
    pass


class ExtractionCorrectionError(ValueError):
    pass


class UnresolvedSafetyFactsError(ValueError):
    pass


def create_extraction_proposal(
    *,
    mail: InboundMailEnvelope,
    proposed_shipment: ShipmentProposalSnapshot,
    repository: ExtractionProposalRepository,
) -> ShipmentExtractionProposal:
    if not isinstance(proposed_shipment, ShipmentProposalSnapshot):
        raise TypeError(
            "Customer inquiry parser must return a ShipmentProposalSnapshot."
        )
    return repository.save(
        ShipmentExtractionProposal(
            inbound_mail=mail,
            proposed_shipment=proposed_shipment,
        )
    )


def _load_proposal(
    repository: ExtractionProposalRepository,
    proposal_id: str,
) -> ShipmentExtractionProposal:
    proposal = repository.get(proposal_id)
    if proposal is None:
        raise ExtractionProposalNotFoundError(
            f"Extraction proposal not found: {proposal_id}"
        )
    return proposal


def _validated_confirmed_shipment(
    proposed: ShipmentProposalSnapshot,
    corrections: dict[str, Any],
) -> tuple[Shipment, dict[str, Any], list[str]]:
    blocked_fields = {"regulatory_exception_reviews"}
    unknown_fields = set(corrections) - set(ShipmentProposalSnapshot.model_fields)
    if unknown_fields:
        raise ExtractionCorrectionError(
            "Unknown shipment correction fields: "
            + ", ".join(sorted(unknown_fields))
        )
    disallowed_fields = set(corrections).intersection(blocked_fields)
    if disallowed_fields:
        raise ExtractionCorrectionError(
            "System-managed shipment fields cannot be corrected here: "
            + ", ".join(sorted(disallowed_fields))
        )

    candidate_data = proposed.model_dump()
    candidate_data.update(corrections)
    try:
        candidate = ShipmentProposalSnapshot.model_validate(candidate_data)
    except ValidationError as exc:
        raise ExtractionCorrectionError(
            "Shipment corrections are invalid."
        ) from exc

    unresolved = [
        field_name
        for field_name in SAFETY_SENSITIVE_FIELDS
        if getattr(candidate, field_name) is None
    ]
    if unresolved:
        raise UnresolvedSafetyFactsError(
            "Safety-sensitive facts require explicit human resolution: "
            + ", ".join(unresolved)
        )
    if candidate.is_adr is False and candidate.adr_class is not None:
        raise ExtractionCorrectionError(
            "ADR class must be empty when ADR status is explicitly false."
        )
    if (
        candidate.is_temperature_controlled is False
        and candidate.temperature_requirement is not None
    ):
        raise ExtractionCorrectionError(
            "Temperature requirement must be empty when temperature control "
            "is explicitly false."
        )

    candidate_dump = candidate.model_dump()
    confirmed = Shipment.model_validate(candidate_dump)
    proposed_data = proposed.model_dump()
    changed_fields = sorted(
        field_name
        for field_name in ShipmentProposalSnapshot.model_fields
        if proposed_data.get(field_name) != candidate_dump.get(field_name)
    )
    normalized_corrections = {
        field_name: candidate_dump.get(field_name)
        for field_name in changed_fields
    }
    return confirmed, normalized_corrections, changed_fields


def confirm_extraction_proposal(
    *,
    repository: ExtractionProposalRepository,
    proposal_id: str,
    operator_identity: str,
    corrections: dict[str, Any] | None = None,
    confirmed_at: datetime | None = None,
) -> ShipmentExtractionProposal:
    proposal = _load_proposal(repository, proposal_id)
    if proposal.extraction_status != "proposed":
        raise ExtractionConfirmationTransitionError(
            "Extraction proposal has already been confirmed."
        )
    normalized_operator = operator_identity.strip()
    if not normalized_operator:
        raise ValueError("Operator identity is required.")

    confirmed_shipment, normalized_corrections, changed_fields = (
        _validated_confirmed_shipment(
            proposal.proposed_shipment,
            corrections or {},
        )
    )
    updated = ShipmentExtractionProposal.model_validate(
        {
            **proposal.model_dump(
                exclude={"unknown_fields", "unknown_safety_fields"}
            ),
            "extraction_status": "confirmed",
            "confirmed_shipment": confirmed_shipment,
            "operator_corrections": normalized_corrections,
            "changed_fields": changed_fields,
            "confirmed_by": normalized_operator,
            "confirmed_at": confirmed_at or utc_now(),
        }
    )
    return repository.save(updated)


def resume_confirmed_extraction(
    *,
    repository: ExtractionProposalRepository,
    proposal_id: str,
    rfq_repository: SupplierRFQRepository | None = None,
    approval_repository: QuoteApprovalRepository | None = None,
    quote_case_repository: QuoteCaseRepository | None = None,
    evidence_recorder: PilotEvidenceRecorder | None = None,
) -> dict:
    proposal = _load_proposal(repository, proposal_id)
    if proposal.extraction_status != "confirmed" or proposal.confirmed_shipment is None:
        raise ExtractionConfirmationTransitionError(
            "Only a confirmed extraction proposal may enter the operational workflow."
        )
    if proposal.resumed_at is not None:
        raise ExtractionConfirmationTransitionError(
            "Confirmed extraction proposal has already been resumed."
        )

    result = process_shipment(
        shipment=proposal.confirmed_shipment.model_copy(deep=True),
        email_text=proposal.inbound_mail.body_text,
        sender_address=proposal.inbound_mail.sender_address,
        rfq_repository=rfq_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
    )
    readiness = result.get("quote_readiness")
    result_type = str(
        result.get("result_type")
        or getattr(readiness, "result_type", None)
        or "unknown"
    )
    result["result_type"] = result_type

    if evidence_recorder is not None:
        evidence_recorder.record_event(
            event_type="confirmed_extraction_resumed",
            entity_type="extraction_proposal",
            entity_id=proposal.proposal_id,
            payload={
                "proposal_id": proposal.proposal_id,
                "confirmed_by": proposal.confirmed_by,
                "confirmed_at": proposal.confirmed_at,
                "result_type": result_type,
                "result": result,
            },
        )

    resumed = ShipmentExtractionProposal.model_validate(
        {
            **proposal.model_dump(
                exclude={"unknown_fields", "unknown_safety_fields"}
            ),
            "resumed_at": utc_now(),
            "downstream_result_type": result_type,
        }
    )
    resumed = repository.save(resumed)
    result["extraction_proposal"] = resumed
    return result
