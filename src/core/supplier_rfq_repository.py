from __future__ import annotations

from collections.abc import Iterable
from typing import Optional, Protocol

from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQFollowUpDraft,
    SupplierRFQFollowUpManualSentEvidence,
    SupplierRFQManualSentEvidence,
    SupplierRFQResponse,
    SupplierRFQWorkflow,
)


class DuplicateSupplierRFQResponseError(ValueError):
    pass


class DuplicateSupplierRFQManualSentEvidenceError(ValueError):
    pass


class DuplicateSupplierRFQFollowUpManualSentEvidenceError(ValueError):
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

    def save_follow_up_drafts(
        self,
        drafts: Iterable[SupplierRFQFollowUpDraft],
    ) -> list[SupplierRFQFollowUpDraft]:
        ...

    def get_follow_up_draft(
        self,
        follow_up_id: str,
    ) -> Optional[SupplierRFQFollowUpDraft]:
        ...

    def list_follow_up_drafts(
        self,
        rfq_id: Optional[str] = None,
    ) -> list[SupplierRFQFollowUpDraft]:
        ...

    def save_follow_up_manual_sent_evidence(
        self,
        evidence: SupplierRFQFollowUpManualSentEvidence,
    ) -> SupplierRFQFollowUpManualSentEvidence:
        ...

    def list_follow_up_manual_sent_evidence(
        self,
        follow_up_id: Optional[str] = None,
    ) -> list[SupplierRFQFollowUpManualSentEvidence]:
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

    def get_ingested_message_evidence(
        self,
        message_key: str,
    ) -> dict[str, str] | None:
        ...

    def record_ingested_message(
        self,
        message_key: str,
        *,
        body_sha256: Optional[str] = None,
        sender_address: Optional[str] = None,
    ) -> None:
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
        response.vehicle_available_date,
        response.equipment_type,
        response.pricing_basis,
        tuple(response.included_costs or []),
        (
            response.included_costs is None
        ),
        tuple(response.excluded_costs or []),
        (
            response.excluded_costs is None
        ),
        response.notes,
        response.source,
        response.recorded_by,
        response.received_at,
        response.is_consolidated_follow_up,
        tuple(response.inherited_fields),
        response.prior_response_received_at,
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
        self._follow_up_drafts: dict[
            str, SupplierRFQFollowUpDraft
        ] = {}
        self._follow_up_manual_sent_evidence: dict[
            str, SupplierRFQFollowUpManualSentEvidence
        ] = {}
        self._ingested_message_keys: set[str] = set()
        self._ingested_message_evidence: dict[
            str,
            dict[str, str],
        ] = {}

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

    def save_follow_up_drafts(
        self,
        drafts: Iterable[SupplierRFQFollowUpDraft],
    ) -> list[SupplierRFQFollowUpDraft]:
        saved = []
        for draft in drafts:
            self._follow_up_drafts[draft.follow_up_id] = draft
            saved.append(draft)
        return saved

    def get_follow_up_draft(
        self,
        follow_up_id: str,
    ) -> Optional[SupplierRFQFollowUpDraft]:
        return self._follow_up_drafts.get(follow_up_id)

    def list_follow_up_drafts(
        self,
        rfq_id: Optional[str] = None,
    ) -> list[SupplierRFQFollowUpDraft]:
        drafts = list(self._follow_up_drafts.values())
        if rfq_id is None:
            return drafts
        return [item for item in drafts if item.rfq_id == rfq_id]

    def save_follow_up_manual_sent_evidence(
        self,
        evidence: SupplierRFQFollowUpManualSentEvidence,
    ) -> SupplierRFQFollowUpManualSentEvidence:
        if evidence.follow_up_id in self._follow_up_manual_sent_evidence:
            raise DuplicateSupplierRFQFollowUpManualSentEvidenceError(
                "Manual Supplier RFQ follow-up sent evidence already exists."
            )
        self._follow_up_manual_sent_evidence[evidence.follow_up_id] = evidence
        return evidence

    def list_follow_up_manual_sent_evidence(
        self,
        follow_up_id: Optional[str] = None,
    ) -> list[SupplierRFQFollowUpManualSentEvidence]:
        evidence = list(self._follow_up_manual_sent_evidence.values())
        if follow_up_id is None:
            return evidence
        return [item for item in evidence if item.follow_up_id == follow_up_id]

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

    def get_ingested_message_evidence(
        self,
        message_key: str,
    ) -> dict[str, str] | None:
        evidence = self._ingested_message_evidence.get(
            message_key
        )
        return (
            None
            if evidence is None
            else dict(evidence)
        )

    def record_ingested_message(
        self,
        message_key: str,
        *,
        body_sha256: Optional[str] = None,
        sender_address: Optional[str] = None,
    ) -> None:
        self._ingested_message_keys.add(message_key)

        payload = {
            "message_key": message_key,
        }

        if body_sha256 is not None:
            payload["body_sha256"] = body_sha256

        if sender_address is not None:
            payload["sender_address"] = (
                sender_address
            )

        self._ingested_message_evidence.setdefault(
            message_key,
            payload,
        )
