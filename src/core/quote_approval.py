from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from src.core.models import (
    CustomerQuote,
    QuoteDraft,
    SupplierQuote,
)


QuoteApprovalStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "invalidated",
]


class QuoteApprovalSnapshot(BaseModel):
    supplier_name: str
    supplier_cost: float
    final_price: float
    currency: str
    transit_time: Optional[str] = None
    supplier_validity_date: Optional[str] = None
    supplier_vehicle_available_date: Optional[str] = None
    supplier_equipment_type: Optional[str] = None
    supplier_pricing_basis: Optional[str] = None
    supplier_included_costs: Optional[list[str]] = None
    supplier_excluded_costs: Optional[list[str]] = None
    quote_subject: str
    quote_body: str

    @classmethod
    def from_quote(
        cls,
        supplier_quote: SupplierQuote,
        customer_quote: CustomerQuote,
        quote_draft: QuoteDraft,
    ) -> "QuoteApprovalSnapshot":
        return cls(
            supplier_name=supplier_quote.supplier_name,
            supplier_cost=supplier_quote.cost,
            final_price=customer_quote.final_price,
            currency=customer_quote.currency,
            transit_time=supplier_quote.transit_time,
            supplier_validity_date=supplier_quote.validity_date,
            supplier_vehicle_available_date=(
                supplier_quote.vehicle_available_date
            ),
            supplier_equipment_type=supplier_quote.equipment_type,
            supplier_pricing_basis=supplier_quote.pricing_basis,
            supplier_included_costs=supplier_quote.included_costs,
            supplier_excluded_costs=supplier_quote.excluded_costs,
            quote_subject=quote_draft.subject,
            quote_body=quote_draft.body,
        )

    def matches_quote(
        self,
        supplier_quote: SupplierQuote,
        customer_quote: CustomerQuote,
        quote_draft: QuoteDraft,
    ) -> bool:
        current_snapshot = self.from_quote(
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
        )
        return self == current_snapshot


class QuoteApproval(BaseModel):
    approval_id: str = Field(
        default_factory=lambda: str(uuid4())
    )
    approval_status: QuoteApprovalStatus = "pending"

    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    invalidated_by: Optional[str] = None
    invalidated_at: Optional[datetime] = None

    quote_snapshot: QuoteApprovalSnapshot
    created_at: datetime = Field(default_factory=datetime.utcnow)

    source: str = "quote_approval_engine"

    @model_validator(mode="after")
    def validate_approval_state(self):
        if self.approval_status == "approved":
            if not self.approved_by:
                raise ValueError(
                    "Approved quote must include approved_by."
                )

            if self.approved_at is None:
                raise ValueError(
                    "Approved quote must include approved_at."
                )

            if (
                self.rejected_by is not None
                or self.rejected_at is not None
                or self.rejection_reason is not None
                or self.invalidated_by is not None
                or self.invalidated_at is not None
            ):
                raise ValueError(
                    "Approved quote contains incompatible decision metadata."
                )

        elif self.approval_status == "rejected":
            if not self.rejection_reason:
                raise ValueError(
                    "Rejected quote must include "
                    "rejection_reason."
                )

            if not self.rejected_by or self.rejected_at is None:
                raise ValueError(
                    "Rejected quote must include rejection operator metadata."
                )

            if (
                self.approved_by is not None
                or self.approved_at is not None
                or self.invalidated_by is not None
                or self.invalidated_at is not None
            ):
                raise ValueError(
                    "Rejected quote contains incompatible decision metadata."
                )

        elif self.approval_status == "invalidated":
            if not self.invalidated_by or self.invalidated_at is None:
                raise ValueError(
                    "Invalidated quote must include invalidation operator metadata."
                )

            if (
                self.approved_by is not None
                or self.approved_at is not None
                or self.rejected_by is not None
                or self.rejected_at is not None
                or self.rejection_reason is not None
            ):
                raise ValueError(
                    "Invalidated quote contains incompatible decision metadata."
                )

        else:
            if (
                self.approved_by is not None
                or self.approved_at is not None
                or self.rejected_by is not None
                or self.rejected_at is not None
                or self.rejection_reason is not None
                or self.invalidated_by is not None
                or self.invalidated_at is not None
            ):
                raise ValueError(
                    "Pending approval must not include decision metadata."
                )

        return self

    @property
    def is_approved(self) -> bool:
        return self.approval_status == "approved"

    def is_valid_for_quote(
        self,
        supplier_quote: SupplierQuote,
        customer_quote: CustomerQuote,
        quote_draft: QuoteDraft,
    ) -> bool:
        return (
            self.is_approved
            and self.quote_snapshot.matches_quote(
                supplier_quote=supplier_quote,
                customer_quote=customer_quote,
                quote_draft=quote_draft,
            )
        )
