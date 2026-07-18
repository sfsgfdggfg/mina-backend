from __future__ import annotations

from collections.abc import Iterable

from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
)


def filter_valid_supplier_rfq_responses(
    drafts: Iterable[SupplierRFQDraft],
    responses: Iterable[SupplierRFQResponse],
) -> list[SupplierRFQResponse]:
    draft_by_rfq_id = {
        draft.rfq_id: draft
        for draft in drafts
    }

    valid_responses: list[SupplierRFQResponse] = []

    for response in responses:
        draft = draft_by_rfq_id.get(response.rfq_id)

        if draft is None:
            continue

        if response.supplier_name != draft.supplier_name:
            continue

        if response.rfq_priority != draft.priority:
            continue

        valid_responses.append(response)

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
