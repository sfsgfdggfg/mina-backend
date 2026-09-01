from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any, TypeVar

from pydantic import BaseModel

from src.core.extraction_confirmation import ShipmentExtractionProposal
from src.core.attachment_interpretation_review import AttachmentInterpretationReview
from src.core.operational_work_assignment import OperationalWorkAssignment
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval import QuoteApproval
from src.core.quote_case import QuoteCase
from src.core.supplier_rfq import (
    SupplierRFQAutomatedSentEvidence,
    SupplierRFQDraft,
    SupplierRFQFollowUpAutomatedSentEvidence,
    SupplierRFQFollowUpDraft,
    SupplierRFQFollowUpManualSentEvidence,
    SupplierRFQManualSentEvidence,
    SupplierRFQResponse,
    SupplierRFQWorkflow,
)
from src.core.supplier_rfq_repository import (
    DuplicateSupplierRFQAutomatedSentEvidenceError,
    DuplicateSupplierRFQFollowUpAutomatedSentEvidenceError,
    DuplicateSupplierRFQFollowUpManualSentEvidenceError,
    DuplicateSupplierRFQManualSentEvidenceError,
    DuplicateSupplierRFQResponseError,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


@contextmanager
def atomic_repository_transaction(*repositories):
    stores = [
        (
            repository
            if isinstance(repository, SQLitePilotStore)
            else getattr(repository, "store", None)
        )
        for repository in repositories
        if repository is not None
    ]
    sqlite_stores = [store for store in stores if store is not None]
    if not sqlite_stores:
        yield
        return
    if len(sqlite_stores) != len(stores):
        raise ValueError(
            "Atomic transition repositories must all use SQLite or all be in-memory."
        )
    store = sqlite_stores[0]
    if any(candidate is not store for candidate in sqlite_stores[1:]):
        raise ValueError(
            "Atomic transition repositories must share one SQLitePilotStore."
        )
    if store.transaction_active:
        yield
        return
    with store.transaction():
        yield

def _model_payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_computed_fields=True)

def _model_from_payload(model_type: type[ModelT], payload: Any) -> ModelT:
    return model_type.model_validate(payload)

def _stable_payload_key(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

class SQLiteOperationalWorkAssignmentRepository:
    NAMESPACE = "operational_work_assignments"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def save(self, assignment: OperationalWorkAssignment) -> OperationalWorkAssignment:
        payload = _model_payload(assignment)
        self.store.upsert(
            namespace=self.NAMESPACE,
            record_key=assignment.work_id,
            payload=payload,
            event_type="operational_work_assignment_saved",
            entity_type="operational_work_assignment",
        )
        return _model_from_payload(OperationalWorkAssignment, payload)

    def get(self, work_id: str) -> OperationalWorkAssignment | None:
        payload = self.store.get(namespace=self.NAMESPACE, record_key=work_id)
        return None if payload is None else _model_from_payload(OperationalWorkAssignment, payload)

    def list_all(self) -> list[OperationalWorkAssignment]:
        return [
            _model_from_payload(OperationalWorkAssignment, payload)
            for payload in self.store.list_all(namespace=self.NAMESPACE)
        ]


class SQLiteAttachmentInterpretationReviewRepository:
    NAMESPACE = "attachment_interpretation_reviews"
    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store
    def save(self, review: AttachmentInterpretationReview) -> AttachmentInterpretationReview:
        payload = _model_payload(review)
        self.store.upsert(namespace=self.NAMESPACE, record_key=review.review_id, payload=payload, event_type="attachment_interpretation_review_saved", entity_type="attachment_interpretation_review")
        return _model_from_payload(AttachmentInterpretationReview, payload)
    def get(self, review_id: str) -> AttachmentInterpretationReview | None:
        payload = self.store.get(namespace=self.NAMESPACE, record_key=review_id)
        return None if payload is None else _model_from_payload(AttachmentInterpretationReview, payload)
    def list_all(self) -> list[AttachmentInterpretationReview]:
        return [_model_from_payload(AttachmentInterpretationReview, p) for p in self.store.list_all(namespace=self.NAMESPACE)]
    def find_by_source_fingerprint(self, fingerprint: str) -> AttachmentInterpretationReview | None:
        for review in self.list_all():
            if review.source_fingerprint_sha256 == fingerprint:
                return review
        return None
    def find_by_message_key(self, message_key: str) -> AttachmentInterpretationReview | None:
        for review in self.list_all():
            if review.source_message_key == message_key:
                return review
        return None

class SQLiteExtractionProposalRepository:
    NAMESPACE = "extraction_proposals"
    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store
    def save(self, proposal: ShipmentExtractionProposal) -> ShipmentExtractionProposal:
        payload = _model_payload(proposal)
        self.store.upsert(namespace=self.NAMESPACE, record_key=proposal.proposal_id, payload=payload, event_type="extraction_proposal_saved", entity_type="extraction_proposal")
        return _model_from_payload(ShipmentExtractionProposal, payload)
    def get(self, proposal_id: str) -> ShipmentExtractionProposal | None:
        payload = self.store.get(namespace=self.NAMESPACE, record_key=proposal_id)
        return None if payload is None else _model_from_payload(ShipmentExtractionProposal, payload)
    def list_all(self) -> list[ShipmentExtractionProposal]:
        return [_model_from_payload(ShipmentExtractionProposal, p) for p in self.store.list_all(namespace=self.NAMESPACE)]
    def find_by_message_key(
        self,
        message_key: str,
    ) -> ShipmentExtractionProposal | None:
        for proposal in self.list_all():
            if (
                proposal.inbound_mail.message_deduplication_key
                == message_key
            ):
                return proposal
        return None

class SQLiteSupplierRFQRepository:
    DRAFT_NAMESPACE = "supplier_rfq_drafts"
    AUTOMATED_SENT_EVIDENCE_NAMESPACE = "supplier_rfq_automated_sent_evidence"
    MANUAL_SENT_EVIDENCE_NAMESPACE = "supplier_rfq_manual_sent_evidence"
    FOLLOW_UP_DRAFT_NAMESPACE = "supplier_rfq_follow_up_drafts"
    FOLLOW_UP_AUTOMATED_SENT_EVIDENCE_NAMESPACE = (
        "supplier_rfq_follow_up_automated_sent_evidence"
    )
    FOLLOW_UP_MANUAL_SENT_EVIDENCE_NAMESPACE = (
        "supplier_rfq_follow_up_manual_sent_evidence"
    )
    WORKFLOW_NAMESPACE = "supplier_rfq_workflows"
    RESPONSE_NAMESPACE = "supplier_rfq_responses"
    INGESTED_MESSAGE_NAMESPACE = "supplier_ingested_messages"
    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store
    def save_drafts(self, drafts: Iterable[SupplierRFQDraft]) -> list[SupplierRFQDraft]:
        saved = []
        for draft in drafts:
            payload = _model_payload(draft)
            self.store.upsert(namespace=self.DRAFT_NAMESPACE, record_key=draft.rfq_id, payload=payload, event_type="supplier_rfq_draft_saved", entity_type="supplier_rfq_draft")
            saved.append(_model_from_payload(SupplierRFQDraft, payload))
        return saved
    def save_responses(self, responses: Iterable[SupplierRFQResponse]) -> list[SupplierRFQResponse]:
        saved = []
        for response in responses:
            payload = _model_payload(response)
            response_key = _stable_payload_key(payload)
            if not self.store.insert_once(namespace=self.RESPONSE_NAMESPACE, record_key=response_key, payload=payload, event_type="supplier_rfq_response_saved", entity_type="supplier_rfq_response"):
                raise DuplicateSupplierRFQResponseError("Supplier RFQ response already exists.")
            saved.append(_model_from_payload(SupplierRFQResponse, payload))
        return saved
    def get_draft(self, rfq_id: str) -> SupplierRFQDraft | None:
        payload = self.store.get(namespace=self.DRAFT_NAMESPACE, record_key=rfq_id)
        return None if payload is None else _model_from_payload(SupplierRFQDraft, payload)
    def list_drafts(self) -> list[SupplierRFQDraft]:
        return [_model_from_payload(SupplierRFQDraft, p) for p in self.store.list_all(namespace=self.DRAFT_NAMESPACE)]
    def save_automated_sent_evidence(
        self,
        evidence: SupplierRFQAutomatedSentEvidence,
    ) -> SupplierRFQAutomatedSentEvidence:
        payload = _model_payload(evidence)
        if not self.store.insert_once(
            namespace=self.AUTOMATED_SENT_EVIDENCE_NAMESPACE,
            record_key=evidence.rfq_id,
            payload=payload,
            event_type="supplier_rfq_automated_sent",
            entity_type="supplier_rfq",
        ):
            raise DuplicateSupplierRFQAutomatedSentEvidenceError(
                "Automated Supplier RFQ sent evidence already exists."
            )
        return _model_from_payload(SupplierRFQAutomatedSentEvidence, payload)

    def list_automated_sent_evidence(
        self,
        rfq_id: str | None = None,
    ) -> list[SupplierRFQAutomatedSentEvidence]:
        evidence = [
            _model_from_payload(SupplierRFQAutomatedSentEvidence, payload)
            for payload in self.store.list_all(
                namespace=self.AUTOMATED_SENT_EVIDENCE_NAMESPACE
            )
        ]
        if rfq_id is None:
            return evidence
        return [item for item in evidence if item.rfq_id == rfq_id]

    def save_manual_sent_evidence(
        self,
        evidence: SupplierRFQManualSentEvidence,
    ) -> SupplierRFQManualSentEvidence:
        payload = _model_payload(evidence)
        if not self.store.insert_once(
            namespace=self.MANUAL_SENT_EVIDENCE_NAMESPACE,
            record_key=evidence.rfq_id,
            payload=payload,
            event_type="supplier_rfq_manually_sent",
            entity_type="supplier_rfq",
        ):
            raise DuplicateSupplierRFQManualSentEvidenceError(
                "Manual Supplier RFQ sent evidence already exists."
            )
        return _model_from_payload(SupplierRFQManualSentEvidence, payload)
    def list_manual_sent_evidence(
        self,
        rfq_id: str | None = None,
    ) -> list[SupplierRFQManualSentEvidence]:
        evidence = [
            _model_from_payload(SupplierRFQManualSentEvidence, payload)
            for payload in self.store.list_all(
                namespace=self.MANUAL_SENT_EVIDENCE_NAMESPACE
            )
        ]
        if rfq_id is None:
            return evidence
        return [item for item in evidence if item.rfq_id == rfq_id]
    def save_follow_up_drafts(
        self,
        drafts: Iterable[SupplierRFQFollowUpDraft],
    ) -> list[SupplierRFQFollowUpDraft]:
        saved = []
        for draft in drafts:
            payload = _model_payload(draft)
            self.store.upsert(
                namespace=self.FOLLOW_UP_DRAFT_NAMESPACE,
                record_key=draft.follow_up_id,
                payload=payload,
                event_type="supplier_rfq_follow_up_draft_saved",
                entity_type="supplier_rfq_follow_up_draft",
            )
            saved.append(_model_from_payload(SupplierRFQFollowUpDraft, payload))
        return saved

    def get_follow_up_draft(
        self,
        follow_up_id: str,
    ) -> SupplierRFQFollowUpDraft | None:
        payload = self.store.get(
            namespace=self.FOLLOW_UP_DRAFT_NAMESPACE,
            record_key=follow_up_id,
        )
        return (
            None
            if payload is None
            else _model_from_payload(SupplierRFQFollowUpDraft, payload)
        )

    def list_follow_up_drafts(
        self,
        rfq_id: str | None = None,
    ) -> list[SupplierRFQFollowUpDraft]:
        drafts = [
            _model_from_payload(SupplierRFQFollowUpDraft, payload)
            for payload in self.store.list_all(
                namespace=self.FOLLOW_UP_DRAFT_NAMESPACE
            )
        ]
        return drafts if rfq_id is None else [d for d in drafts if d.rfq_id == rfq_id]

    def save_follow_up_automated_sent_evidence(
        self,
        evidence: SupplierRFQFollowUpAutomatedSentEvidence,
    ) -> SupplierRFQFollowUpAutomatedSentEvidence:
        payload = _model_payload(evidence)
        if not self.store.insert_once(
            namespace=self.FOLLOW_UP_AUTOMATED_SENT_EVIDENCE_NAMESPACE,
            record_key=evidence.follow_up_id,
            payload=payload,
            event_type="supplier_rfq_follow_up_automated_sent",
            entity_type="supplier_rfq_follow_up",
        ):
            raise DuplicateSupplierRFQFollowUpAutomatedSentEvidenceError(
                "Automated Supplier RFQ follow-up sent evidence already exists."
            )
        return _model_from_payload(
            SupplierRFQFollowUpAutomatedSentEvidence, payload
        )

    def list_follow_up_automated_sent_evidence(
        self,
        follow_up_id: str | None = None,
    ) -> list[SupplierRFQFollowUpAutomatedSentEvidence]:
        evidence = [
            _model_from_payload(
                SupplierRFQFollowUpAutomatedSentEvidence, payload
            )
            for payload in self.store.list_all(
                namespace=self.FOLLOW_UP_AUTOMATED_SENT_EVIDENCE_NAMESPACE
            )
        ]
        return (
            evidence
            if follow_up_id is None
            else [e for e in evidence if e.follow_up_id == follow_up_id]
        )

    def save_follow_up_manual_sent_evidence(
        self,
        evidence: SupplierRFQFollowUpManualSentEvidence,
    ) -> SupplierRFQFollowUpManualSentEvidence:
        payload = _model_payload(evidence)
        if not self.store.insert_once(
            namespace=self.FOLLOW_UP_MANUAL_SENT_EVIDENCE_NAMESPACE,
            record_key=evidence.follow_up_id,
            payload=payload,
            event_type="supplier_rfq_follow_up_manually_sent",
            entity_type="supplier_rfq_follow_up",
        ):
            raise DuplicateSupplierRFQFollowUpManualSentEvidenceError(
                "Manual Supplier RFQ follow-up sent evidence already exists."
            )
        return _model_from_payload(
            SupplierRFQFollowUpManualSentEvidence, payload
        )

    def list_follow_up_manual_sent_evidence(
        self,
        follow_up_id: str | None = None,
    ) -> list[SupplierRFQFollowUpManualSentEvidence]:
        evidence = [
            _model_from_payload(
                SupplierRFQFollowUpManualSentEvidence, payload
            )
            for payload in self.store.list_all(
                namespace=self.FOLLOW_UP_MANUAL_SENT_EVIDENCE_NAMESPACE
            )
        ]
        return (
            evidence
            if follow_up_id is None
            else [e for e in evidence if e.follow_up_id == follow_up_id]
        )

    def save_workflow(self, workflow: SupplierRFQWorkflow) -> SupplierRFQWorkflow:
        payload = _model_payload(workflow)
        self.store.upsert(namespace=self.WORKFLOW_NAMESPACE, record_key=workflow.workflow_id, payload=payload, event_type="supplier_rfq_workflow_saved", entity_type="supplier_rfq_workflow")
        return _model_from_payload(SupplierRFQWorkflow, payload)
    def get_workflow(self, workflow_id: str) -> SupplierRFQWorkflow | None:
        payload = self.store.get(namespace=self.WORKFLOW_NAMESPACE, record_key=workflow_id)
        return None if payload is None else _model_from_payload(SupplierRFQWorkflow, payload)
    def list_responses(self, rfq_id: str | None = None) -> list[SupplierRFQResponse]:
        responses = [_model_from_payload(SupplierRFQResponse, p) for p in self.store.list_all(namespace=self.RESPONSE_NAMESPACE)]
        return responses if rfq_id is None else [r for r in responses if r.rfq_id == rfq_id]
    def has_ingested_message(self, message_key: str) -> bool:
        return self.store.exists(
            namespace=self.INGESTED_MESSAGE_NAMESPACE,
            record_key=message_key,
        )

    def get_ingested_message_evidence(
        self,
        message_key: str,
    ) -> dict[str, str] | None:
        payload = self.store.get(
            namespace=self.INGESTED_MESSAGE_NAMESPACE,
            record_key=message_key,
        )

        if not isinstance(payload, dict):
            return None

        return {
            str(key): str(value)
            for key, value in payload.items()
        }

    def record_ingested_message(
        self,
        message_key: str,
        *,
        body_sha256: str | None = None,
        sender_address: str | None = None,
        attachment_source_sha256: str | None = None,
        attachment_review_id: str | None = None,
    ) -> None:
        payload = {
            "message_key": message_key,
        }

        if body_sha256 is not None:
            payload["body_sha256"] = body_sha256

        if sender_address is not None:
            payload["sender_address"] = (
                sender_address
            )
        if attachment_source_sha256 is not None:
            payload["attachment_source_sha256"] = attachment_source_sha256
        if attachment_review_id is not None:
            payload["attachment_review_id"] = attachment_review_id

        self.store.insert_once(
            namespace=self.INGESTED_MESSAGE_NAMESPACE,
            record_key=message_key,
            payload=payload,
            event_type="supplier_message_ingested",
            entity_type="supplier_ingested_message",
        )


class SQLiteQuoteApprovalRepository:
    NAMESPACE = "quote_approvals"
    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store
    def save(self, approval: QuoteApproval) -> QuoteApproval:
        payload = _model_payload(approval)
        self.store.upsert(namespace=self.NAMESPACE, record_key=approval.approval_id, payload=payload, event_type="quote_approval_saved", entity_type="quote_approval")
        return _model_from_payload(QuoteApproval, payload)
    def save_many(self, approvals: Iterable[QuoteApproval]) -> list[QuoteApproval]:
        return [self.save(a) for a in approvals]
    def get(self, approval_id: str) -> QuoteApproval | None:
        payload = self.store.get(namespace=self.NAMESPACE, record_key=approval_id)
        return None if payload is None else _model_from_payload(QuoteApproval, payload)
    def list_all(self) -> list[QuoteApproval]:
        return [_model_from_payload(QuoteApproval, p) for p in self.store.list_all(namespace=self.NAMESPACE)]

class SQLiteQuoteCaseRepository:
    NAMESPACE = "quote_cases"
    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store
    def save(self, quote_case: QuoteCase) -> QuoteCase:
        payload = _model_payload(quote_case)
        self.store.upsert(namespace=self.NAMESPACE, record_key=quote_case.case_id, payload=payload, event_type="quote_case_saved", entity_type="quote_case")
        return _model_from_payload(QuoteCase, payload)
    def save_many(self, quote_cases: Iterable[QuoteCase]) -> list[QuoteCase]:
        return [self.save(c) for c in quote_cases]
    def get(self, case_id: str) -> QuoteCase | None:
        payload = self.store.get(namespace=self.NAMESPACE, record_key=case_id)
        return None if payload is None else _model_from_payload(QuoteCase, payload)
    def list_all(self) -> list[QuoteCase]:
        return [_model_from_payload(QuoteCase, p) for p in self.store.list_all(namespace=self.NAMESPACE)]
