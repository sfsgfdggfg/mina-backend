from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AirRateValidityReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid_from: date
    valid_to: date
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    review_note: str = Field(min_length=1, max_length=800)

    @field_validator("reviewed_by", "review_note", mode="before")
    @classmethod
    def normalize_text(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_review_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air tariff validity review timestamp must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_range(self):
        if self.valid_to < self.valid_from:
            raise ValueError("Air tariff validity valid_to cannot precede valid_from.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False
