from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.core.air_operation_handoff import (
    AirOperationCustomerQuoteSentEvidence,
    AirOperationHandoff,
)
from src.core.air_operation_handoff_repository import (
    AirOperationHandoffConflictError,
    AirOperationHandoffRepository,
)
from src.core.mina_job import MinaJob, MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import transition_mina_job_stage
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.sqlite_repositories import atomic_repository_transaction


class AirOperationHandoffNotFoundError(LookupError):
    pass


class AirOperationHandoffTransitionError(ValueError):
    pass


class AirOperationHandoffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["prepared", "existing"]
    handoff: AirOperationHandoff
    mina_job: MinaJob
    created: bool = False
    booking_confirmed: bool = False
    airline_contact_performed: bool = False
    booking_authority: bool = False
    outbound_authority: bool = False
    runtime_authoritative: bool = False


def _aware(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Air operation handoff timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _operator(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def _acceptance_event(repository: MinaJobRepository, job_id: str) -> MinaJobEvent:
    matches = [
        event
        for event in repository.list_events(job_id)
        if event.event_type == "stage_changed"
        and isinstance(event.metadata, dict)
        and event.metadata.get("to_stage") == "accepted"
    ]
    if len(matches) != 1:
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_requires_exactly_one_customer_acceptance_event"
        )
    event = matches[0]
    if not event.actor:
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_acceptance_event_missing_actor"
        )
    return event


def _sent_evidence(
    quote_case: QuoteCase,
    *,
    approval_id: str,
    revision_number: int,
) -> list[AirOperationCustomerQuoteSentEvidence]:
    items: list[AirOperationCustomerQuoteSentEvidence] = []
    for evidence in quote_case.manual_sent_evidence:
        if evidence.approval_id == approval_id and evidence.revision_number == revision_number:
            items.append(
                AirOperationCustomerQuoteSentEvidence(
                    evidence_kind="manual_external_send",
                    approval_id=approval_id,
                    revision_number=revision_number,
                    recipient_email=evidence.recipient_email,
                    sent_at=evidence.sent_at,
                )
            )
    for evidence in quote_case.automated_sent_evidence:
        if evidence.approval_id == approval_id and evidence.revision_number == revision_number:
            items.append(
                AirOperationCustomerQuoteSentEvidence(
                    evidence_kind="automated_provider_send",
                    approval_id=approval_id,
                    revision_number=revision_number,
                    recipient_email=evidence.recipient_email,
                    sent_at=evidence.sent_at,
                    provider_name=evidence.provider_name,
                    provider_message_id=evidence.provider_message_id,
                )
            )
    for evidence in quote_case.send_reconciliation_evidence:
        if (
            evidence.approval_id == approval_id
            and evidence.revision_number == revision_number
            and evidence.outcome == "confirmed_sent"
            and evidence.observed_sent_at is not None
        ):
            items.append(
                AirOperationCustomerQuoteSentEvidence(
                    evidence_kind="operator_provider_reconciliation",
                    approval_id=approval_id,
                    revision_number=revision_number,
                    recipient_email=evidence.recipient_email,
                    sent_at=evidence.observed_sent_at,
                )
            )
    return sorted(
        items,
        key=lambda item: (
            item.sent_at,
            item.evidence_kind,
            item.recipient_email,
            item.provider_message_id or "",
        ),
    )


def _load_chain(
    *,
    job_id: str,
    mina_repository: MinaJobRepository,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
):
    job = mina_repository.get(job_id)
    if job is None:
        raise AirOperationHandoffNotFoundError(f"MINA job not found: {job_id}")
    if job.lifecycle_version != 2 or job.job_kind != "price_request":
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_requires_price_request_lifecycle_v2"
        )
    if job.shipment.transport_mode != "air":
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_requires_air_shipment"
        )
    if not job.quote_case_id:
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_requires_linked_quote_case"
        )
    quote_case = quote_case_repository.get(job.quote_case_id)
    if quote_case is None:
        raise AirOperationHandoffNotFoundError(
            f"Quote case not found: {job.quote_case_id}"
        )
    if quote_case.mina_job_id != job.job_id or quote_case.mina_code != job.mina_code:
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_quote_case_job_mismatch"
        )
    if quote_case.air_quote_context is None:
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_requires_frozen_air_quote_context"
        )
    if (
        quote_case.supplier_quote is None
        or quote_case.customer_quote is None
        or quote_case.quote_draft is None
        or quote_case.quote_approval is None
    ):
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_quote_case_incomplete"
        )
    approval_id = quote_case.quote_approval.approval_id
    approval = approval_repository.get(approval_id)
    if approval is None:
        raise AirOperationHandoffNotFoundError(
            f"Quote approval not found: {approval_id}"
        )
    if approval.approval_status != "approved":
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_requires_current_approved_quote"
        )
    if approval.air_quote_context_snapshot != quote_case.air_quote_context:
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_air_context_snapshot_mismatch"
        )
    if not approval.is_valid_for_quote(
        supplier_quote=quote_case.supplier_quote,
        customer_quote=quote_case.customer_quote,
        quote_draft=quote_case.quote_draft,
    ):
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_current_approval_snapshot_mismatch"
        )
    revision_number = len(quote_case.quote_revisions)
    sent = _sent_evidence(
        quote_case,
        approval_id=approval.approval_id,
        revision_number=revision_number,
    )
    if not sent:
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_requires_durable_current_quote_sent_evidence"
        )
    acceptance = _acceptance_event(mina_repository, job.job_id)
    if any(item.sent_at > acceptance.occurred_at for item in sent):
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_quote_sent_evidence_after_customer_acceptance"
        )
    return job, quote_case, approval, revision_number, sent, acceptance


def prepare_air_operation_handoff(
    *,
    job_id: str,
    handed_off_by: str,
    handoff_repository: AirOperationHandoffRepository,
    mina_repository: MinaJobRepository,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
    handed_off_at: datetime | None = None,
) -> AirOperationHandoffResult:
    normalized_job_id = str(job_id or "").strip()
    if not normalized_job_id:
        raise ValueError("job_id is required")
    operator = _operator(handed_off_by)
    current_time = _aware(handed_off_at)

    existing = handoff_repository.find_by_job(normalized_job_id)
    if existing is not None:
        job = mina_repository.get(normalized_job_id)
        if job is None:
            raise AirOperationHandoffNotFoundError(
                f"MINA job not found: {normalized_job_id}"
            )
        return AirOperationHandoffResult(
            status="existing", handoff=existing, mina_job=job, created=False
        )

    job, quote_case, approval, revision_number, sent, acceptance = _load_chain(
        job_id=normalized_job_id,
        mina_repository=mina_repository,
        quote_case_repository=quote_case_repository,
        approval_repository=approval_repository,
    )
    if job.stage != "accepted":
        raise AirOperationHandoffTransitionError(
            f"air_operation_handoff_requires_accepted_job:{job.stage}"
        )
    if current_time < acceptance.occurred_at:
        raise AirOperationHandoffTransitionError(
            "air_operation_handoff_time_cannot_precede_customer_acceptance"
        )

    candidate = AirOperationHandoff(
        job_id=job.job_id,
        mina_code=job.mina_code,
        quote_case_id=quote_case.case_id,
        approval_id=approval.approval_id,
        revision_number=revision_number,
        air_quote_context=quote_case.air_quote_context,
        customer_quote_sent_evidence=sent,
        accepted_by=acceptance.actor,
        accepted_at=acceptance.occurred_at,
        handed_off_by=operator,
        handed_off_at=current_time,
    )

    try:
        with atomic_repository_transaction(
            handoff_repository,
            mina_repository,
            quote_case_repository,
            approval_repository,
        ):
            concurrent = handoff_repository.find_by_job(normalized_job_id)
            if concurrent is not None:
                return AirOperationHandoffResult(
                    status="existing",
                    handoff=concurrent,
                    mina_job=mina_repository.get(normalized_job_id) or job,
                    created=False,
                )
            (
                current_job,
                current_case,
                current_approval,
                current_revision,
                current_sent,
                current_acceptance,
            ) = _load_chain(
                job_id=normalized_job_id,
                mina_repository=mina_repository,
                quote_case_repository=quote_case_repository,
                approval_repository=approval_repository,
            )
            if current_job.stage != "accepted":
                raise AirOperationHandoffTransitionError(
                    f"air_operation_handoff_requires_accepted_job:{current_job.stage}"
                )
            current_candidate = candidate.model_copy(
                update={
                    "quote_case_id": current_case.case_id,
                    "approval_id": current_approval.approval_id,
                    "revision_number": current_revision,
                    "air_quote_context": current_case.air_quote_context,
                    "customer_quote_sent_evidence": current_sent,
                    "accepted_by": current_acceptance.actor,
                    "accepted_at": current_acceptance.occurred_at,
                }
            )
            if current_candidate.model_dump(exclude={"handoff_id"}) != candidate.model_dump(
                exclude={"handoff_id"}
            ):
                raise AirOperationHandoffTransitionError(
                    "air_operation_handoff_evidence_changed_during_preparation"
                )
            saved, created = handoff_repository.create(candidate)
            if not created:
                return AirOperationHandoffResult(
                    status="existing", handoff=saved, mina_job=current_job, created=False
                )
            updated_job = transition_mina_job_stage(
                repository=mina_repository,
                mina_code=current_job.mina_code,
                target_stage="operation_opened",
                actor=operator,
                reason="accepted_air_quote_handed_off_without_booking",
                occurred_at=current_time,
                air_operation_handoff_repository=handoff_repository,
            )
            mina_repository.append_event(
                MinaJobEvent(
                    job_id=updated_job.job_id,
                    mina_code=updated_job.mina_code,
                    event_type="air_operation_handoff_created",
                    occurred_at=current_time,
                    actor=operator,
                    resource_type="air_operation_handoff",
                    resource_id=saved.handoff_id,
                    metadata={
                        "quote_case_id": saved.quote_case_id,
                        "approval_id": saved.approval_id,
                        "revision_number": saved.revision_number,
                        "source_id": saved.air_quote_context.source_id,
                        "candidate_id": saved.air_quote_context.candidate_id,
                        "service_date": saved.air_quote_context.service_date.isoformat(),
                        "booking_confirmed": False,
                        "airline_contact_performed": False,
                    },
                )
            )
    except AirOperationHandoffConflictError as exc:
        raise AirOperationHandoffTransitionError(str(exc)) from exc

    return AirOperationHandoffResult(
        status="prepared", handoff=saved, mina_job=updated_job, created=True
    )


def build_air_operation_handoff_view(
    *,
    handoff_repository: AirOperationHandoffRepository,
    mina_repository: MinaJobRepository,
    job_id: str,
) -> dict:
    job = mina_repository.get(job_id)
    if job is None:
        raise AirOperationHandoffNotFoundError(f"MINA job not found: {job_id}")
    handoff = handoff_repository.find_by_job(job_id)
    return {
        "job_id": job.job_id,
        "mina_code": job.mina_code,
        "stage": job.stage,
        "handoff": None if handoff is None else handoff.model_dump(mode="json"),
        "handoff_exists": handoff is not None,
        "booking_confirmed": False if handoff is None else handoff.booking_confirmed,
        "airline_contact_performed": False if handoff is None else handoff.airline_contact_performed,
        "booking_authority": False,
        "outbound_authority": False,
        "runtime_authoritative": False,
    }
