from __future__ import annotations

from collections.abc import Iterable

from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
)


def synchronize_supplier_rfq_lifecycle(
    drafts: Iterable[SupplierRFQDraft],
    responses: Iterable[SupplierRFQResponse],
) -> list[SupplierRFQDraft]:
    latest_response_by_rfq_id: dict[str, SupplierRFQResponse] = {}

    for response in responses:
        current = latest_response_by_rfq_id.get(response.rfq_id)

        if current is None or response.received_at > current.received_at:
            latest_response_by_rfq_id[response.rfq_id] = response

    synchronized_drafts: list[SupplierRFQDraft] = []

    for draft in drafts:
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
