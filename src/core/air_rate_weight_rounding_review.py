from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AirWeightRoundingMode = Literal["none", "ceiling"]


class AirRateWeightRoundingReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rounding_mode: AirWeightRoundingMode
    increment_kg: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("100"))
    applies_to: Literal["chargeable_weight_before_break_evaluation"] = (
        "chargeable_weight_before_break_evaluation"
    )
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    review_note: str = Field(min_length=1, max_length=800)
    source: Literal["air_rate_weight_rounding_review_v1"] = (
        "air_rate_weight_rounding_review_v1"
    )

    @field_validator("reviewed_by", "review_note", mode="before")
    @classmethod
    def normalize_text(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_review_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air weight-rounding review timestamp must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_rule(self):
        if self.rounding_mode == "none" and self.increment_kg is not None:
            raise ValueError("No-rounding review cannot carry an increment.")
        if self.rounding_mode == "ceiling" and self.increment_kg is None:
            raise ValueError("Ceiling rounding review requires increment_kg.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False

    @property
    def customer_pricing_authority(self) -> bool:
        return False
