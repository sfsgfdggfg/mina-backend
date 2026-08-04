from __future__ import annotations

from collections.abc import Iterable
from typing import Optional, Protocol

from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
)


class SupplierRFQRepository(Protocol):
    def save_drafts(
        self,
        drafts: Iterable[SupplierRFQDraft],
    ) -> list[SupplierRFQDraft]:
        ...

    def save_responses(
        self,
        responses: Iterable[SupplierRFQResponse],
    ) -> list[SupplierRFQResponse]:
        ...

    def get_draft(
        self,
        rfq_id: str,
    ) -> Optional[SupplierRFQDraft]:
        ...

    def list_drafts(self) -> list[SupplierRFQDraft]:
        ...

    def list_responses(
        self,
        rfq_id: Optional[str] = None,
    ) -> list[SupplierRFQResponse]:
        ...


def _supplier_rfq_response_key(
    response: SupplierRFQResponse,
) -> tuple:
    return (
        response.rfq_id,
        response.supplier_name,
        response.rfq_priority,
        response.status,
        response.cost,
        response.currency,
        response.transit_time,
        response.validity_date,
        response.equipment_type,
        response.notes,
        response.source,
        response.received_at,
    )


class InMemorySupplierRFQRepository:
    def __init__(self) -> None:
        self._drafts: dict[str, SupplierRFQDraft] = {}
        self._responses: list[SupplierRFQResponse] = []
        self._response_keys: set[tuple] = set()

    def save_drafts(
        self,
        drafts: Iterable[SupplierRFQDraft],
    ) -> list[SupplierRFQDraft]:
        saved = []

        for draft in drafts:
            self._drafts[draft.rfq_id] = draft
            saved.append(draft)

        return saved

    def save_responses(
        self,
        responses: Iterable[SupplierRFQResponse],
    ) -> list[SupplierRFQResponse]:
        saved = []

        for response in responses:
            response_key = _supplier_rfq_response_key(response)

            if response_key in self._response_keys:
                continue

            self._response_keys.add(response_key)
            self._responses.append(response)
            saved.append(response)

        return saved

    def get_draft(
        self,
        rfq_id: str,
    ) -> Optional[SupplierRFQDraft]:
        return self._drafts.get(rfq_id)

    def list_drafts(self) -> list[SupplierRFQDraft]:
        return list(self._drafts.values())

    def list_responses(
        self,
        rfq_id: Optional[str] = None,
    ) -> list[SupplierRFQResponse]:
        if rfq_id is None:
            return list(self._responses)

        return [
            response
            for response in self._responses
            if response.rfq_id == rfq_id
        ]
