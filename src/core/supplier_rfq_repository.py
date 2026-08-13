from __future__ import annotations

from collections.abc import Iterable
from typing import Optional, Protocol

from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQManualSentEvidence,
    SupplierRFQResponse,
    SupplierRFQWorkflow,
)


class DuplicateSupplierRFQResponseError(ValueError):
    pass


class DuplicateSupplierRFQManualSentEvidenceError(ValueError):
    pass


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

    def save_manual_sent_evidence(
        self,
        evidence: SupplierRFQManualSentEvidence,
    ) -> SupplierRFQManualSentEvidence:
        ...

    def list_manual_sent_evidence(
        self,
        rfq_id: Optional[str] = None,
    ) -> list[SupplierRFQManualSentEvidence]:
        ...

    def save_workflow(
        self,
        workflow: SupplierRFQWorkflow,
    ) -> SupplierRFQWorkflow:
        ...

    def get_workflow(
        self,
        workflow_id: str,
    ) -> Optional[SupplierRFQWorkflow]:
        ...

    def list_responses(
        self,
        rfq_id: Optional[str] = None,
    ) -> list[SupplierRFQResponse]:
        ...

    def has_ingested_message(self, message_key: str) -> bool:
        ...

    def record_ingested_message(self, message_key: str) -> None:
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
        self._workflows: dict[str, SupplierRFQWorkflow] = {}
        self._responses: list[SupplierRFQResponse] = []
        self._response_keys: set[tuple] = set()
        self._manual_sent_evidence: dict[
            str, SupplierRFQManualSentEvidence
        ] = {}
        self._ingested_message_keys: set[str] = set()

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
                raise DuplicateSupplierRFQResponseError(
                    "Supplier RFQ response already exists."
                )

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

    def save_manual_sent_evidence(
        self,
        evidence: SupplierRFQManualSentEvidence,
    ) -> SupplierRFQManualSentEvidence:
        if evidence.rfq_id in self._manual_sent_evidence:
            raise DuplicateSupplierRFQManualSentEvidenceError(
                "Manual Supplier RFQ sent evidence already exists."
            )
        self._manual_sent_evidence[evidence.rfq_id] = evidence
        return evidence

    def list_manual_sent_evidence(
        self,
        rfq_id: Optional[str] = None,
    ) -> list[SupplierRFQManualSentEvidence]:
        evidence = list(self._manual_sent_evidence.values())
        if rfq_id is None:
            return evidence
        return [item for item in evidence if item.rfq_id == rfq_id]

    def save_workflow(
        self,
        workflow: SupplierRFQWorkflow,
    ) -> SupplierRFQWorkflow:
        self._workflows[workflow.workflow_id] = workflow
        return workflow

    def get_workflow(
        self,
        workflow_id: str,
    ) -> Optional[SupplierRFQWorkflow]:
        return self._workflows.get(workflow_id)

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

    def has_ingested_message(self, message_key: str) -> bool:
        return message_key in self._ingested_message_keys

    def record_ingested_message(self, message_key: str) -> None:
        self._ingested_message_keys.add(message_key)
