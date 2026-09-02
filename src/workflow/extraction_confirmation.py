from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import ValidationError

from src.core.extraction_confirmation import (
    ShipmentExtractionProposal,
    ShipmentProposalSnapshot,
    utc_now,
)
from src.core.extraction_confirmation_repository import (
    ExtractionProposalRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.models import Shipment
from src.core.data_provenance import DataProvenanceError
from src.core.operational_data import OperationalDataSources
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_rfq_repository import (
    InMemorySupplierRFQRepository,
    SupplierRFQRepository,
)
from src.core.sqlite_repositories import atomic_repository_transaction
from src.workflow.pipeline import (
    build_data_provenance_blocked_result,
    process_shipment,
)


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


def _require_unchanged_resume_state(
    repository: ExtractionProposalRepository,
    expected: ShipmentExtractionProposal,
) -> None:
    current = _load_proposal(repository, expected.proposal_id)
    expected_state = (
        expected.resume_status,
        expected.resume_attempt_count,
        expected.resume_started_at,
        expected.resumed_at,
        expected.downstream_result_type,
        expected.last_resume_blocked_at,
        expected.last_resume_blocked_result_type,
    )
    current_state = (
        current.resume_status,
        current.resume_attempt_count,
        current.resume_started_at,
        current.resumed_at,
        current.downstream_result_type,
        current.last_resume_blocked_at,
        current.last_resume_blocked_result_type,
    )
    if current_state != expected_state:
        raise ExtractionConfirmationTransitionError(
            "Confirmed extraction resume state changed during processing."
        )


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
    normalized_operator = operator_identity.strip()
    if not normalized_operator:
        raise ValueError("Operator identity is required.")

    with atomic_repository_transaction(repository):
        proposal = _load_proposal(repository, proposal_id)
        if proposal.extraction_status != "proposed":
            raise ExtractionConfirmationTransitionError(
                "Extraction proposal has already been confirmed."
            )

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
    operational_data_sources: OperationalDataSources | None = None,
) -> dict:
    proposal = _load_proposal(repository, proposal_id)
    if proposal.extraction_status != "confirmed" or proposal.confirmed_shipment is None:
        raise ExtractionConfirmationTransitionError(
            "Only a confirmed extraction proposal may enter the operational workflow."
        )
    if proposal.resume_status in {"in_progress", "completed"}:
        raise ExtractionConfirmationTransitionError(
            "Confirmed extraction operational resume has already started."
        )
    if rfq_repository is None:
        rfq_repository = InMemorySupplierRFQRepository()

    started = ShipmentExtractionProposal.model_validate(
        {
            **proposal.model_dump(
                exclude={"unknown_fields", "unknown_safety_fields"}
            ),
            "resume_started_at": utc_now(),
            "resume_status": "in_progress",
            "resume_attempt_count": proposal.resume_attempt_count + 1,
        }
    )
    try:
        result = process_shipment(
            shipment=started.confirmed_shipment.model_copy(deep=True),
            email_text=proposal.inbound_mail.body_text,
            sender_address=proposal.inbound_mail.sender_address,
            customer_subject=proposal.inbound_mail.subject,
            rfq_repository=rfq_repository,
            operational_data_sources=operational_data_sources,
            approval_repository=approval_repository,
            quote_case_repository=quote_case_repository,
            _persist_rfq_transition=False,
        )
    except DataProvenanceError:
        result = build_data_provenance_blocked_result(
            started.confirmed_shipment.model_copy(deep=True)
        )
    readiness = result.get("quote_readiness")
    result_type = str(
        result.get("result_type")
        or getattr(readiness, "result_type", None)
        or "unknown"
    )
    result["result_type"] = result_type
    transactional_evidence_recorder = (
        evidence_recorder
        if getattr(repository, "store", None) is not None
        else None
    )

    if result_type == "data_provenance_blocked":
        blocked = ShipmentExtractionProposal.model_validate(
            {
                **started.model_dump(
                    exclude={"unknown_fields", "unknown_safety_fields"}
                ),
                "resume_status": "provenance_blocked",
                "last_resume_blocked_at": utc_now(),
                "last_resume_blocked_result_type": result_type,
            }
        )
        with atomic_repository_transaction(
            repository,
            transactional_evidence_recorder,
        ):
            _require_unchanged_resume_state(repository, proposal)
            blocked = repository.save(blocked)
            if evidence_recorder is not None:
                evidence_recorder.record_event(
                    event_type="confirmed_extraction_resume_blocked",
                    entity_type="extraction_proposal",
                    entity_id=blocked.proposal_id,
                    payload={
                        "proposal_id": blocked.proposal_id,
                        "result_type": result_type,
                        "resume_attempt_count": blocked.resume_attempt_count,
                    },
                )
        result["extraction_proposal"] = blocked
        return result

    resumed = ShipmentExtractionProposal.model_validate(
        {
            **started.model_dump(
                exclude={"unknown_fields", "unknown_safety_fields"}
            ),
            "resumed_at": utc_now(),
            "downstream_result_type": result_type,
            "resume_status": "completed",
        }
    )
    deferred_workflow = result.get("supplier_rfq_workflow")
    deferred_drafts = result.get("supplier_rfq_drafts") or []
    with atomic_repository_transaction(
        repository,
        rfq_repository if deferred_workflow is not None else None,
        transactional_evidence_recorder,
    ):
        _require_unchanged_resume_state(repository, proposal)
        if deferred_workflow is not None:
            result["supplier_rfq_drafts"] = rfq_repository.save_drafts(
                deferred_drafts
            )
            result["supplier_rfq_workflow"] = rfq_repository.save_workflow(
                deferred_workflow
            )
        if evidence_recorder is not None:
            evidence_recorder.record_event(
                event_type="confirmed_extraction_resumed",
                entity_type="extraction_proposal",
                entity_id=started.proposal_id,
                payload={
                    "proposal_id": started.proposal_id,
                    "confirmed_by": started.confirmed_by,
                    "confirmed_at": started.confirmed_at,
                    "result_type": result_type,
                    "result": result,
                },
            )
        resumed = repository.save(resumed)
    result["extraction_proposal"] = resumed
    return result
