from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AirRateTableRowStatus = Literal["proposed", "confirmed", "rejected"]
AirRateTableReviewStatus = Literal["pending", "partially_reviewed", "completed", "no_candidates"]


def _valid_break_key(value: str) -> bool:
    if value == "MIN":
        return True
    return value.startswith("+") and value[1:].isdigit() and 0 < int(value[1:]) <= 5000


class AirRateTableRowCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=12, max_length=64)
    destination_label: str = Field(min_length=1, max_length=160)
    destination_code: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    rates: dict[str, Decimal] = Field(min_length=2, max_length=20)
    source_line_number: int = Field(ge=1)
    source_line_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    detection_method: Literal["deterministic_table_v1"] = "deterministic_table_v1"
    status: AirRateTableRowStatus = "proposed"
    reviewed_by: Optional[str] = Field(default=None, max_length=200)
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = Field(default=None, max_length=800)

    @field_validator("destination_label", "reviewed_by", "review_note", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return None
        normalized = " ".join(str(value).strip().split())
        return normalized or None

    @field_validator("destination_code", "currency", mode="before")
    @classmethod
    def normalize_code(cls, value):
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @field_validator("rates")
    @classmethod
    def validate_rates(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        for key, amount in value.items():
            if not _valid_break_key(key):
                raise ValueError(f"Unsupported air-rate break key: {key}")
            if not amount.is_finite() or amount <= 0 or amount > Decimal("1000000"):
                raise ValueError("Air-rate row values must be finite positive bounded decimals.")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_review_time(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Air rate row review timestamp must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_review_evidence(self):
        if self.status == "proposed":
            if self.reviewed_by is not None or self.reviewed_at is not None or self.review_note is not None:
                raise ValueError("Proposed air-rate row cannot carry review evidence.")
        elif not self.reviewed_by or self.reviewed_at is None or not self.review_note:
            raise ValueError("Reviewed air-rate row requires actor, time and note.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False


class AirRateTableReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    structure_review_id: str = Field(min_length=1, max_length=200)
    extracted_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_version: Literal["air_rate_table_v1"] = "air_rate_table_v1"
    ai_parser_called: Literal[False] = False
    weight_breaks: list[str] = Field(min_length=2, max_length=20)
    candidates: list[AirRateTableRowCandidate] = Field(default_factory=list, max_length=250)
    status: AirRateTableReviewStatus = "pending"
    requested_by: str = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("weight_breaks")
    @classmethod
    def validate_weight_breaks(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not _valid_break_key(item) for item in value):
            raise ValueError("Air-rate table review has invalid or duplicate weight breaks.")
        return value

    @field_validator("requested_by", mode="before")
    @classmethod
    def normalize_actor(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air rate table review created_at must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_status(self):
        proposed = sum(item.status == "proposed" for item in self.candidates)
        if not self.candidates:
            expected = "no_candidates"
        elif proposed == len(self.candidates):
            expected = "pending"
        elif proposed:
            expected = "partially_reviewed"
        else:
            expected = "completed"
        if self.status != expected:
            raise ValueError("Air rate table review status does not match row states.")
        if len({item.candidate_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("Air rate table review candidate identifiers must be unique.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False
