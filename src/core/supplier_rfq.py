from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.models import Shipment


SupplierRFQStatus = Literal[
    "draft",
    "approved",
    "sent",
    "awaiting_response",
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


class SupplierRFQManualSentEvidence(BaseModel):
    rfq_id: str
    recorded_by: str
    recorded_at: datetime
    source: Literal["manual_external_send"] = "manual_external_send"


class SupplierRFQWorkflow(BaseModel):
    workflow_id: str = Field(default_factory=lambda: str(uuid4()))
    shipment: Shipment
    email_text: Optional[str] = None
    rfq_ids: list[str] = Field(default_factory=list)
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
    equipment_type: Optional[str] = None
    notes: Optional[str] = None

    source: Literal["simulation", "email", "portal", "api", "manual"] = "manual"
    received_at: datetime = Field(default_factory=datetime.utcnow)

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

        return self

    @property
    def is_price_usable(self) -> bool:
        return (
            self.status == "quoted"
            and self.cost is not None
            and self.cost > 0
            and self.currency is not None
        )
