from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.models import Shipment
from src.core.supplier_dispatch_policy import SupplierDispatchPolicy


SupplierRFQStatus = Literal[
    "draft",
    "approved",
    "sent",
    "awaiting_response",
    "clarification_required",
    "responded",
    "expired",
    "cancelled",
]
QuoteProgressionStatus = Literal[
    "ready",
    "in_progress",
    "provenance_blocked",
    "completed",
]
SupplierRFQFollowUpStatus = Literal[
    "draft",
    "approved",
    "awaiting_response",
    "responded",
    "cancelled",
]

SUPPLIER_RFQ_REFERENCE_PREFIX = "MINAI-RFQ:"


def build_supplier_rfq_reference(rfq_id: str) -> str:
    return f"{SUPPLIER_RFQ_REFERENCE_PREFIX}{rfq_id}"


class SupplierContact(BaseModel):
    contact_name: Optional[str] = None
    email: str
    role: str = "pricing"
    is_primary: bool = False
    active: bool = True


class SupplierRFQDraft(BaseModel):
    rfq_id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str = Field(default_factory=lambda: str(uuid4()))
    supplier_name: str
    priority: int
    recipient_email: Optional[str] = None
    subject: str
    body: str
    status: SupplierRFQStatus = "draft"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    source: str = "supplier_rfq_generator"

    @property
    def has_recipient(self) -> bool:
        return bool(self.recipient_email)

    @property
    def reference_token(self) -> str:
        return build_supplier_rfq_reference(self.rfq_id)


class SupplierRFQAutomatedSentEvidence(BaseModel):
    rfq_id: str
    recipient_email: str
    provider_name: str
    provider_message_id: str
    sent_at: datetime
    source: Literal["automated_provider_send"] = "automated_provider_send"


class SupplierRFQManualSentEvidence(BaseModel):
    rfq_id: str
    recorded_by: str
    recorded_at: datetime
    source: Literal["manual_external_send"] = "manual_external_send"


class SupplierRFQFollowUpDraft(BaseModel):
    follow_up_id: str = Field(default_factory=lambda: str(uuid4()))
    rfq_id: str
    workflow_id: str
    sequence_number: int = Field(ge=1)
    recipient_email: str
    subject: str
    body: str
    rejection_reasons: list[str] = Field(default_factory=list)
    status: SupplierRFQFollowUpStatus = "draft"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    source: str = "supplier_follow_up_generator"

    @property
    def operation_id(self) -> str:
        return (
            f"supplier-rfq-clarification:{self.rfq_id}:"
            f"{self.sequence_number}"
        )

    @property
    def reference_token(self) -> str:
        return build_supplier_rfq_reference(self.rfq_id)


class SupplierRFQFollowUpAutomatedSentEvidence(BaseModel):
    follow_up_id: str
    rfq_id: str
    sequence_number: int = Field(ge=1)
    recipient_email: str
    provider_name: str
    provider_message_id: str
    sent_at: datetime
    source: Literal["automated_provider_send"] = "automated_provider_send"


class SupplierRFQFollowUpManualSentEvidence(BaseModel):
    follow_up_id: str
    rfq_id: str
    sequence_number: int = Field(ge=1)
    recorded_by: str
    recorded_at: datetime
    source: Literal["manual_external_send"] = "manual_external_send"


class SupplierRFQWorkflow(BaseModel):
    workflow_id: str = Field(default_factory=lambda: str(uuid4()))
    shipment: Shipment
    email_text: Optional[str] = None
    sender_address: Optional[str] = None
    rfq_ids: list[str] = Field(default_factory=list)
    dispatch_policy: SupplierDispatchPolicy = Field(
        default_factory=SupplierDispatchPolicy
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    quote_progression_status: QuoteProgressionStatus = "ready"
    quote_progression_attempt_count: int = Field(default=0, ge=0)
    quote_progression_started_at: Optional[datetime] = None
    quote_progressed_at: Optional[datetime] = None
    last_provenance_blocked_at: Optional[datetime] = None
    last_provenance_blocked_result_type: Optional[str] = None
    source: str = "supplier_rfq_workflow"

    @model_validator(mode="after")
    def validate_quote_progression_state(self):
        if (
            self.quote_progression_status
            in {"in_progress", "provenance_blocked", "completed"}
            and self.quote_progression_started_at is None
        ):
            raise ValueError(
                "A started quote progression requires a start time."
            )
        if self.quote_progression_status == "provenance_blocked":
            if (
                self.last_provenance_blocked_at is None
                or self.last_provenance_blocked_result_type
                != "data_provenance_blocked"
            ):
                raise ValueError(
                    "A provenance-blocked quote progression requires durable evidence."
                )
            if self.quote_progressed_at is not None:
                raise ValueError(
                    "A provenance-blocked quote progression cannot be completed."
                )
        if (
            self.quote_progression_status == "completed"
            and self.quote_progressed_at is None
        ):
            raise ValueError(
                "A completed quote progression requires a completion time."
            )
        return self


SupplierPricingBasis = Literal[
    "all_in",
    "base_freight_plus_extras",
]


SupplierRFQResponseStatus = Literal[
    "quoted",
    "no_capacity",
    "declined",
    "needs_clarification",
]


class SupplierRFQResponse(BaseModel):
    rfq_id: str = Field(default_factory=lambda: str(uuid4()))
    supplier_name: str
    rfq_priority: int
    status: SupplierRFQResponseStatus

    cost: Optional[float] = None
    currency: Optional[str] = None
    transit_time: Optional[str] = None
    validity_date: Optional[str] = None
    vehicle_available_date: Optional[str] = None
    equipment_type: Optional[str] = None
    pricing_basis: Optional[SupplierPricingBasis] = None
    included_costs: Optional[list[str]] = None
    excluded_costs: Optional[list[str]] = None
    notes: Optional[str] = None

    source: Literal["simulation", "email", "portal", "api", "manual"] = "manual"
    recorded_by: Optional[str] = None
    received_at: datetime = Field(default_factory=datetime.utcnow)
    is_consolidated_follow_up: bool = False
    inherited_fields: list[str] = Field(default_factory=list)
    prior_response_received_at: Optional[datetime] = None
    source_attachment_review_id: Optional[str] = None

    @field_validator("cost", mode="before")
    @classmethod
    def validate_cost_type(cls, value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                "Supplier RFQ response cost must be numeric."
            )
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError(
                "Supplier RFQ response currency must be a 3-letter code."
            )
        return normalized

    @model_validator(mode="after")
    def validate_status_data_consistency(self):
        if self.status == "quoted":
            if self.cost is None or self.cost <= 0:
                raise ValueError(
                    "Quoted RFQ response must have a positive cost."
                )

            if self.currency is None:
                raise ValueError(
                    "Quoted RFQ response must include currency."
                )

        else:
            if self.cost is not None:
                raise ValueError(
                    "Non-quoted RFQ response must not include a cost."
                )

            if self.currency is not None:
                raise ValueError(
                    "Non-quoted RFQ response must not include currency."
                )

        if self.is_consolidated_follow_up:
            if not self.inherited_fields or self.prior_response_received_at is None:
                raise ValueError(
                    "Consolidated follow-up response requires inherited-field provenance."
                )
        elif self.inherited_fields or self.prior_response_received_at is not None:
            raise ValueError(
                "Non-consolidated response must not carry inherited-field provenance."
            )
        return self

    @property
    def is_price_usable(self) -> bool:
        return (
            self.status == "quoted"
            and self.cost is not None
            and self.cost > 0
            and self.currency is not None
        )
