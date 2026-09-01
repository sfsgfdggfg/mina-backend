from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.mail import InboundMailEnvelope
from src.core.supplier_response_ingestion import SupplierResponseExtraction

AttachmentReviewRoute = Literal["customer", "supplier"]
AttachmentReviewStatus = Literal["pending", "applied", "rejected"]


class AttachmentReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_profile: Literal["pdf", "xlsx", "csv"]
    size_bytes: int = Field(ge=0)
    sha256_hex: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)


class AttachmentInterpretationReview(BaseModel):
    """Durable human-review case for a non-authoritative attachment interpretation."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    route: AttachmentReviewRoute
    status: AttachmentReviewStatus = "pending"
    source_message_key: str = Field(min_length=1, max_length=2048)
    source_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    inbound_mail: InboundMailEnvelope = Field(repr=False)
    attachment_evidence: list[AttachmentReviewEvidence] = Field(min_length=1, repr=False)
    privacy_transform_version: str = Field(min_length=1, max_length=64)
    source_character_count: int = Field(ge=0)
    source_table_count: int = Field(ge=0)

    trusted_customer_name: str | None = None
    rfq_id: str | None = None
    correlation_method: str | None = None
    expected_rfq_snapshot_sha256: str | None = Field(default=None, repr=False)

    customer_candidate: ShipmentProposalSnapshot | None = Field(default=None, repr=False)
    supplier_candidate: SupplierResponseExtraction | None = Field(default=None, repr=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    operator_corrections: dict = Field(default_factory=dict)
    changed_fields: list[str] = Field(default_factory=list)
    applied_proposal_id: str | None = None
    applied_rfq_id: str | None = None
    source: str = "attachment_interpretation_review"

    @model_validator(mode="after")
    def validate_route_and_state(self):
        if self.route == "customer":
            if self.customer_candidate is None or self.supplier_candidate is not None:
                raise ValueError("Customer review requires only a customer candidate.")
            if self.rfq_id is not None or self.expected_rfq_snapshot_sha256 is not None:
                raise ValueError("Customer review cannot carry Supplier RFQ state.")
        else:
            if self.supplier_candidate is None or self.customer_candidate is not None:
                raise ValueError("Supplier review requires only a supplier candidate.")
            if not self.rfq_id or not self.expected_rfq_snapshot_sha256:
                raise ValueError("Supplier review requires frozen RFQ provenance.")

        if self.status == "pending":
            if self.reviewed_by or self.reviewed_at or self.rejection_reason:
                raise ValueError("Pending review cannot contain review decision metadata.")
            if self.applied_proposal_id or self.applied_rfq_id:
                raise ValueError("Pending review cannot contain applied target metadata.")
        elif self.status == "rejected":
            if not self.reviewed_by or self.reviewed_at is None or not self.rejection_reason:
                raise ValueError("Rejected review requires operator, time and reason.")
            if self.applied_proposal_id or self.applied_rfq_id:
                raise ValueError("Rejected review cannot contain applied target metadata.")
        else:
            if not self.reviewed_by or self.reviewed_at is None or self.rejection_reason:
                raise ValueError("Applied review requires operator/time and no rejection reason.")
            if self.route == "customer" and not self.applied_proposal_id:
                raise ValueError("Applied customer review requires a proposal ID.")
            if self.route == "supplier" and not self.applied_rfq_id:
                raise ValueError("Applied supplier review requires an RFQ ID.")
        return self
