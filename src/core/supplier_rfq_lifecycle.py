from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
)
from src.core.supplier_rfq_repository import (
    DuplicateSupplierRFQResponseError,
    SupplierRFQRepository,
)


class SupplierRFQNotFoundError(LookupError):
    pass


class SupplierRFQTransitionError(ValueError):
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

        if draft.status not in {"sent", "awaiting_response", "responded"}:
            synchronized_drafts.append(draft)
            continue

        synchronized_drafts.append(
            SupplierRFQDraft.model_validate(
                {
                    **draft.model_dump(),
                    "status": "responded",
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
    draft = _get_draft(repository, rfq_id)
    approver = approved_by.strip()
    if not approver:
        raise ValueError("RFQ approver identity is required.")
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
    sent_at: datetime | None = None,
) -> SupplierRFQDraft:
    draft = _get_draft(repository, rfq_id)
    if draft.status != "approved":
        raise SupplierRFQTransitionError(
            f"Cannot send Supplier RFQ from status: {draft.status}"
        )
    if not draft.has_recipient:
        raise SupplierRFQTransitionError(
            "Cannot send Supplier RFQ without a recipient email."
        )
    awaiting = SupplierRFQDraft.model_validate(
        {
            **draft.model_dump(),
            "status": "awaiting_response",
            "sent_at": sent_at or datetime.utcnow(),
        }
    )
    repository.save_drafts([awaiting])
    return awaiting


def attach_supplier_rfq_response(
    repository: SupplierRFQRepository,
    response: SupplierRFQResponse,
) -> SupplierRFQDraft:
    draft = _get_draft(repository, response.rfq_id)
    if repository.list_responses(response.rfq_id):
        raise DuplicateSupplierRFQResponseError(
            f"Supplier RFQ already has a response: {response.rfq_id}"
        )
    if draft.status not in {"sent", "awaiting_response"}:
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
    repository.save_responses([response])
    responded = SupplierRFQDraft.model_validate(
        {
            **draft.model_dump(),
            "status": "responded",
            "responded_at": response.received_at,
        }
    )
    repository.save_drafts([responded])
    return responded
