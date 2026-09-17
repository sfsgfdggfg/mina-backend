from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupplierAwardSelection(BaseModel):
    """Append-only operator selection of an exact supplier-price offer."""

    model_config = ConfigDict(extra="forbid")

    selection_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str = Field(min_length=1, max_length=300)
    mina_code: str = Field(pattern=r"^MINA\d{4}/[1-9]\d*$")
    supplier_name: str = Field(min_length=1, max_length=200)
    offer_id: str = Field(min_length=1, max_length=300)
    cost: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    source_type: str = Field(min_length=1, max_length=40)
    source_reference_id: str | None = Field(default=None, max_length=300)
    rfq_id: str | None = Field(default=None, max_length=300)
    fixed_rate_id: str | None = Field(default=None, max_length=300)
    selected_by: str = Field(min_length=1, max_length=200)
    selected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    supersedes_selection_id: str | None = Field(default=None, max_length=100)
    source: str = "approved_job_supplier_award"

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("selected_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Supplier award timestamp must be timezone-aware.")
        return value.astimezone(timezone.utc)

    @classmethod
    def from_offer(
        cls, *, job_id: str, mina_code: str, offer: Any, selected_by: str,
        selected_at: datetime, supersedes_selection_id: str | None,
    ) -> "SupplierAwardSelection":
        return cls(
            job_id=job_id, mina_code=mina_code, supplier_name=offer.supplier_name,
            offer_id=offer.offer_id, cost=float(offer.cost), currency=offer.currency,
            source_type=offer.source_type,
            source_reference_id=offer.source_reference_id, rfq_id=offer.rfq_id,
            fixed_rate_id=offer.fixed_rate_id, selected_by=selected_by,
            selected_at=selected_at, supersedes_selection_id=supersedes_selection_id,
        )
