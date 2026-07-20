from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
)


SupplierRFQResponseRejectionReason = Literal[
    "unknown_rfq_id",
    "supplier_name_mismatch",
    "priority_mismatch",
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

        synchronized_drafts.append(
            draft.model_copy(
                update={
                    "status": "responded",
                    "responded_at": response.received_at,
                }
            )
        )

    return synchronized_drafts
