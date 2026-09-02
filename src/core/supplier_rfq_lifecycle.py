from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.core.mail import MailSendResult
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQFollowUpDraft,
    SupplierRFQFollowUpAutomatedSentEvidence,
    SupplierRFQFollowUpManualSentEvidence,
    SupplierRFQManualSentEvidence,
    SupplierRFQResponse,
)
from src.core.supplier_rfq_repository import (
    DuplicateSupplierRFQFollowUpAutomatedSentEvidenceError,
    DuplicateSupplierRFQFollowUpManualSentEvidenceError,
    DuplicateSupplierRFQManualSentEvidenceError,
    DuplicateSupplierRFQResponseError,
    SupplierRFQRepository,
)
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_dispatch_control import (
    SupplierSecondaryDispatchBlockedError,
    require_secondary_dispatch_allowed,
)


class SupplierRFQNotFoundError(LookupError):
    pass


class SupplierRFQTransitionError(ValueError):
    pass


class SupplierRFQFollowUpNotFoundError(LookupError):
    pass


class SupplierRFQResponseError(ValueError):
    pass


SupplierRFQResponseRejectionReason = Literal[
    "unknown_rfq_id",
    "supplier_name_mismatch",
    "priority_mismatch",
    "rfq_not_sent",
]


class RejectedSupplierRFQResponse(BaseModel):
    rfq_id: str
    supplier_name: str
    reason: SupplierRFQResponseRejectionReason


class SupplierRFQResponseValidationReport(BaseModel):
    valid_count: int
    rejected_count: int
    rejected_responses: list[RejectedSupplierRFQResponse] = Field(
        default_factory=list
    )
    source: str = "supplier_rfq_response_validator"


def validate_supplier_rfq_responses(
    drafts: Iterable[SupplierRFQDraft],
    responses: Iterable[SupplierRFQResponse],
) -> tuple[
    list[SupplierRFQResponse],
    SupplierRFQResponseValidationReport,
]:
    draft_by_rfq_id = {
        draft.rfq_id: draft
        for draft in drafts
    }

    valid_responses: list[SupplierRFQResponse] = []
    rejected_responses: list[RejectedSupplierRFQResponse] = []

    for response in responses:
        draft = draft_by_rfq_id.get(response.rfq_id)

        if draft is None:
            rejected_responses.append(
                RejectedSupplierRFQResponse(
                    rfq_id=response.rfq_id,
                    supplier_name=response.supplier_name,
                    reason="unknown_rfq_id",
                )
            )
            continue

        if response.supplier_name != draft.supplier_name:
            rejected_responses.append(
                RejectedSupplierRFQResponse(
                    rfq_id=response.rfq_id,
                    supplier_name=response.supplier_name,
                    reason="supplier_name_mismatch",
                )
            )
            continue

        if response.rfq_priority != draft.priority:
            rejected_responses.append(
                RejectedSupplierRFQResponse(
                    rfq_id=response.rfq_id,
                    supplier_name=response.supplier_name,
                    reason="priority_mismatch",
                )
            )
            continue

        if draft.status not in {
            "sent",
            "awaiting_response",
            "clarification_required",
            "responded",
        }:
            rejected_responses.append(
                RejectedSupplierRFQResponse(
                    rfq_id=response.rfq_id,
                    supplier_name=response.supplier_name,
                    reason="rfq_not_sent",
                )
            )
            continue

        valid_responses.append(response)

    report = SupplierRFQResponseValidationReport(
        valid_count=len(valid_responses),
        rejected_count=len(rejected_responses),
        rejected_responses=rejected_responses,
    )

    return valid_responses, report


def filter_valid_supplier_rfq_responses(
    drafts: Iterable[SupplierRFQDraft],
    responses: Iterable[SupplierRFQResponse],
) -> list[SupplierRFQResponse]:
    valid_responses, _ = validate_supplier_rfq_responses(
        drafts=drafts,
        responses=responses,
    )

    return valid_responses


def synchronize_supplier_rfq_lifecycle(
    drafts: Iterable[SupplierRFQDraft],
    responses: Iterable[SupplierRFQResponse],
) -> list[SupplierRFQDraft]:
    draft_list = list(drafts)
    valid_responses = filter_valid_supplier_rfq_responses(
        drafts=draft_list,
        responses=responses,
    )

    latest_response_by_rfq_id: dict[str, SupplierRFQResponse] = {}

    for response in valid_responses:
        current = latest_response_by_rfq_id.get(response.rfq_id)

        if current is None or response.received_at > current.received_at:
            latest_response_by_rfq_id[response.rfq_id] = response

    synchronized_drafts: list[SupplierRFQDraft] = []

    for draft in draft_list:
        response = latest_response_by_rfq_id.get(draft.rfq_id)

        if response is None:
            synchronized_drafts.append(draft)
            continue

        if draft.status not in {
            "sent",
            "awaiting_response",
            "clarification_required",
            "responded",
        }:
            synchronized_drafts.append(draft)
            continue

        next_status = (
            "clarification_required"
            if response.status == "needs_clarification"
            else "responded"
        )

        synchronized_drafts.append(
            SupplierRFQDraft.model_validate(
                {
                    **draft.model_dump(),
                    "status": next_status,
                    "responded_at": response.received_at,
                }
            )
        )

    return synchronized_drafts


def _get_draft(
    repository: SupplierRFQRepository,
    rfq_id: str,
) -> SupplierRFQDraft:
    draft = repository.get_draft(rfq_id)
    if draft is None:
        raise SupplierRFQNotFoundError(
            f"Supplier RFQ not found: {rfq_id}"
        )
    return draft


def approve_supplier_rfq(
    repository: SupplierRFQRepository,
    rfq_id: str,
    approved_by: str,
    approved_at: datetime | None = None,
) -> SupplierRFQDraft:
    with atomic_repository_transaction(repository):
        draft = _get_draft(repository, rfq_id)
        approver = approved_by.strip()
        if not approver:
            raise ValueError("RFQ approver identity is required.")
        try:
            require_secondary_dispatch_allowed(repository, draft)
        except SupplierSecondaryDispatchBlockedError as exc:
            raise SupplierRFQTransitionError(str(exc)) from exc
        if draft.status != "draft":
            raise SupplierRFQTransitionError(
                f"Cannot approve Supplier RFQ from status: {draft.status}"
            )
        approved = SupplierRFQDraft.model_validate(
            {
                **draft.model_dump(),
                "status": "approved",
                "approved_by": approver,
                "approved_at": approved_at or datetime.utcnow(),
            }
        )
        repository.save_drafts([approved])
        return approved


def send_supplier_rfq(
    repository: SupplierRFQRepository,
    rfq_id: str,
    send_result: MailSendResult,
) -> SupplierRFQDraft:
    with atomic_repository_transaction(repository):
        draft = _get_draft(repository, rfq_id)
        try:
            require_secondary_dispatch_allowed(repository, draft)
        except SupplierSecondaryDispatchBlockedError as exc:
            raise SupplierRFQTransitionError(str(exc)) from exc
        if draft.status != "approved":
            raise SupplierRFQTransitionError(
                f"Cannot send Supplier RFQ from status: {draft.status}"
            )
        if not draft.has_recipient:
            raise SupplierRFQTransitionError(
                "Cannot send Supplier RFQ without a recipient email."
            )
        if send_result.operation_id != f"supplier-rfq:{rfq_id}":
            raise SupplierRFQTransitionError(
                "Supplier RFQ send confirmation does not match the RFQ."
            )
        if send_result.status != "sent" or send_result.sent_at is None:
            raise SupplierRFQTransitionError(
                "Supplier RFQ requires confirmed provider send success."
            )
        awaiting = SupplierRFQDraft.model_validate(
            {
                **draft.model_dump(),
                "status": "awaiting_response",
                "sent_at": send_result.sent_at,
            }
        )
        repository.save_drafts([awaiting])
        return awaiting


def record_supplier_rfq_manually_sent(
    repository: SupplierRFQRepository,
    rfq_id: str,
    recorded_by: str,
    recorded_at: datetime | None = None,
) -> tuple[SupplierRFQDraft, SupplierRFQManualSentEvidence]:
    initial = _get_draft(repository, rfq_id)
    operator = recorded_by.strip()
    if not operator:
        raise ValueError("Manual RFQ send recorder identity is required.")
    timestamp = recorded_at or datetime.utcnow()
    evidence = SupplierRFQManualSentEvidence(
        rfq_id=rfq_id,
        recorded_by=operator,
        recorded_at=timestamp,
    )

    with atomic_repository_transaction(repository):
        current = _get_draft(repository, rfq_id)
        if current != initial:
            raise SupplierRFQTransitionError(
                "Supplier RFQ changed during manual send recording."
            )
        if current.status != "approved":
            raise SupplierRFQTransitionError(
                "Cannot record manual Supplier RFQ send from status: "
                f"{current.status}"
            )
        if not current.has_recipient:
            raise SupplierRFQTransitionError(
                "Cannot record manual Supplier RFQ send without a recipient email."
            )
        awaiting = SupplierRFQDraft.model_validate(
            {
                **current.model_dump(),
                "status": "awaiting_response",
                "sent_at": timestamp,
            }
        )
        repository.save_drafts([awaiting])
        try:
            repository.save_manual_sent_evidence(evidence)
        except DuplicateSupplierRFQManualSentEvidenceError as exc:
            raise SupplierRFQTransitionError(str(exc)) from exc

    return awaiting, evidence


def _get_follow_up(
    repository: SupplierRFQRepository,
    follow_up_id: str,
) -> SupplierRFQFollowUpDraft:
    follow_up = repository.get_follow_up_draft(follow_up_id)
    if follow_up is None:
        raise SupplierRFQFollowUpNotFoundError(
            f"Supplier RFQ follow-up not found: {follow_up_id}"
        )
    return follow_up


def approve_supplier_rfq_follow_up(
    repository: SupplierRFQRepository,
    follow_up_id: str,
    *,
    approved_by: str,
    approved_at: datetime | None = None,
) -> SupplierRFQFollowUpDraft:
    actor = approved_by.strip()
    if not actor:
        raise ValueError("Supplier RFQ follow-up approval requires an operator.")
    with atomic_repository_transaction(repository):
        current = _get_follow_up(repository, follow_up_id)
        parent = _get_draft(repository, current.rfq_id)
        if current.status != "draft":
            raise SupplierRFQTransitionError(
                "Supplier RFQ follow-up approval requires draft status; "
                f"current status is {current.status}."
            )
        if parent.status != "clarification_required":
            raise SupplierRFQTransitionError(
                "Supplier RFQ follow-up approval requires a clarification-required RFQ; "
                f"current RFQ status is {parent.status}."
            )
        approved = current.model_copy(
            update={
                "status": "approved",
                "approved_by": actor,
                "approved_at": approved_at or datetime.utcnow(),
            }
        )
        repository.save_follow_up_drafts([approved])
        return approved


def send_supplier_rfq_follow_up(
    repository: SupplierRFQRepository,
    follow_up_id: str,
    *,
    send_result: MailSendResult,
) -> SupplierRFQFollowUpDraft:
    with atomic_repository_transaction(repository):
        current = _get_follow_up(repository, follow_up_id)
        parent = _get_draft(repository, current.rfq_id)
        if current.status != "approved":
            raise SupplierRFQTransitionError(
                "Supplier RFQ follow-up send requires approved status; "
                f"current status is {current.status}."
            )
        if parent.status != "clarification_required":
            raise SupplierRFQTransitionError(
                "Supplier RFQ follow-up send requires a clarification-required RFQ; "
                f"current RFQ status is {parent.status}."
            )
        if send_result.operation_id != current.operation_id:
            raise SupplierRFQTransitionError(
                "Supplier RFQ follow-up send confirmation does not match the follow-up."
            )
        if send_result.status != "sent" or send_result.sent_at is None:
            raise SupplierRFQTransitionError(
                "Supplier RFQ follow-up requires confirmed provider send success."
            )
        sent = current.model_copy(
            update={"status": "awaiting_response", "sent_at": send_result.sent_at}
        )
        repository.save_follow_up_drafts([sent])
        return sent


def record_supplier_rfq_follow_up_manually_sent(
    repository: SupplierRFQRepository,
    follow_up_id: str,
    *,
    recorded_by: str,
    recorded_at: datetime | None = None,
) -> tuple[
    SupplierRFQFollowUpDraft,
    SupplierRFQFollowUpAutomatedSentEvidence,
    SupplierRFQFollowUpManualSentEvidence,
]:
    actor = recorded_by.strip()
    if not actor:
        raise ValueError("Supplier RFQ follow-up send evidence requires an operator.")
    timestamp = recorded_at or datetime.utcnow()
    with atomic_repository_transaction(repository):
        current = _get_follow_up(repository, follow_up_id)
        parent = _get_draft(repository, current.rfq_id)
        if current.status != "approved":
            raise SupplierRFQTransitionError(
                "Manual Supplier RFQ follow-up send requires approved status; "
                f"current status is {current.status}."
            )
        if parent.status != "clarification_required":
            raise SupplierRFQTransitionError(
                "Manual Supplier RFQ follow-up send requires a clarification-required RFQ; "
                f"current RFQ status is {parent.status}."
            )
        if repository.list_follow_up_automated_sent_evidence(follow_up_id):
            raise SupplierRFQTransitionError(
                "Supplier RFQ follow-up already has automated send evidence."
            )
        sent = current.model_copy(
            update={
                "status": "awaiting_response",
                "sent_at": timestamp,
            }
        )
        evidence = SupplierRFQFollowUpManualSentEvidence(
            follow_up_id=sent.follow_up_id,
            rfq_id=sent.rfq_id,
            sequence_number=sent.sequence_number,
            recorded_by=actor,
            recorded_at=timestamp,
        )
        repository.save_follow_up_drafts([sent])
        try:
            repository.save_follow_up_manual_sent_evidence(evidence)
        except DuplicateSupplierRFQFollowUpManualSentEvidenceError as exc:
            raise SupplierRFQTransitionError(str(exc)) from exc
        return sent, evidence


def _close_supplier_follow_up_for_response(
    repository: SupplierRFQRepository,
    *,
    rfq_id: str,
    response: SupplierRFQResponse,
) -> None:
    if response.status == "needs_clarification":
        return
    active = sorted(
        (
            item
            for item in repository.list_follow_up_drafts(rfq_id)
            if item.status in {"draft", "approved", "awaiting_response"}
        ),
        key=lambda item: item.sequence_number,
        reverse=True,
    )
    if not active:
        return
    current = active[0]
    if current.status == "awaiting_response":
        updated = current.model_copy(
            update={
                "status": "responded",
                "responded_at": response.received_at,
            }
        )
    else:
        updated = current.model_copy(update={"status": "cancelled"})
    repository.save_follow_up_drafts([updated])


def attach_supplier_rfq_response(
    repository: SupplierRFQRepository,
    response: SupplierRFQResponse,
) -> SupplierRFQDraft:
    with atomic_repository_transaction(repository):
        draft = _get_draft(repository, response.rfq_id)
        existing_responses = repository.list_responses(
            response.rfq_id
        )

        if (
            existing_responses
            and draft.status != "clarification_required"
        ):
            raise DuplicateSupplierRFQResponseError(
                f"Supplier RFQ already has a response: {response.rfq_id}"
            )

        if draft.status not in {
            "sent",
            "awaiting_response",
            "clarification_required",
        }:
            raise SupplierRFQTransitionError(
                "Supplier RFQ response requires a sent/awaiting_response RFQ; "
                f"current status is {draft.status}."
            )
        valid, report = validate_supplier_rfq_responses([draft], [response])
        if not valid:
            reason = report.rejected_responses[0].reason
            raise SupplierRFQResponseError(
                f"Supplier RFQ response rejected: {reason}"
            )
        next_status = (
            "clarification_required"
            if response.status == "needs_clarification"
            else "responded"
        )

        updated = SupplierRFQDraft.model_validate(
            {
                **draft.model_dump(),
                "status": next_status,
                "responded_at": response.received_at,
            }
        )

        repository.save_responses([response])
        repository.save_drafts([updated])
        _close_supplier_follow_up_for_response(
            repository,
            rfq_id=response.rfq_id,
            response=response,
        )

        return updated
