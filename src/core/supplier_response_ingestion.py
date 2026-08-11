from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.supplier_rfq import (
    SUPPLIER_RFQ_REFERENCE_PREFIX,
    SupplierRFQDraft,
    SupplierRFQResponse,
    SupplierRFQResponseStatus,
)
from src.core.supplier_rfq_repository import SupplierRFQRepository


InboundSupplierReplySource = Literal[
    "email",
    "manual",
    "portal",
    "api",
]

CommercialResponseField = Literal[
    "status",
    "cost",
    "currency",
    "transit_time",
    "validity_date",
    "equipment_type",
    "notes",
]

CommercialFieldState = Literal[
    "provided",
    "not_provided",
    "uncertain",
]

SupplierRFQCorrelationMethod = Literal[
    "explicit_reference",
    "subject_reference",
    "supplier_identity",
]

SupplierRFQCorrelationStatus = Literal[
    "matched",
    "unresolved_rfq",
    "ambiguous_rfq",
    "invalid_supplier",
    "rfq_not_awaiting_response",
]

SupplierReplyIngestionStatus = Literal[
    "response_attached",
    "unresolved_rfq",
    "ambiguous_rfq",
    "invalid_supplier",
    "invalid_response",
    "duplicate_response",
    "rfq_not_awaiting_response",
    "parsing_required",
    "parsing_failed",
]


class InboundSupplierReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_address: str
    sender_name: Optional[str] = None
    subject: Optional[str] = None
    body_text: str
    received_at: Optional[datetime] = None
    external_message_id: Optional[str] = None
    explicit_rfq_reference: Optional[str] = None
    source: InboundSupplierReplySource = "manual"
    provider_name: Optional[str] = None

    @field_validator("sender_address")
    @classmethod
    def normalize_sender_address(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized or "@" not in normalized:
            raise ValueError("A valid supplier sender address is required.")
        return normalized

    @field_validator(
        "sender_name",
        "subject",
        "external_message_id",
        "explicit_rfq_reference",
        "provider_name",
    )
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @property
    def message_deduplication_key(self) -> Optional[str]:
        if self.external_message_id is None:
            return None
        namespace = (self.provider_name or self.source).strip().lower()
        return f"{namespace}:{self.external_message_id}"


class SupplierResponseExtraction(BaseModel):
    """Commercial-only parser output; it carries no lifecycle authority."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: Optional[SupplierRFQResponseStatus] = None
    cost: Optional[float] = None
    currency: Optional[str] = None
    transit_time: Optional[str] = None
    validity_date: Optional[str] = None
    equipment_type: Optional[str] = None
    notes: Optional[str] = None
    uncertain_fields: list[CommercialResponseField] = Field(
        default_factory=list
    )

    @field_validator(
        "currency",
        "transit_time",
        "validity_date",
        "equipment_type",
        "notes",
    )
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value is not None else None

    @field_validator("uncertain_fields")
    @classmethod
    def validate_unique_uncertain_fields(
        cls,
        value: list[CommercialResponseField],
    ) -> list[CommercialResponseField]:
        if len(value) != len(set(value)):
            raise ValueError("uncertain_fields must not contain duplicates.")
        return value

    @model_validator(mode="after")
    def validate_uncertain_values_are_absent(self):
        for field_name in self.uncertain_fields:
            if getattr(self, field_name) is not None:
                raise ValueError(
                    f"Uncertain field must not include a value: {field_name}"
                )
        return self

    def field_state(
        self,
        field_name: CommercialResponseField,
    ) -> CommercialFieldState:
        if field_name in self.uncertain_fields:
            return "uncertain"
        if getattr(self, field_name) is None:
            return "not_provided"
        return "provided"


class SupplierRFQCorrelationResult(BaseModel):
    status: SupplierRFQCorrelationStatus
    rfq_id: Optional[str] = None
    method: Optional[SupplierRFQCorrelationMethod] = None
    reason: str
    candidate_rfq_ids: list[str] = Field(default_factory=list)
    source: str = "supplier_reply_correlator"


class SupplierReplyIngestionResult(BaseModel):
    status: SupplierReplyIngestionStatus
    reason: str
    rfq_id: Optional[str] = None
    correlation_method: Optional[SupplierRFQCorrelationMethod] = None
    external_message_id: Optional[str] = None
    response: Optional[SupplierRFQResponse] = None
    supplier_rfq: Optional[SupplierRFQDraft] = None
    source: str = "supplier_reply_ingestion"


_RFQ_REFERENCE_PATTERN = re.compile(
    rf"{re.escape(SUPPLIER_RFQ_REFERENCE_PREFIX)}([A-Za-z0-9._-]+)",
    flags=re.IGNORECASE,
)


def _normalize_rfq_reference(value: str) -> str:
    match = _RFQ_REFERENCE_PATTERN.search(value)
    if match:
        return match.group(1)
    return value.strip().strip("[]")


def _subject_rfq_ids(subject: Optional[str]) -> list[str]:
    if not subject:
        return []
    return list(dict.fromkeys(_RFQ_REFERENCE_PATTERN.findall(subject)))


def _sender_matches_draft(
    reply: InboundSupplierReply,
    draft: SupplierRFQDraft,
) -> bool:
    if not draft.recipient_email:
        return False
    return draft.recipient_email.strip().lower() == reply.sender_address


def _correlate_referenced_draft(
    *,
    reply: InboundSupplierReply,
    repository: SupplierRFQRepository,
    rfq_id: str,
    method: SupplierRFQCorrelationMethod,
) -> SupplierRFQCorrelationResult:
    draft = repository.get_draft(rfq_id)
    if draft is None:
        return SupplierRFQCorrelationResult(
            status="unresolved_rfq",
            method=method,
            reason=f"No Supplier RFQ matches reference: {rfq_id}",
        )
    if draft.status != "awaiting_response":
        return SupplierRFQCorrelationResult(
            status="rfq_not_awaiting_response",
            rfq_id=draft.rfq_id,
            method=method,
            reason=(
                "Supplier RFQ is not awaiting a response; "
                f"current status is {draft.status}."
            ),
        )
    if not _sender_matches_draft(reply, draft):
        return SupplierRFQCorrelationResult(
            status="invalid_supplier",
            rfq_id=draft.rfq_id,
            method=method,
            reason=(
                "Inbound sender address does not match the RFQ supplier "
                "contact."
            ),
        )
    return SupplierRFQCorrelationResult(
        status="matched",
        rfq_id=draft.rfq_id,
        method=method,
        reason="Supplier RFQ matched deterministically.",
    )


def correlate_supplier_reply(
    reply: InboundSupplierReply,
    repository: SupplierRFQRepository,
) -> SupplierRFQCorrelationResult:
    if reply.explicit_rfq_reference:
        explicit_rfq_id = _normalize_rfq_reference(
            reply.explicit_rfq_reference
        )
        conflicting_subject_ids = [
            rfq_id
            for rfq_id in _subject_rfq_ids(reply.subject)
            if rfq_id != explicit_rfq_id
        ]
        if conflicting_subject_ids:
            return SupplierRFQCorrelationResult(
                status="ambiguous_rfq",
                method="explicit_reference",
                reason=(
                    "Explicit and subject Supplier RFQ references conflict."
                ),
                candidate_rfq_ids=[
                    explicit_rfq_id,
                    *conflicting_subject_ids,
                ],
            )
        return _correlate_referenced_draft(
            reply=reply,
            repository=repository,
            rfq_id=explicit_rfq_id,
            method="explicit_reference",
        )

    subject_rfq_ids = _subject_rfq_ids(reply.subject)
    if len(subject_rfq_ids) > 1:
        return SupplierRFQCorrelationResult(
            status="ambiguous_rfq",
            method="subject_reference",
            reason="Subject contains multiple Supplier RFQ references.",
            candidate_rfq_ids=subject_rfq_ids,
        )
    if len(subject_rfq_ids) == 1:
        return _correlate_referenced_draft(
            reply=reply,
            repository=repository,
            rfq_id=subject_rfq_ids[0],
            method="subject_reference",
        )

    sender_drafts = [
        draft
        for draft in repository.list_drafts()
        if _sender_matches_draft(reply, draft)
    ]
    awaiting_drafts = [
        draft
        for draft in sender_drafts
        if draft.status == "awaiting_response"
    ]
    if len(awaiting_drafts) == 1:
        draft = awaiting_drafts[0]
        return SupplierRFQCorrelationResult(
            status="matched",
            rfq_id=draft.rfq_id,
            method="supplier_identity",
            reason=(
                "Supplier sender address uniquely matches one awaiting RFQ."
            ),
        )
    if len(awaiting_drafts) > 1:
        return SupplierRFQCorrelationResult(
            status="ambiguous_rfq",
            method="supplier_identity",
            reason=(
                "Supplier sender address matches multiple awaiting RFQs."
            ),
            candidate_rfq_ids=[draft.rfq_id for draft in awaiting_drafts],
        )
    if len(sender_drafts) == 1:
        draft = sender_drafts[0]
        return SupplierRFQCorrelationResult(
            status="rfq_not_awaiting_response",
            rfq_id=draft.rfq_id,
            method="supplier_identity",
            reason=(
                "The only RFQ matching this sender is not awaiting a "
                f"response; current status is {draft.status}."
            ),
        )
    if len(sender_drafts) > 1:
        return SupplierRFQCorrelationResult(
            status="ambiguous_rfq",
            method="supplier_identity",
            reason="Supplier identity matches multiple non-awaiting RFQs.",
            candidate_rfq_ids=[draft.rfq_id for draft in sender_drafts],
        )
    return SupplierRFQCorrelationResult(
        status="unresolved_rfq",
        reason="No deterministic Supplier RFQ match was found.",
    )
