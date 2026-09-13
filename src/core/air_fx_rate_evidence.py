from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AirFxEvidenceSource = Literal["bank", "central_bank", "airline", "manual_document", "other"]


class AirFxRateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    inquiry_reference: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    quote_currency: str = Field(pattern=r"^[A-Z]{3}$")
    rate: Decimal = Field(gt=0)
    effective_at: datetime
    evidence_source: AirFxEvidenceSource
    evidence_reference: str = Field(min_length=1, max_length=500)
    evidence_note: str = Field(min_length=1, max_length=800)
    recorded_by: str = Field(min_length=1, max_length=200)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["air_fx_rate_evidence_v1"] = "air_fx_rate_evidence_v1"

    @field_validator(
        "entry_id", "inquiry_reference", "evidence_reference", "evidence_note", "recorded_by",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @field_validator("base_currency", "quote_currency", mode="before")
    @classmethod
    def normalize_currency(cls, value):
        return str(value or "").strip().upper()
    @field_validator("effective_at", "recorded_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air FX evidence timestamps must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_pair(self):
        if self.base_currency == self.quote_currency:
            raise ValueError("Air FX evidence requires two different currencies.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False

    @property
    def pricing_authority(self) -> bool:
        return False
