from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AirQuoteContextSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preparation_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    inquiry_reference: str = Field(min_length=1, max_length=300)
    customer_id: str = Field(min_length=1, max_length=200)
    customer_name: str = Field(min_length=1, max_length=240)

    source_id: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    airline_name: str = Field(min_length=1, max_length=200)
    origin_airport: Optional[str] = Field(default=None, min_length=3, max_length=3)
    destination_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    table_review_id: str = Field(min_length=1, max_length=300)
    candidate_id: str = Field(min_length=1, max_length=300)
    cost_scope_review_id: str = Field(min_length=1, max_length=300)
    unsupported_cost_semantics_review_id: str = Field(min_length=1, max_length=300)
    validity_review_id: Optional[str] = Field(default=None, max_length=300)
    rounding_review_id: Optional[str] = Field(default=None, max_length=300)
    availability_confirmation_id: Optional[str] = Field(default=None, max_length=300)

    service_date: date
    expected_delivery_date: Optional[date] = None
    routing_context: Literal["direct", "connecting"]
    via_airport: Optional[str] = Field(default=None, min_length=3, max_length=3)
    flight_reference: Optional[str] = Field(default=None, max_length=120)

    confirmed_cost_basis_amount: Decimal = Field(gt=0)
    confirmed_cost_basis_currency: str = Field(min_length=3, max_length=3)
    quoted_chargeable_weight_kg: Optional[Decimal] = Field(default=None, gt=0)
    customer_final_price: Decimal = Field(gt=0)
    customer_price_currency: str = Field(min_length=3, max_length=3)
    pricing_policy_source: Optional[str] = Field(default=None, max_length=80)

    fx_evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    additional_cost_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    prepared_by: str = Field(min_length=1, max_length=200)
    prepared_at: datetime
    source: Literal["air_quote_context_v1"] = "air_quote_context_v1"

    @field_validator("origin_airport", "destination_code", "via_airport")
    @classmethod
    def normalize_airports(cls, value):
        if value is None:
            return None
        return str(value).strip().upper()

    @field_validator("confirmed_cost_basis_currency", "customer_price_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("prepared_at")
    @classmethod
    def require_aware_prepared_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air quote prepared_at must be timezone-aware.")
        return value
