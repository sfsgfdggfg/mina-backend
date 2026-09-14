from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


AirAdditionalCostCategory = Literal[
    "pickup",
    "origin_handling",
    "origin_terminal",
    "documentation",
    "customs_service_fee",
    "destination_handling",
    "destination_terminal",
    "delivery",
    "other",
]
AirAdditionalCostQuantityBasis = Literal[
    "per_shipment", "per_awb", "per_hawb", "per_mawb"
]
AirAdditionalCostEvidenceSource = Literal[
    "email", "phone", "whatsapp", "portal", "manual_document", "other"
]


class AirAdditionalCostEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    inquiry_reference: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cost_category: AirAdditionalCostCategory
    provider_name: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, le=Decimal("1000000000"))
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    quantity_basis: AirAdditionalCostQuantityBasis
    evidence_source: AirAdditionalCostEvidenceSource
    evidence_reference: str = Field(min_length=1, max_length=500)
    evidence_note: str = Field(min_length=1, max_length=1200)
    recorded_by: str = Field(min_length=1, max_length=200)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["air_additional_cost_evidence_v1"] = "air_additional_cost_evidence_v1"

    @field_validator(
        "entry_id", "inquiry_reference", "provider_name", "evidence_reference",
        "evidence_note", "recorded_by", mode="before",
    )
    @classmethod
    def normalize_text(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value):
        return str(value or "").strip().upper()

    @field_validator("recorded_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air additional-cost evidence timestamp must be timezone-aware.")
        return value

    @property
    def runtime_authoritative(self) -> bool:
        return False

    @property
    def pricing_authority(self) -> bool:
        return False
